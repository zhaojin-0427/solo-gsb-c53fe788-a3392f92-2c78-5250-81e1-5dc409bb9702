"""SQLite 持久化：当前工作集（计划广告位 / 实播片段）与不可变核销报告。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DB_PATH = os.environ.get("APP_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"))

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS slots (
                slot_id          TEXT PRIMARY KEY,
                material_id      TEXT NOT NULL,
                planned_start    INTEGER NOT NULL,
                duration         INTEGER NOT NULL,
                tolerance        INTEGER NOT NULL,
                max_pause        INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS segments (
                seg_id           TEXT PRIMARY KEY,
                material_id      TEXT NOT NULL,
                air_start        INTEGER NOT NULL,
                air_end          INTEGER NOT NULL,
                src_start        INTEGER NOT NULL,
                src_end          INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id               TEXT PRIMARY KEY,
                created_at       TEXT NOT NULL,
                fingerprint      TEXT NOT NULL,
                payload          TEXT NOT NULL
            );
            """
        )


def load_workset() -> dict[str, list[dict[str, Any]]]:
    with _connect() as conn:
        slots = [dict(r) for r in conn.execute("SELECT * FROM slots ORDER BY slot_id")]
        segments = [dict(r) for r in conn.execute("SELECT * FROM segments ORDER BY seg_id")]
    return {"slots": slots, "segments": segments}


def replace_workset(slots: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    """整量替换当前计划与实播（单频道单工作集）。"""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM slots")
        conn.execute("DELETE FROM segments")
        conn.executemany(
            "INSERT INTO slots(slot_id, material_id, planned_start, duration, tolerance, max_pause)"
            " VALUES (:slot_id, :material_id, :planned_start, :duration, :tolerance, :max_pause)",
            slots,
        )
        conn.executemany(
            "INSERT INTO segments(seg_id, material_id, air_start, air_end, src_start, src_end)"
            " VALUES (:seg_id, :material_id, :air_start, :air_end, :src_start, :src_end)",
            segments,
        )


def save_report(payload: dict[str, Any]) -> dict[str, Any]:
    """保存不可变报告：含输入快照、分配证据、目标值与指纹。旧报告永不修改/删除。"""
    import hashlib

    created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    report_id = f"R-{time.strftime('%Y%m%d-%H%M%S')}-{fingerprint[:8]}"
    record = {
        "id": report_id,
        "created_at": created_at,
        "fingerprint": fingerprint,
        "payload": {**payload, "id": report_id, "created_at": created_at, "fingerprint": fingerprint},
    }
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO reports(id, created_at, fingerprint, payload) VALUES (?, ?, ?, ?)",
            (record["id"], record["created_at"], record["fingerprint"],
             json.dumps(record["payload"], ensure_ascii=False)),
        )
    return record["payload"]


def list_reports() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, created_at, fingerprint FROM reports ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_report(report_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM reports WHERE id = ?", (report_id,)).fetchone()
    return json.loads(row["payload"]) if row else None
