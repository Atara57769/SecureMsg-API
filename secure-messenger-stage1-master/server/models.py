"""
models.py — Database tables as Python classes (SQLAlchemy ORM).

╔══════════════════════════════════════════════╗
║  YOUR TASK: fill in the two table classes.   ║
╚══════════════════════════════════════════════╝

WHAT IS AN ORM?
  Instead of writing raw SQL like:
      CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, ...)
  you write a Python class and SQLAlchemy creates the table for you.
  Reading and writing rows becomes reading and writing Python objects.

WHAT IS SQLITE?
  A database that lives in a single file (messenger.db).
  No server to install, no configuration — just a file.
  Perfect for development and learning.

THE TWO TABLES YOU NEED:

  User — one row per registered user
    id            : integer, primary key
    username      : string, must be unique (no two users with the same name)
    password_hash : string  (NEVER store the plain password — only the hash)
    created_at    : datetime, set automatically when the row is created

  Message — one row per sent message
    id         : integer, primary key
    sender     : string  (the username of who sent it)
    recipient  : string  (the username of who should receive it)
    ciphertext : text    (the AES-encrypted content — NEVER store plain text)
    created_at : datetime, set automatically when the row is created

USEFUL REFERENCE:
  Mapped column types: String, Text, DateTime
  mapped_column options: primary_key=True, index=True, unique=True, nullable=False
  Auto-set timestamp: default=lambda: datetime.now(timezone.utc)
"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


DATABASE_URL = "sqlite:///./messenger.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    """
    FastAPI dependency — opens a DB session for one request, closes it after.
    You don't need to change this. Just use it in your routes:
        def my_route(db: Session = Depends(get_db)):
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# TODO 1 — Define the User table
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    # your columns here


# ---------------------------------------------------------------------------
# TODO 2 — Define the Message table
# ---------------------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"

    # your columns here


def create_tables():
    """Creates all tables in the database if they don't exist yet."""
    Base.metadata.create_all(bind=engine)
