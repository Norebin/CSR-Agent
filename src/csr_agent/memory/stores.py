"""Memory store implementations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from csr_agent.kb import SemanticCaseStore


class EpisodicStore:
    """SQLite-backed episodic memory per task."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, task_id: str, stage: str, payload: dict[str, Any], created_at: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO episodic_events (task_id, stage, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, stage, json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.commit()

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT stage, payload_json, created_at
                FROM episodic_events
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            )
            rows = cursor.fetchall()
        events: list[dict[str, Any]] = []
        for stage, payload_json, created_at in rows:
            events.append(
                {
                    "stage": stage,
                    "payload": json.loads(payload_json),
                    "created_at": created_at,
                }
            )
        return events


class SkillStore:
    """Rule-card based procedural memory store."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._skills = self._load_skills()

    def _load_skills(self) -> dict[str, list[dict[str, Any]]]:
        if self.path is None or not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return {}
        normalized: dict[str, list[dict[str, Any]]] = {}
        for smell, cards in data.items():
            if isinstance(cards, list):
                normalized[str(smell)] = [c for c in cards if isinstance(c, dict)]
        return normalized

    def get_for_smell(self, smell_type: str) -> list[dict[str, Any]]:
        return list(self._skills.get(smell_type, []))


class MemoryManager:
    """Facade over semantic / episodic / skill memory."""

    def __init__(
        self,
        semantic_store: SemanticCaseStore | None,
        episodic_store: EpisodicStore | None,
        skill_store: SkillStore | None,
    ) -> None:
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.skill_store = skill_store

    def get_skill_cards(self, smell_type: str) -> list[dict[str, Any]]:
        if self.skill_store is None:
            return []
        return self.skill_store.get_for_smell(smell_type)
