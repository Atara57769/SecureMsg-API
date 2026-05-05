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

log = logging.getLogger(__name__)

# The set of all currently-connected client queues.
_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    """Register a new SSE listener and return its personal queue."""
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    log.info("SSE subscriber added  (total=%d)", len(_subscribers))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a listener when its connection closes."""
    _subscribers.discard(q)
    log.info("SSE subscriber removed (total=%d)", len(_subscribers))


async def broadcast(event: Any) -> None:
    """Push *event* to every currently-connected client queue."""
    dead: set[asyncio.Queue] = set()
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # If a slow client's queue is full, drop the event for that client
            # rather than blocking the whole broadcast.
            dead.add(q)
            log.warning("SSE client queue full — dropping event for slow consumer")
    for q in dead:
        _subscribers.discard(q)
