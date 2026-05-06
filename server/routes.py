"""
routes.py — All API route handlers.

╔══════════════════════════════════════════════╗
║  YOUR TASK: implement the four routes.       ║
╚══════════════════════════════════════════════╝

WHY A SEPARATE routes.py?
  In real projects, main.py only creates the app and wires things together.
  The actual logic lives in dedicated files — one per feature area.
  This keeps files small, focused, and easy to navigate.
  main.py imports this router and registers it with one line.

THE FOUR ROUTES YOU NEED TO IMPLEMENT:

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /register                                                      │
  │   Receives: RegisterRequest (username, password)                    │
  │   1. Check if the username is already taken → return 400 if so     │
  │   2. Hash the password (NEVER store plain text)                     │
  │   3. Save the new User to the database                              │
  │   4. Return a success message                                       │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /login                                                         │
  │   Receives: LoginRequest (username, password)                       │
  │   1. Find the user in the database → return 401 if not found       │
  │   2. Verify the password against the stored hash → 401 if wrong    │
  │   3. Create and return a JWT token                                  │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ POST /messages                          [requires valid JWT]        │
  │   Receives: SendMessageRequest (content, recipient)                 │
  │   1. Encrypt the content with encrypt()                             │
  │   2. Save a new Message row (sender=current user, recipient=...)    │
  │   3. Return the message as MessageResponse (with decrypted content) │
  └─────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────┐
  │ GET /messages                           [requires valid JWT]        │
  │   1. Fetch all messages from the database                           │
  │   2. Decrypt each message's ciphertext before returning             │
  │   3. Return a list of MessageResponse objects                       │
  │                                                                     │
  │   THINK ABOUT: should a user see ALL messages, or only those        │
  │   where they are the sender or recipient?                           │
  └─────────────────────────────────────────────────────────────────────┘

USEFUL IMPORTS ALREADY PROVIDED BELOW.
USEFUL PATTERN — how to query the database:
  user = db.query(User).filter(User.username == "alice").first()
  messages = db.query(Message).order_by(Message.created_at).all()

USEFUL PATTERN — how to save a new row:
  new_user = User(username="alice", password_hash="$2b$...")
  db.add(new_user)
  db.commit()
  db.refresh(new_user)   ← fills in the auto-generated id and created_at
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .models import get_db
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse,
)
from .auth import require_auth, decode_token
from . import services, broadcaster


log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# TODO 1 — Register a new user
# ---------------------------------------------------------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    return services.register_user(body, db)


# ---------------------------------------------------------------------------
# TODO 2 — Login and receive a JWT token
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    return services.authenticate_user(body, db)

# ---------------------------------------------------------------------------
# TODO 3 — Send a message (authenticated)
# ---------------------------------------------------------------------------
@router.post("/messages", response_model=list[MessageResponse], status_code=status.HTTP_201_CREATED)
async def send_message(
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    messages = services.process_send_message(body, username, db)
    
    # Push the new messages to all SSE listeners in real-time
    tasks = []
    
    # 1. Broadcast to each recipient individually
    for msg in messages:
        event = {
            "id":        msg.id,
            "sender":    msg.sender,
            "recipient": msg.recipient,
            "content":   msg.content,
            "created_at": msg.created_at.isoformat(),
        }
        if msg.sender != msg.recipient:
            tasks.append(broadcaster.broadcast(msg.recipient, event))
            
    # 2. Broadcast a single combined event to the sender (one entry for multiple recipients)
    if messages:
        all_recipients = ", ".join(body.recipients)
        sender_event = {
            "id":         messages[0].id,
            "sender":     username,
            "recipient":  all_recipients,
            "content":    body.content,
            "created_at": messages[0].created_at.isoformat(),
        }
        tasks.append(broadcaster.broadcast(username, sender_event))
            
    await asyncio.gather(*tasks)
    return messages


# ---------------------------------------------------------------------------
# TODO 4 — Fetch messages (authenticated)
# ---------------------------------------------------------------------------
@router.get("/messages", response_model=list[MessageResponse])
def get_messages(
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    return services.fetch_messages(username, db)


# ---------------------------------------------------------------------------
# SSE stream — real-time push of new messages to connected clients
# ---------------------------------------------------------------------------
@router.get("/stream")
async def stream(
    request: Request,
    token: str,                        # ?token=<JWT>  (query param for EventSource)
):
    """
    Open a persistent Server-Sent Events connection.

    The token is passed as a query parameter because the browser's native
    EventSource API (and the Python sseclient / httpx-sse libraries) cannot
    set Authorization headers.  In production you would use a short-lived
    one-time token fetched from a separate endpoint.

    Each SSE event is a JSON-encoded MessageResponse dict.
    The stream stays open indefinitely; a heartbeat comment is sent every
    15 seconds to keep proxies and firewalls from closing the connection.
    """
    username = decode_token(token)
    if username is None:
        # Return a proper HTTP 401 *before* the streaming response starts
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")

    log.info("SSE connection opened by '%s'", username)
    q = broadcaster.subscribe(username)

    async def event_generator():
        try:
            while True:
                # Check if the client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait up to 15 s for a new message; send a keepalive comment if none
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    payload = json.dumps(event)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment — invisible to the client, but prevents connection timeout
                    yield ": heartbeat\n\n"
        finally:
            broadcaster.unsubscribe(username, q)
            log.info("SSE connection closed for '%s'", username)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind a proxy
        },
    )
