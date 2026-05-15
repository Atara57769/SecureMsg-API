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

# The map of username -> list of connected client queues.
# Using a list ensures stable ordering for tests and predictable broadcasting.
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def get_active_users() -> list[str]:
    """Return a list of usernames that currently have at least one active connection."""
    return list(_subscribers.keys())


async def broadcast_all(event: Any) -> None:
    """Push *event* to EVERY currently-connected client queue."""
    tasks = []
    # Use list() to avoid issues if _subscribers changes during iteration
    for username in list(_subscribers.keys()):
        tasks.append(broadcast(username, event))
    if tasks:
        await asyncio.gather(*tasks)


async def subscribe(username: str) -> asyncio.Queue:
    """Register a new SSE listener for *username* and return its personal queue."""
    q: asyncio.Queue = asyncio.Queue()
    
    # If this is the user's first connection, they are now 'online'
    is_first = (username not in _subscribers)
    
    _subscribers[username].append(q)
    
    if is_first:
        await broadcast_all({
            "type": "presence",
            "username": username,
            "status": "online"
        })
        
    log.info("SSE subscriber added for '%s' (total user queues=%d)",
             username, len(_subscribers[username]))
    return q


async def unsubscribe(username: str, q: asyncio.Queue) -> None:
    """Remove a listener for *username* when its connection closes."""
    if username in _subscribers:
        if q in _subscribers[username]:
            _subscribers[username].remove(q)
        if not _subscribers[username]:
            del _subscribers[username]
            # If that was their last connection, they are now 'offline'
            await broadcast_all({
                "type": "presence",
                "username": username,
                "status": "offline"
            })
            
    log.info("SSE subscriber removed for '%s'", username)


async def broadcast(username: str, event: Any) -> None:
    """Push *event* to every currently-connected client queue for *username*."""
    if username not in _subscribers:
        return

    # Take a snapshot of the current subscribers to avoid issues if the list 
    # changes while we are iterating (e.g. if someone unsubscribes).
    current_queues = list(_subscribers[username])
    
    for q in current_queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # If a slow client's queue is full, drop the event for that client
            # rather than blocking the whole broadcast.
            if q in _subscribers[username]:
                _subscribers[username].remove(q)
            log.warning("SSE client queue full for '%s' — dropping event", username)
    
    if username in _subscribers and not _subscribers[username]:
        del _subscribers[username]
