
import asyncio
import json
import logging
from fastapi import HTTPException

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .models import get_db
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse, OnlineUsersResponse,
    UpdateMessageRequest,
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


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def patch_message(
    message_id: int,
    body: UpdateMessageRequest,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    msg = services.edit_message(message_id, username, body, db)
    
    # Broadcast edit event
    event = {
        "type": "edit",
        "id": msg.id,
        "sender": msg.sender,
        "recipient": msg.recipient,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
        "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
    }
    await asyncio.gather(
        broadcaster.broadcast(msg.recipient, event),
        broadcaster.broadcast(msg.sender, event)
    )
    return msg


@router.delete("/messages/{message_id}", response_model=MessageResponse)
async def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_auth),
):
    msg = services.delete_message(message_id, username, db)
    
    # Broadcast delete event
    event = {
        "type": "delete",
        "id": msg.id,
        "sender": msg.sender,
        "recipient": msg.recipient,
        "is_deleted": True,
    }
    await asyncio.gather(
        broadcaster.broadcast(msg.recipient, event),
        broadcaster.broadcast(msg.sender, event)
    )
    return msg


# ---------------------------------------------------------------------------
# Bonus 3 — Presence Indicator
# ---------------------------------------------------------------------------
@router.get("/users/online", response_model=OnlineUsersResponse)
def get_online_users(username: str = Depends(require_auth)):
    """Return list of currently connected users."""
    return {"online_users": broadcaster.get_active_users()}


# ---------------------------------------------------------------------------
# SSE stream — real-time push of new messages to connected clients
# ---------------------------------------------------------------------------
@router.get("/stream")
async def stream(
    request: Request,
    token: str | None = None,          # ?token=<JWT> (query param fallback for EventSource)
    db: Session = Depends(get_db),
):
    """
    Open a persistent Server-Sent Events connection.

    The token can be passed either via the standard 'Authorization: Bearer <token>'
    header, or as a query parameter '?token=<JWT>' (required because browser-native
    EventSource APIs cannot set headers).

    Each SSE event is a JSON-encoded MessageResponse dict.
    The stream stays open indefinitely; a heartbeat comment is sent every
    15 seconds to keep proxies and firewalls from closing the connection.
    """
    # 1. Extract token from header or fallback to query parameter
    auth_header = request.headers.get("Authorization")
    actual_token = None
    if auth_header and auth_header.startswith("Bearer "):
        actual_token = auth_header.split(" ", 1)[1]
    else:
        actual_token = token

    if not actual_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token"
        )

    from .models import User
    payload = decode_token(actual_token)
    if payload is None:
        # Return a proper HTTP 401 *before* the streaming response starts
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")
                            
    username = payload.get("sub")
    version = payload.get("version")
    
    if username is None or version is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid token payload")
                            
    # Validate version against database
    user = db.query(User).filter(User.username == username).first()
    if user is None or user.login_version != version:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session invalidated (logged in elsewhere)")

    log.info("SSE connection opened by '%s' (version %d)", username, version)
    q = await broadcaster.subscribe(username)

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
                    yield f"event: message\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment — invisible to the client, but prevents connection timeout
                    yield ": heartbeat\n\n"
        finally:
            await broadcaster.unsubscribe(username, q)
            log.info("SSE connection closed for '%s'", username)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind a proxy
        },
    )
