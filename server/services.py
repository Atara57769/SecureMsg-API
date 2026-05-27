import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from . import repository
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

def process_send_message(body: SendMessageRequest, username: str, db: Session) -> list[MessageResponse]:
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

def edit_message(message_id: int, username: str, body: UpdateMessageRequest, db: Session) -> MessageResponse:
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

def delete_message(message_id: int, username: str, db: Session) -> MessageResponse:
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
