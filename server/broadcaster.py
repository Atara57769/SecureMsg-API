"""
broadcaster.py — In-memory pub/sub for Server-Sent Events.

HOW IT WORKS
  Every time a client opens GET /stream it registers an asyncio.Queue here.
  When a message is saved (POST /messages), the route calls broadcast() which
  puts a copy of the event into every registered queue.
  The SSE generator for each client pulls from its own queue and streams it.

  This is the simplest possible pub/sub — no external broker, no persistence.
  It lives only in the server process memory, which is fine for Stage 2.

THREAD SAFETY
  asyncio queues are coroutine-safe by design.  Because we're running a single
  asyncio event-loop inside uvicorn, no extra locking is needed.
"""

import asyncio
import logging
from typing import Any
from collections import defaultdict

log = logging.getLogger(__name__)

# The map of username -> set of connected client queues.
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def subscribe(username: str) -> asyncio.Queue:
    """Register a new SSE listener for *username* and return its personal queue."""
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[username].add(q)
    log.info("SSE subscriber added for '%s' (total user queues=%d)",
             username, len(_subscribers[username]))
    return q


def unsubscribe(username: str, q: asyncio.Queue) -> None:
    """Remove a listener for *username* when its connection closes."""
    if username in _subscribers:
        _subscribers[username].discard(q)
        if not _subscribers[username]:
            del _subscribers[username]
    log.info("SSE subscriber removed for '%s'", username)


async def broadcast(username: str, event: Any) -> None:
    """Push *event* to every currently-connected client queue for *username*."""
    if username not in _subscribers:
        return

    dead: set[asyncio.Queue] = set()
    for q in _subscribers[username]:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # If a slow client's queue is full, drop the event for that client
            # rather than blocking the whole broadcast.
            dead.add(q)
            log.warning("SSE client queue full for '%s' — dropping event", username)

    for q in dead:
        _subscribers[username].discard(q)
    
    if username in _subscribers and not _subscribers[username]:
        del _subscribers[username]
