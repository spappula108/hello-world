"""Database layer for the QA/QC workflow.

This module encapsulates SQLite access and provides high-level methods
to work with users, samples, analysis entries, decisions, and audit logs.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _utcnow_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    role: str
    full_name: str


class Database:
    """SQLite database accessor for the QA/QC app.

    The class creates tables on first initialization and exposes methods for
    common CRUD operations required by the application.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # --- connection helpers ---
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # --- schema ---
    def initialize(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    full_name TEXT NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT UNIQUE NOT NULL,
                    material TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    requester_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (requester_id) REFERENCES users(id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT NOT NULL,
                    analyst_id INTEGER NOT NULL,
                    results_json TEXT NOT NULL,
                    attachments_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (sample_id) REFERENCES samples(sample_id),
                    FOREIGN KEY (analyst_id) REFERENCES users(id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pass_fail TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    decided_by INTEGER NOT NULL,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY (sample_id) REFERENCES samples(sample_id),
                    FOREIGN KEY (decided_by) REFERENCES users(id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    details_json TEXT,
                    esign_username TEXT,
                    esign_signature_hash TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
                """
            )

            conn.commit()

    # --- users ---
    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cur.fetchone()
            if row is None:
                return None
            return User(
                id=row["id"],
                username=row["username"],
                password_hash=row["password_hash"],
                role=row["role"],
                full_name=row["full_name"],
            )

    def create_user(self, username: str, password_hash: str, role: str, full_name: str) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                (username, password_hash, role, full_name),
            )
            conn.commit()
            return int(cur.lastrowid)

    # --- samples ---
    def create_sample(self, sample_id: str, material: str, stage: str, requester_id: int, status: str) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            now = _utcnow_str()
            cur.execute(
                """
                INSERT INTO samples (sample_id, material, stage, requester_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sample_id, material, stage, requester_id, status, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_sample_status(self, sample_id: str, status: str) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE samples SET status = ?, updated_at = ? WHERE sample_id = ?",
                (status, _utcnow_str(), sample_id),
            )
            conn.commit()

    def get_samples_by_status(self, status: str) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM samples WHERE status = ? ORDER BY created_at DESC", (status,))
            return cur.fetchall()

    def get_sample(self, sample_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM samples WHERE sample_id = ?", (sample_id,))
            return cur.fetchone()

    def get_all_samples(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM samples ORDER BY created_at DESC")
            return cur.fetchall()

    # --- analyses ---
    def create_analysis(self, sample_id: str, analyst_id: int, results: Dict[str, Any], attachments: Optional[List[Dict[str, Any]]] = None) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO analyses (sample_id, analyst_id, results_json, attachments_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    sample_id,
                    analyst_id,
                    json.dumps(results),
                    json.dumps(attachments or []),
                    _utcnow_str(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_analyses_for_sample(self, sample_id: str) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM analyses WHERE sample_id = ? ORDER BY created_at DESC", (sample_id,))
            return cur.fetchall()

    # --- decisions ---
    def create_decision(self, sample_id: str, status: str, pass_fail: str, rationale: str, decided_by: int) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO decisions (sample_id, status, pass_fail, rationale, decided_by, decided_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sample_id, status, pass_fail, rationale, decided_by, _utcnow_str()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_decisions_for_sample(self, sample_id: str) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM decisions WHERE sample_id = ? ORDER BY decided_at DESC", (sample_id,))
            return cur.fetchall()

    # --- audit ---
    def log_audit(
        self,
        action: str,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        esign_username: Optional[str] = None,
        esign_signature_hash: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_log (timestamp, user_id, action, entity_type, entity_id, details_json, esign_username, esign_signature_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utcnow_str(),
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    json.dumps(details or {}),
                    esign_username,
                    esign_signature_hash,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def export_audit_rows(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY timestamp DESC")
            return cur.fetchall()

