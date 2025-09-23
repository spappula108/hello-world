"""Authentication and authorization utilities.

Provides password hashing/verification (bcrypt), role checks, and demo user seeding.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from passlib.context import CryptContext

from .db import Database, User


DEMO_USERS = [
    {"username": "requester", "password": "requester123", "role": "Requester", "full_name": "Requester User"},
    {"username": "qc", "password": "qc123", "role": "QC", "full_name": "QC Analyst"},
    {"username": "qa", "password": "qa123", "role": "QA", "full_name": "QA Reviewer"},
    {"username": "admin", "password": "admin123", "role": "Admin", "full_name": "Administrator"},
]


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(plain_password, password_hash)
    except Exception:
        return False


@dataclass
class SessionUser:
    id: int
    username: str
    role: str
    full_name: str


class AuthService:
    """Simple authentication service backed by the database."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_seed_users(self, path: str) -> None:
        """Seed demo users if DB is empty.

        Reads from `path` if it exists; otherwise uses DEMO_USERS constant.
        """
        try:
            # If any user exists, skip seeding
            if self.database.get_user_by_username("admin") is not None:
                return
        except Exception:
            pass

        users = DEMO_USERS
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    users = json.load(f)
            except Exception:
                users = DEMO_USERS

        for u in users:
            if self.database.get_user_by_username(u["username"]) is None:
                self.database.create_user(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    full_name=u.get("full_name", u["username"]),
                )

    def authenticate(self, username: str, password: str) -> Optional[SessionUser]:
        user = self.database.get_user_by_username(username)
        if user and verify_password(password, user.password_hash):
            return SessionUser(id=user.id, username=user.username, role=user.role, full_name=user.full_name)
        return None

    def can_access_role(self, session_user: Optional[SessionUser], roles: list[str]) -> bool:
        if session_user is None:
            return False
        return session_user.role in roles

