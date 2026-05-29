"""RCKB builder and semantic store backed by FAISS with fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import numpy as np

from csr_agent.models import RefactoringCase, RefactoringTask

try:  # pragma: no cover - optional import branch
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional import branch
    faiss = None


class EmbeddingProvider(Protocol):
    def embed(self, text: str, dim: int = 128) -> list[float]:
        """Return a deterministic dense embedding."""


class HashEmbeddingProvider:
    """A deterministic non-LLM embedding provider for reproducible experiments."""

    def embed(self, text: str, dim: int = 128) -> list[float]:
        vec = np.zeros(dim, dtype=np.float32)
        tokens = text.lower().split()
        for token in tokens:
            idx = hash(token) % dim
            vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


class RCKBBuilder:
    """Build structured cases and persist semantic index artifacts."""

    def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

    def build_cases(self, tasks: list[RefactoringTask]) -> list[RefactoringCase]:
        cases: list[RefactoringCase] = []
        for task in tasks:
            source = task.context.raw_code or ""
            context_text = " ".join(
                filter(
                    None,
                    [
                        task.location.package_name if task.location else None,
                        task.location.type_name if task.location else None,
                        task.location.method_name if task.location else None,
                        task.context.comment,
                    ],
                )
            )
            pattern = str(task.context.refactorings or "")
            cases.append(
                RefactoringCase(
                    case_id=f"case_{task.task_id}",
                    unique_id=task.task_id,
                    project=task.project,
                    smell_type=task.smell_type,
                    source_snippet=source,
                    target_snippet_candidates=[],
                    refactor_action_sequence=_split_actions(pattern),
                    context_summary={
                        "file_path": task.file_path,
                        "graph_available": task.context.graph_available,
                    },
                    mapping_confidence=0.5,
                    data_noise_flags=[],
                    code_embedding=self.embedding_provider.embed(source),
                    context_embedding=self.embedding_provider.embed(context_text),
                    refactor_pattern_embedding=self.embedding_provider.embed(pattern),
                )
            )
        return cases

    def persist(
        self,
        cases: list[RefactoringCase],
        output_dir: Path | str,
    ) -> "SemanticCaseStore":
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        case_path = out / "cases.jsonl"

        with case_path.open("w", encoding="utf-8") as fh:
            for case in cases:
                fh.write(json.dumps(case.to_json_dict(), ensure_ascii=False) + "\n")

        vectors = np.array([c.code_embedding for c in cases], dtype=np.float32)
        ids = [c.case_id for c in cases]

        if len(vectors) > 0 and faiss is not None:
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            faiss.write_index(index, str(out / "semantic.index"))
            backend = "faiss"
        else:
            np.save(out / "semantic.npy", vectors)
            backend = "numpy"

        meta = {"backend": backend, "size": len(cases), "ids": ids}
        with (out / "index_meta.json").open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

        return SemanticCaseStore(cases=cases, vectors=vectors, backend=backend)

    def build_and_persist(
        self,
        tasks: list[RefactoringTask],
        output_dir: Path | str,
    ) -> "SemanticCaseStore":
        return self.persist(self.build_cases(tasks), output_dir)


class SemanticCaseStore:
    """Query abstraction over case embeddings."""

    def __init__(
        self,
        cases: list[RefactoringCase],
        vectors: np.ndarray,
        backend: str = "numpy",
    ) -> None:
        self.cases = cases
        self.vectors = vectors
        self.backend = backend
        self._faiss_index = None
        if backend == "faiss" and faiss is not None and len(vectors) > 0:
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            self._faiss_index = index

    def query(self, query_vector: list[float], top_n: int) -> list[tuple[RefactoringCase, float]]:
        if len(self.cases) == 0:
            return []

        q = np.array(query_vector, dtype=np.float32).reshape(1, -1)
        if self._faiss_index is not None:
            distances, idx = self._faiss_index.search(q, min(top_n, len(self.cases)))
            results: list[tuple[RefactoringCase, float]] = []
            for rank, case_idx in enumerate(idx[0]):
                if case_idx < 0:
                    continue
                results.append((self.cases[int(case_idx)], float(distances[0][rank])))
            return results

        scores = self.vectors @ q[0]
        pairs = list(enumerate(scores.tolist()))
        pairs.sort(key=lambda t: t[1], reverse=True)
        return [(self.cases[i], float(score)) for i, score in pairs[:top_n]]


def _split_actions(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    normalized = text.replace("|", ",").replace(";", ",")
    return [segment.strip() for segment in normalized.split(",") if segment.strip()]
