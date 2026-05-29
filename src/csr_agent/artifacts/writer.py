"""Task and experiment artifact writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactWriter:
    """Write structured outputs under configured output roots."""

    def __init__(self, output_root: Path | str) -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def task_dir(self, project: str, task_id: str) -> Path:
        path = self.output_root / project / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def experiment_dir(self, experiment_id: str) -> Path:
        path = self.output_root / "experiments" / experiment_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, path: Path | str, payload: dict[str, Any]) -> None:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with path_obj.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def write_text(self, path: Path | str, text: str) -> None:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(text, encoding="utf-8")
