"""Resolve graph context from project-version zip bundles."""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from csr_agent.models import RefactoringTask


@dataclass(slots=True)
class GraphResolution:
    graph_available: bool
    graph_context_path: str | None = None
    source_zip: str | None = None
    zip_member: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    recoverable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_available": self.graph_available,
            "graph_context_path": self.graph_context_path,
            "source_zip": self.source_zip,
            "zip_member": self.zip_member,
            "confidence": self.confidence,
            "notes": list(self.notes),
            "recoverable": self.recoverable,
        }


class GraphResolver:
    """Locate and extract graphml from project-version zip archives."""

    def __init__(self, graph_root: Path | str, cache_root: Path | str) -> None:
        self.graph_root = Path(graph_root)
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, task: RefactoringTask) -> GraphResolution:
        notes: list[str] = []
        existing = (task.context.graph_context_path or "").strip()
        if existing:
            existing_path = Path(existing)
            if existing_path.exists():
                return GraphResolution(
                    graph_available=True,
                    graph_context_path=str(existing_path),
                    confidence=1.0,
                    notes=["use_existing_graph_context_path"],
                )
            notes.append("existing graph_context_path not found on disk")

        project_dir = self.graph_root / task.project
        if not project_dir.exists():
            return GraphResolution(
                graph_available=bool(task.context.graph_available),
                graph_context_path=task.context.graph_context_path,
                confidence=0.0,
                notes=notes + [f"project graph directory missing: {project_dir}"],
            )

        zips = sorted([p for p in project_dir.glob("*.zip") if p.is_file()])
        if not zips:
            return GraphResolution(
                graph_available=bool(task.context.graph_available),
                graph_context_path=task.context.graph_context_path,
                confidence=0.0,
                notes=notes + [f"no zip found under {project_dir}"],
            )

        hints = _build_version_hints(task)
        scored_zips = sorted(
            [(p, _score_zip(p, task.project, hints)) for p in zips],
            key=lambda x: x[1],
            reverse=True,
        )

        expected_members = _expected_member_names(task.project, task.task_id)
        best_zip_score = scored_zips[0][1] if scored_zips else 0.0
        for zip_path, zip_score in scored_zips:
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    members = [m for m in zf.namelist() if m.lower().endswith(".graphml")]
                    if not members:
                        continue

                    matched = _match_member(members, expected_members, task.task_id)
                    if matched is None:
                        continue

                    extract_to = (
                        self.cache_root
                        / task.project
                        / zip_path.stem
                        / Path(matched).name
                    )
                    extract_to.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(matched, "r") as src, extract_to.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

                    confidence = min(1.0, 0.6 + 0.4 * zip_score)
                    return GraphResolution(
                        graph_available=True,
                        graph_context_path=str(extract_to),
                        source_zip=str(zip_path),
                        zip_member=matched,
                        confidence=confidence,
                        notes=notes
                        + [
                            "graph_resolved_from_zip",
                            f"zip_score={zip_score:.3f}",
                            f"matched_member={matched}",
                        ],
                    )
            except zipfile.BadZipFile:
                notes.append(f"bad zip skipped: {zip_path}")
            except Exception as exc:
                notes.append(f"zip read failure {zip_path}: {exc}")

        return GraphResolution(
            graph_available=bool(task.context.graph_available),
            graph_context_path=task.context.graph_context_path,
            confidence=best_zip_score * 0.2,
            notes=notes
            + [
                "graphml_not_found_in_zip",
                f"expected_member_patterns={expected_members}",
            ],
        )


def _build_version_hints(task: RefactoringTask) -> list[str]:
    hints: list[str] = []
    for value in [
        task.version.resolved_begin_tag,
        task.version.begin_tag,
        task.version.version_hint,
        task.version.resolved_disappear_tag,
        task.version.disappear_tag,
        task.version.end_tag,
    ]:
        if value:
            hints.append(str(value))
    return hints


def _score_zip(zip_path: Path, project: str, hints: list[str]) -> float:
    stem = zip_path.stem.lower()
    normalized = _normalize(stem.replace(project.lower(), ""))
    if not hints:
        return 0.2
    best = 0.0
    for hint in hints:
        hint_norm = _normalize(str(hint).lower().replace(project.lower(), ""))
        if not hint_norm:
            continue
        ratio = SequenceMatcher(None, normalized, hint_norm).ratio()
        if hint_norm in normalized:
            ratio = min(1.0, ratio + 0.2)
        best = max(best, ratio)
    return best


def _expected_member_names(project: str, task_id: str) -> list[str]:
    return [
        f"{project}-{task_id}.graphml",
        f"{task_id}.graphml",
    ]


def _match_member(
    members: list[str],
    expected_names: list[str],
    task_id: str,
) -> str | None:
    expected_lower = {name.lower() for name in expected_names}
    for member in members:
        base = Path(member).name.lower()
        if base in expected_lower:
            return member

    # Fallback: member name contains task_id token.
    token = _normalize(task_id.lower())
    if token:
        for member in members:
            base = _normalize(Path(member).name.lower())
            if token and token in base:
                return member
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())
