#!/usr/bin/env python3
"""
seed.py — Populate the database with test users and messages.

IDEMPOTENT: safe to run multiple times.
  - Users are only created if they don't already exist.
  - Messages are only seeded once (guarded by a sentinel message).

HOW TO RUN:
  python seed.py

USERS CREATED:
  alice  / password123
  bob    / password123
  charlie / password123

WHY THIS IS USEFUL:
  Lets you start two CLI clients immediately and see real-time SSE
  delivery without manually registering users first.
"""

import sys
import logging

import bcrypt

# ---------------------------------------------------------------------------
# Bootstrap: make sure the project root is on sys.path so we can import
# server modules without installing the package.
# ---------------------------------------------------------------------------
import pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from server.models import SessionLocal, create_tables, User, Message  # noqa: E402
from server.crypto import encrypt                                       # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("seed")

# ---------------------------------------------------------------------------
# Test users
# ---------------------------------------------------------------------------
USERS = [
    {"username": "alice",   "password": "password123"},
    {"username": "bob",     "password": "password123"},
    {"username": "charlie", "password": "password123"},
]

# ---------------------------------------------------------------------------
# Sample conversation (sender, recipient, plain-text content)
# ---------------------------------------------------------------------------
MESSAGES = [
    ("alice",   "bob",     "Hey Bob! Can you hear me?"),
    ("bob",     "alice",   "Loud and clear, Alice!"),
    ("alice",   "charlie", "Charlie, are you online?"),
    ("charlie", "alice",   "Yes! Just connected."),
    ("bob",     "charlie", "Welcome to the channel, Charlie!"),
    ("charlie", "bob",     "Thanks, Bob. This SSE stream is slick."),
    ("alice",   "bob",     "Group test: everyone reply to this."),
    ("bob",     "alice",   "Reply from Bob ✔"),
    ("charlie", "alice",   "Reply from Charlie ✔"),
]

# Sentinel: if this message already exists we skip seeding messages
SEED_SENTINEL = ("alice", "bob", "Hey Bob! Can you hear me?")


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def seed() -> None:
    create_tables()
    db = SessionLocal()

    try:
        # ── Users ──────────────────────────────────────────────────────────
        created_users = 0
        for spec in USERS:
            existing = db.query(User).filter(User.username == spec["username"]).first()
            if existing:
                log.info("User '%s' already exists — skipping.", spec["username"])
            else:
                db.add(User(username=spec["username"], password_hash=_hash(spec["password"])))
                created_users += 1
                log.info("Created user '%s'.", spec["username"])

        db.commit()
        log.info("Users: %d created, %d skipped.", created_users, len(USERS) - created_users)

        # ── Messages ───────────────────────────────────────────────────────
        sentinel_sender, sentinel_recipient, sentinel_content = SEED_SENTINEL
        already_seeded = (
            db.query(Message)
            .filter(
                Message.sender    == sentinel_sender,
                Message.recipient == sentinel_recipient,
            )
            .first()
        )

        if already_seeded:
            log.info("Messages already seeded — skipping.")
        else:
            for sender, recipient, content in MESSAGES:
                db.add(Message(
                    sender=sender,
                    recipient=recipient,
                    ciphertext=encrypt(content),
                ))
            db.commit()
            log.info("Seeded %d messages.", len(MESSAGES))

    finally:
        db.close()

    print()
    print("  ✔  Seed complete.")
    print("  ℹ  Run the server:   uvicorn server.main:app --reload")
    print("  ℹ  Run the client:   python -m client.client")
    print()


if __name__ == "__main__":
    seed()
