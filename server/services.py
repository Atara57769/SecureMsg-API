import asyncio
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from . import repository, broadcaster
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse, UpdateMessageRequest
)
from .auth import hash_password, verify_password, create_token
from .crypto import encrypt, decrypt

log = logging.getLogger(__name__)

def register_user(body: RegisterRequest, db: Session) -> dict:
    user = repository.get_user_by_username(db, body.username)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    hashed_password = hash_password(body.password)
    repository.create_user(db, body.username, hashed_password)
    
    log.info("New user registered: '%s'", body.username)
    return {"message": "User registered successfully"}

def authenticate_user(body: LoginRequest, db: Session) -> dict:
    user = repository.get_user_by_username(db, body.username)
    
    # Timing attack mitigation: always execute a Bcrypt checkpw verification,
    # even if the username does not exist, to make the computation time uniform.
    # We use a structured, valid placeholder Bcrypt hash for non-existent users.
    dummy_hash = "$2b$12$eImiTXuWVMtY.n89.B.6IuxA.X/g19g2588s77977.B8B8B8B8B8B"
    stored_hash = user.password_hash if user else dummy_hash
    
    # Run Bcrypt verification (takes ~100ms)
    password_valid = verify_password(body.password, stored_hash)
    
    if not user or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Increment login version to invalidate old sessions
    user.login_version += 1
    db.commit()
    db.refresh(user)
    
    access_token = create_token(user.username, user.login_version) 
    log.info("User logged in: '%s' (version %d)", user.username, user.login_version)
    return {"access_token": access_token, "token_type": "bearer"}

def save_message(body: SendMessageRequest, username: str, db: Session) -> list[MessageResponse]:
    ciphertext = encrypt(body.content)
    results = []
    
    for recipient in body.recipients:
        new_message = repository.create_message(
            db, 
            sender=username, 
            recipient=recipient, 
            ciphertext=ciphertext
        )
        log.info("Message sent: '%s' -> '%s'", username, recipient)
        results.append(MessageResponse(
            id=new_message.id,
            sender=new_message.sender,
            recipient=new_message.recipient,
            content=body.content,
            created_at=new_message.created_at,
            updated_at=new_message.updated_at,
            is_deleted=new_message.is_deleted
        ))
    return results

async def broadcast_new_messages(messages: list[MessageResponse], recipients: list[str], content: str, username: str) -> None:
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
        all_recipients = ", ".join(recipients)
        sender_event = {
            "id":         messages[0].id,
            "sender":     username,
            "recipient":  all_recipients,
            "content":    content,
            "created_at": messages[0].created_at.isoformat(),
        }
        tasks.append(broadcaster.broadcast(username, sender_event))
            
    await asyncio.gather(*tasks)

async def process_send_message(body: SendMessageRequest, username: str, db: Session) -> list[MessageResponse]:
    messages = save_message(body, username, db)
    await broadcast_new_messages(messages, body.recipients, body.content, username)
    return messages

def fetch_messages(username: str, db: Session) -> list[MessageResponse]:
    messages = repository.get_messages_for_user(db, username)
    
    result = []
    for msg in messages:
        decrypted_content = decrypt(msg.ciphertext)
        result.append(MessageResponse(
            id=msg.id,
            sender=msg.sender,
            recipient=msg.recipient,
            content=decrypted_content,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
            is_deleted=msg.is_deleted
        ))
    return result

def update_message_content(message_id: int, username: str, body: UpdateMessageRequest, db: Session) -> MessageResponse:
    message = repository.get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    
    if message.sender != username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own messages")
    
    if message.is_deleted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit a deleted message")
        
    ciphertext = encrypt(body.content)
    repository.update_message(db, message, ciphertext=ciphertext)
    
    return MessageResponse(
        id=message.id,
        sender=message.sender,
        recipient=message.recipient,
        content=body.content,
        created_at=message.created_at,
        updated_at=message.updated_at,
        is_deleted=message.is_deleted
    )

async def broadcast_edit_event(msg: MessageResponse) -> None:
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

async def edit_message(message_id: int, username: str, body: UpdateMessageRequest, db: Session) -> MessageResponse:
    msg = update_message_content(message_id, username, body, db)
    await broadcast_edit_event(msg)
    return msg

def mark_message_deleted(message_id: int, username: str, db: Session) -> MessageResponse:
    message = repository.get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    
    if message.sender != username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own messages")
    
    repository.update_message(db, message, is_deleted=True)
    
    return MessageResponse(
        id=message.id,
        sender=message.sender,
        recipient=message.recipient,
        content="", # Content is hidden for deleted messages
        created_at=message.created_at,
        updated_at=message.updated_at,
        is_deleted=message.is_deleted
    )

async def broadcast_delete_event(msg: MessageResponse) -> None:
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

async def delete_message(message_id: int, username: str, db: Session) -> MessageResponse:
    msg = mark_message_deleted(message_id, username, db)
    await broadcast_delete_event(msg)
    return msg

def decode_and_parse_token(actual_token: str | None) -> tuple[str, int]:
    """Decode and validate payload structure of a JWT token."""
    if not actual_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token"
        )

    from .auth import decode_token
    payload = decode_token(actual_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
                            
    username = payload.get("sub")
    version = payload.get("version")
    
    if username is None or version is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    return username, version

def validate_user_login_version(username: str, version: int, db: Session) -> None:
    """Validate user's login version against the database."""
    user = repository.get_user_by_username(db, username)
    if user is None or user.login_version != version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated (logged in elsewhere)"
        )

def validate_stream_token(actual_token: str | None, db: Session) -> tuple[str, int]:
    """Validate token for SSE stream and return (username, login_version)."""
    username, version = decode_and_parse_token(actual_token)
    validate_user_login_version(username, version, db)
    return username, version
