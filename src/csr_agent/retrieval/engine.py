"""Three-stage retrieval with configurable ranking modes and fallbacks."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from csr_agent.config import RetrievalConfig
from csr_agent.kb import HashEmbeddingProvider, SemanticCaseStore
from csr_agent.models import EvidenceItem, EvidencePack, RefactoringTask


@dataclass(slots=True)
class RetrievalScore:
    semantic: float
    structure: float
    refactor_prior: float


class RetrievalEngine:
    """Coarse recall -> context gate -> rerank -> evidence pack."""

    def __init__(self) -> None:
        self.embedding_provider = HashEmbeddingProvider()

    def retrieve(
        self,
        task: RefactoringTask,
        store: SemanticCaseStore,
        retrieval_cfg: RetrievalConfig,
    ) -> EvidencePack:
        if not retrieval_cfg.enabled:
            return EvidencePack(
                task_id=task.task_id,
                retrieval_mode="disabled",
                graph_available=task.context.graph_available,
                items=[],
                notes=["retrieval.disabled=true"],
            )

        query_text = " ".join(
            [
                task.context.raw_code or "",
                task.location.method_name or "" if task.location else "",
                task.location.type_name or "" if task.location else "",
                task.smell_type.value,
            ]
        )
        query_tokens = self._tokenize(query_text)
        query_vector = self.embedding_provider.embed(query_text)
        coarse = store.query(query_vector, top_n=retrieval_cfg.top_n_recall)
        gated = self._context_gate(task, coarse)

        if not gated:
            return EvidencePack(
                task_id=task.task_id,
                retrieval_mode=retrieval_cfg.mode,
                graph_available=task.context.graph_available,
                items=[],
                notes=["no retrieval candidates"],
            )

        case_docs = [self._case_text(case) for case, _ in gated]
        case_tokens = [self._tokenize(text) for text in case_docs]
        bm25_scores = self._bm25_like(query_tokens, case_tokens)
        sem_ranks = self._rank_map([sem for _, sem in gated])
        bm25_ranks = self._rank_map(bm25_scores)

        items: list[EvidenceItem] = []
        notes: list[str] = []
        weights = retrieval_cfg.weights.model_dump()
        mode = retrieval_cfg.mode.lower().strip()
        if not task.context.graph_available and mode in {
            "semantic_plus_context_plus_refactor_prior",
            "hybrid",
        }:
            weights = self._renormalize_missing_graph(weights)
            notes.append("context_missing.graph=true; weights renormalized")

        for idx, (case, sem_score) in enumerate(gated):
            score = self._score_case(task, case, sem_score, query_tokens)
            final = self._final_score(
                mode=mode,
                score=score,
                bm25=bm25_scores[idx],
                sem_rank=sem_ranks[idx],
                bm25_rank=bm25_ranks[idx],
                weights=weights,
            )
            items.append(
                EvidenceItem(
                    case_id=case.case_id,
                    source_project=case.project,
                    smell_type=case.smell_type,
                    score=float(final),
                    semantic_score=score.semantic,
                    structure_score=score.structure,
                    refactor_prior_score=score.refactor_prior,
                    payload={
                        "context_summary": case.context_summary,
                        "refactor_action_sequence": case.refactor_action_sequence,
                        "bm25_score": bm25_scores[idx],
                        "mode": mode,
                    },
                )
            )

        items.sort(key=lambda i: i.score, reverse=True)
        top_items = items[: retrieval_cfg.top_k_evidence]
        notes.append(f"retrieval_mode={mode}")
        return EvidencePack(
            task_id=task.task_id,
            retrieval_mode=retrieval_cfg.mode,
            graph_available=task.context.graph_available,
            items=top_items,
            notes=notes,
        )

    def _context_gate(
        self,
        task: RefactoringTask,
        coarse: list[tuple[Any, float]],
    ) -> list[tuple[Any, float]]:
        filtered: list[tuple[Any, float]] = []
        for case, sem_score in coarse:
            if case.smell_type != task.smell_type:
                continue
            filtered.append((case, sem_score))
        return filtered or coarse

    def _score_case(
        self,
        task: RefactoringTask,
        case: Any,
        sem_score: float,
        query_tokens: list[str],
    ) -> RetrievalScore:
        semantic = max(0.0, min(1.0, float(sem_score)))

        context_tokens = self._tokenize(self._case_context_text(case))
        structure = self._jaccard_score(query_tokens, context_tokens)
        if task.location and task.location.method_name:
            if task.location.method_name.lower() in self._case_context_text(case).lower():
                structure = max(structure, 0.9)
        if task.location and task.location.type_name:
            if task.location.type_name.lower() in self._case_context_text(case).lower():
                structure = min(1.0, structure + 0.1)

        prior = 0.1
        hint_tokens = self._tokenize(_to_text(task.context.refactorings))
        action_tokens = self._tokenize(" ".join(case.refactor_action_sequence))
        if hint_tokens and action_tokens:
            prior += 0.9 * self._jaccard_score(hint_tokens, action_tokens)
        elif action_tokens:
            prior += 0.2

        return RetrievalScore(
            semantic=max(0.0, min(1.0, semantic)),
            structure=max(0.0, min(1.0, structure)),
            refactor_prior=max(0.0, min(1.0, prior)),
        )

    def _final_score(
        self,
        *,
        mode: str,
        score: RetrievalScore,
        bm25: float,
        sem_rank: int,
        bm25_rank: int,
        weights: dict[str, float],
    ) -> float:
        if mode == "semantic_only":
            return score.semantic
        if mode == "context_only":
            return 0.7 * score.structure + 0.3 * score.refactor_prior
        if mode in {"bm25_like", "sparse_bm25"}:
            return bm25
        if mode in {"rrf", "rrf_dense_bm25", "hybrid_rrf"}:
            return (1.0 / (60 + sem_rank)) + (1.0 / (60 + bm25_rank))
        if mode in {"semantic_plus_context_plus_refactor_prior", "hybrid"}:
            return (
                weights["semantic"] * score.semantic
                + weights["structure"] * score.structure
                + weights["refactor_prior"] * score.refactor_prior
            )
        # Unknown mode falls back to weighted hybrid for safety.
        return (
            weights["semantic"] * score.semantic
            + weights["structure"] * score.structure
            + weights["refactor_prior"] * score.refactor_prior
        )

    def _rank_map(self, values: list[float]) -> dict[int, int]:
        ordered = sorted(enumerate(values), key=lambda x: x[1], reverse=True)
        rank_map: dict[int, int] = {}
        for rank, (idx, _) in enumerate(ordered, start=1):
            rank_map[idx] = rank
        return rank_map

    def _bm25_like(self, query_tokens: list[str], docs_tokens: list[list[str]]) -> list[float]:
        if not docs_tokens:
            return []
        if not query_tokens:
            return [0.0 for _ in docs_tokens]

        n_docs = len(docs_tokens)
        avgdl = sum(len(doc) for doc in docs_tokens) / max(1, n_docs)
        doc_freq: Counter[str] = Counter()
        for doc in docs_tokens:
            for token in set(doc):
                doc_freq[token] += 1

        k1 = 1.2
        b = 0.75
        scores: list[float] = []
        for doc in docs_tokens:
            tf = Counter(doc)
            dl = len(doc)
            score = 0.0
            for token in query_tokens:
                if token not in tf:
                    continue
                df = doc_freq[token]
                idf = math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))
                freq = float(tf[token])
                denom = freq + (k1 * (1.0 - b + b * (dl / max(1.0, avgdl))))
                score += idf * ((freq * (k1 + 1.0)) / max(1e-9, denom))
            scores.append(score)

        max_score = max(scores) if scores else 1.0
        if max_score <= 0:
            return [0.0 for _ in scores]
        return [float(s / max_score) for s in scores]

    def _case_text(self, case: Any) -> str:
        return " ".join(
            [
                str(case.source_snippet or ""),
                self._case_context_text(case),
                " ".join(case.refactor_action_sequence or []),
            ]
        )

    def _case_context_text(self, case: Any) -> str:
        parts: list[str] = []
        if isinstance(case.context_summary, dict):
            for v in case.context_summary.values():
                if v is None:
                    continue
                parts.append(str(v))
        return " ".join(parts)

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", text.lower())]

    def _jaccard_score(self, a: list[str], b: list[str]) -> float:
        sa = set(a)
        sb = set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / max(1, len(sa | sb))

    def _renormalize_missing_graph(self, weights: dict[str, float]) -> dict[str, float]:
        # Graph-aware structure score can be unreliable when graph context is missing.
        adjusted = dict(weights)
        adjusted["structure"] *= 0.5
        total = sum(adjusted.values())
        if total <= 0:
            return {"semantic": 1.0, "structure": 0.0, "refactor_prior": 0.0}
        return {k: v / total for k, v in adjusted.items()}


def _to_text(value: str | list[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)
