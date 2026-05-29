"""Version tag resolution with confidence scoring."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from csr_agent.models import RefactoringTask


@dataclass(slots=True)
class TagCandidate:
    tag: str
    score: float
    rationale: str


class VersionResolver:
    """Resolve incomplete version hints to concrete git tags."""

    def resolve(self, task: RefactoringTask, tags: list[str]) -> dict[str, object]:
        begin_hint = task.version.begin_tag or task.version.version_hint
        disappear_hint = task.version.disappear_tag or task.version.end_tag
        begin_candidates = self._rank_candidates(begin_hint, tags)
        disappear_candidates = self._rank_candidates(disappear_hint, tags)

        begin = begin_candidates[0] if begin_candidates else None
        disappear = disappear_candidates[0] if disappear_candidates else None

        return {
            "resolved_begin_tag": begin.tag if begin else None,
            "resolved_disappear_tag": disappear.tag if disappear else None,
            "begin_candidates": [asdict(c) for c in begin_candidates[:5]],
            "disappear_candidates": [asdict(c) for c in disappear_candidates[:5]],
            "confidence": self._joint_confidence(begin, disappear),
            "recoverable": bool(begin or disappear),
        }

    def _rank_candidates(self, hint: str | None, tags: list[str]) -> list[TagCandidate]:
        if not hint:
            return []
        hint_lower = hint.lower()
        hint_tuple = _extract_version_tuple(hint_lower)
        scored: list[TagCandidate] = []
        for tag in tags:
            tag_lower = tag.lower()
            exact_bonus = 0.2 if hint_lower in tag_lower else 0.0
            ratio = SequenceMatcher(None, hint_lower, tag_lower).ratio()
            version_bonus = _version_bonus(hint_tuple, _extract_version_tuple(tag_lower))
            score = min(1.0, ratio * 0.6 + exact_bonus + version_bonus)
            scored.append(
                TagCandidate(
                    tag=tag,
                    score=score,
                    rationale=(
                        f"ratio={ratio:.3f}, exact_bonus={exact_bonus:.1f}, "
                        f"version_bonus={version_bonus:.3f}"
                    ),
                )
            )
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored

    def _joint_confidence(
        self, begin: TagCandidate | None, disappear: TagCandidate | None
    ) -> float:
        scores = [c.score for c in (begin, disappear) if c is not None]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)


def _extract_version_tuple(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text)
    if not nums:
        return ()
    return tuple(int(n) for n in nums[:3])


def _version_bonus(hint: tuple[int, ...], tag: tuple[int, ...]) -> float:
    if not hint or not tag:
        return 0.0
    length = max(len(hint), len(tag))
    hint_pad = list(hint) + [0] * (length - len(hint))
    tag_pad = list(tag) + [0] * (length - len(tag))
    distance = sum(abs(a - b) for a, b in zip(hint_pad, tag_pad))
    return max(0.0, 0.4 - 0.08 * distance)
