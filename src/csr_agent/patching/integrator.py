"""Patch integration and conflict detection service."""

from __future__ import annotations

from collections import Counter

from csr_agent.models import PatchBundle, PatchProposal


class PatchIntegrator:
    """Merge patch proposals into one candidate diff."""

    def integrate(self, task_id: str, proposals: list[PatchProposal]) -> PatchBundle:
        merged_diff = "\n".join([p.unified_diff.strip() for p in proposals if p.unified_diff.strip()])
        conflicts = self._detect_conflicts(proposals)
        return PatchBundle(
            task_id=task_id,
            merged_diff=merged_diff,
            proposals=proposals,
            conflicts=conflicts,
        )

    def _detect_conflicts(self, proposals: list[PatchProposal]) -> list[str]:
        touched_files: list[str] = []
        for proposal in proposals:
            for line in proposal.unified_diff.splitlines():
                if line.startswith("--- a/") or line.startswith("+++ b/"):
                    touched_files.append(line[6:].strip())

        counts = Counter(touched_files)
        return [f"Potential conflict on {path}" for path, count in counts.items() if count > 2]
