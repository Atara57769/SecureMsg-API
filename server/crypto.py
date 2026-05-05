"""
crypto.py — AES-256-GCM encryption for messages stored in the database.

╔══════════════════════════════════════════════════════════════╗
║  THIS FILE IS COMPLETE — you do not need to change anything. ║
║  Read it, understand it, then use encrypt() and decrypt()    ║
║  in your routes.                                             ║
╚══════════════════════════════════════════════════════════════╝

HOW IT WORKS (the short version):
  The server has one secret key (256 bits, generated at startup).
  encrypt("hello") → scrambles the text into unreadable base64.
  decrypt(blob)    → unscrambles it back to "hello".
  Without the key, decryption is impossible.

WHY AES-GCM AND NOT JUST AES?
  GCM gives us two guarantees at once:
    1. Confidentiality — the content is hidden.
    2. Integrity      — if anyone tampers with the stored blob,
                        decryption raises an exception instead of
                        silently returning garbage.

WHY A FRESH NONCE EVERY TIME?
  Even if Alice sends "hello" ten times, each encrypted blob looks
  completely different. An attacker watching the database cannot
  detect repeated messages.

  The nonce is NOT secret — it is stored alongside the ciphertext.
  Its only job is to make each encryption unique.
"""

import os
import base64
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_KEY_FILE = Path(__file__).parent.parent / ".messenger.key"


def _load_or_create_key() -> bytes:
    """
    Load the AES key so it survives server restarts:

      1. MESSENGER_ENCRYPTION_KEY env var (hex string)  — preferred in production
      2. .messenger.key file in the project root        — auto-created on first run

    Without a stable key, every restart produces a new random key and the
    server can no longer decrypt messages stored in the database.
    """
    # 1. Environment variable (set this in production / CI)
    env_key = os.environ.get("MESSENGER_ENCRYPTION_KEY")
    if env_key:
        return bytes.fromhex(env_key)

    # 2. Persistent key file
    if _KEY_FILE.exists():
        return bytes.fromhex(_KEY_FILE.read_text().strip())

    # First run: generate, save, and use a fresh key
    key = os.urandom(32)
    _KEY_FILE.write_text(key.hex())
    _KEY_FILE.chmod(0o600)   # owner-read-only
    return key


_KEY: bytes = _load_or_create_key()


def encrypt(plaintext: str) -> str:
    """
    Encrypt a string. Returns a base64 blob safe to store in the database.

    Blob layout (concatenated, then base64-encoded):
        [ nonce: 12 bytes ][ ciphertext + auth-tag: variable ]
    """
    aesgcm = AESGCM(_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt(blob: str) -> str:
    """
    Decrypt a blob produced by encrypt(). Raises an exception if tampered with.
    """
    raw = base64.b64decode(blob.encode())
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_KEY)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
