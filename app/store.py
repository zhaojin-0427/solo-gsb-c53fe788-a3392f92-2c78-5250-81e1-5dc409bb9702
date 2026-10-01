"""SQLite 存储：不可变核销报告 + 输入快照。

报告一经写入永不修改/删除；每次提交计算都新增一行，因此输入修改并重算后，
旧报告仍可通过 report_id 查看。另维护单行 latest 指针指向最近一次计算。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def canonical_json(data: dict) -> str:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def input_hash(data: dict) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    channel         TEXT NOT NULL,
    input_hash      TEXT NOT NULL,
    input_snapshot  TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    verified_count  INTEGER NOT NULL,
    total_deviation INTEGER NOT NULL,
    slot_count      INTEGER NOT NULL,
    fragment_count  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    def save_report(self, dataset: dict, result: dict) -> dict:
        report_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot = canonical_json(dataset)
        row = {
            "id": report_id,
            "created_at": created_at,
            "channel": dataset.get("channel", "") or "",
            "input_hash": input_hash(dataset),
            "input_snapshot": snapshot,
            "result_json": canonical_json(result),
            "verified_count": int(result["verified_count"]),
            "total_deviation": int(result["total_deviation"]),
            "slot_count": len(dataset["slots"]),
            "fragment_count": len(dataset["fragments"]),
        }
        with self._lock:
            self._conn.execute(
                """INSERT INTO reports (id, created_at, channel, input_hash,
                       input_snapshot, result_json, verified_count,
                       total_deviation, slot_count, fragment_count)
                   VALUES (:id, :created_at, :channel, :input_hash,
                       :input_snapshot, :result_json, :verified_count,
                       :total_deviation, :slot_count, :fragment_count)""",
                row,
            )
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES('latest', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (report_id,),
            )
        return {"report_id": report_id, "created_at": created_at}

    def list_reports(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, created_at, channel, input_hash, verified_count,
                          total_deviation, slot_count, fragment_count
                   FROM reports ORDER BY created_at DESC, id DESC"""
            ).fetchall()
            latest = self.get_latest_id()
        out = []
        for r in rows:
            d = dict(r)
            d["is_latest"] = d["id"] == latest
            out.append(d)
        return out

    def get_latest_id(self) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM kv WHERE key='latest'"
        ).fetchone()
        return row["value"] if row else None

    def get_report(self, report_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reports WHERE id=?", (report_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "channel": row["channel"],
            "input_hash": row["input_hash"],
            "slot_count": row["slot_count"],
            "fragment_count": row["fragment_count"],
            "input": json.loads(row["input_snapshot"]),
            "result": json.loads(row["result_json"]),
            "is_latest": row["id"] == self.get_latest_id(),
        }
