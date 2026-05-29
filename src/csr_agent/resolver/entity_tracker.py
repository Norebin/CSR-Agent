"""Entity anchoring and cross-version tracking with uncertainty."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from csr_agent.models import EntityCandidate, EntityMapping, RefactoringTask


@dataclass(slots=True)
class TrackingFeatures:
    signature_similarity: float
    token_similarity: float
    ast_similarity: float
    call_neighborhood_similarity: float
    owner_consistency: float
    refactor_prior_score: float

    def total(self) -> float:
        return (
            0.25 * self.signature_similarity
            + 0.20 * self.token_similarity
            + 0.20 * self.ast_similarity
            + 0.15 * self.call_neighborhood_similarity
            + 0.10 * self.owner_consistency
            + 0.10 * self.refactor_prior_score
        )


class EntityTracker:
    """Heuristic entity tracker with recoverable uncertainty output."""

    def track(
        self,
        task: RefactoringTask,
        tracked_candidates: list[dict[str, str]] | None = None,
    ) -> EntityMapping:
        anchored = self._anchor_entity(task)
        if anchored is None:
            return EntityMapping(
                anchored=False,
                confidence=0.0,
                mapping_rationale="Failed to anchor target entity from task location.",
                recoverable=True,
            )

        candidates = self._build_candidates(task, anchored, tracked_candidates or [])
        if not candidates:
            return EntityMapping(
                anchored=True,
                best_match=anchored,
                alternatives=[],
                confidence=0.45,
                mapping_rationale="No cross-version candidates available; fallback to anchor.",
                recoverable=True,
            )

        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        best = ranked[0]
        alternatives = ranked[1:4]
        confidence = best.score
        return EntityMapping(
            anchored=True,
            best_match=best,
            alternatives=alternatives,
            confidence=confidence,
            mapping_rationale="Scored by signature/token/owner/refactor-prior features.",
            recoverable=True,
        )

    def _anchor_entity(self, task: RefactoringTask) -> EntityCandidate | None:
        location = task.location
        if location is None:
            return None
        method_name = location.method_name or "unknown_method"
        entity_id = f"{location.type_name or 'UnknownType'}::{method_name}"
        return EntityCandidate(
            entity_id=entity_id,
            file_path=location.file_path,
            method_signature=method_name,
            score=0.6,
            rationale="Anchored by package/type/method/file metadata.",
        )

    def _build_candidates(
        self,
        task: RefactoringTask,
        anchor: EntityCandidate,
        tracked_candidates: list[dict[str, str]],
    ) -> list[EntityCandidate]:
        raw_candidates = tracked_candidates or self._extract_candidates_from_context(task)
        output: list[EntityCandidate] = []
        for idx, candidate in enumerate(raw_candidates):
            signature = candidate.get("method_signature") or candidate.get("method_name", "")
            file_path = candidate.get("file_path", anchor.file_path)
            features = self._score_features(task, anchor, signature, file_path)
            output.append(
                EntityCandidate(
                    entity_id=f"candidate_{idx}",
                    file_path=file_path,
                    method_signature=signature or None,
                    score=features.total(),
                    rationale=(
                        f"sig={features.signature_similarity:.2f}, "
                        f"tok={features.token_similarity:.2f}, "
                        f"ast={features.ast_similarity:.2f}, "
                        f"call={features.call_neighborhood_similarity:.2f}, "
                        f"owner={features.owner_consistency:.2f}, "
                        f"prior={features.refactor_prior_score:.2f}"
                    ),
                )
            )
        return output

    def _extract_candidates_from_context(self, task: RefactoringTask) -> list[dict[str, str]]:
        source = task.context.raw_code or ""
        pattern = re.compile(r"(?:public|private|protected)?\s+\w+[<>\w,\s]*\s+(\w+)\s*\(")
        names = pattern.findall(source)
        return [{"method_name": name, "file_path": task.file_path} for name in names]

    def _score_features(
        self,
        task: RefactoringTask,
        anchor: EntityCandidate,
        signature: str,
        file_path: str | None,
    ) -> TrackingFeatures:
        method_ref = task.location.method_name if task.location else ""
        sig_sim = _sim(signature, method_ref or "")
        tok_sim = _sim(signature.replace(" ", ""), (task.context.raw_code or "")[:80])
        ast_sim = min(1.0, 0.4 + 0.6 * sig_sim)
        call_sim = 0.5 if signature and signature in (task.context.raw_code or "") else 0.2
        owner_consistency = 1.0 if file_path == anchor.file_path else 0.4
        refactors_text = str(task.context.refactorings or "").lower()
        prior = 0.8 if any(k in refactors_text for k in ("move", "rename", "extract")) else 0.3
        return TrackingFeatures(
            signature_similarity=sig_sim,
            token_similarity=tok_sim,
            ast_similarity=ast_sim,
            call_neighborhood_similarity=call_sim,
            owner_consistency=owner_consistency,
            refactor_prior_score=prior,
        )


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
