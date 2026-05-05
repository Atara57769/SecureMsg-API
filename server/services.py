from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from . import repository
from .schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    SendMessageRequest, MessageResponse
)
from .auth import hash_password, verify_password, create_token
from .crypto import encrypt, decrypt

def register_user(body: RegisterRequest, db: Session) -> dict:
    user = repository.get_user_by_username(db, body.username)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    hashed_password = hash_password(body.password)
    repository.create_user(db, body.username, hashed_password)
    
    return {"message": "User registered successfully"}

def authenticate_user(body: LoginRequest, db: Session) -> dict:
    user = repository.get_user_by_username(db, body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_token(user.username) 
    return {"access_token": access_token, "token_type": "bearer"}

def process_send_message(body: SendMessageRequest, username: str, db: Session) -> MessageResponse:
    ciphertext = encrypt(body.content)
    new_message = repository.create_message(
        db, 
        sender=username, 
        recipient=body.recipient, 
        ciphertext=ciphertext
    )
    
    return MessageResponse(
        id=new_message.id,
        sender=new_message.sender,
        recipient=new_message.recipient,
        content=body.content,
        created_at=new_message.created_at
    )

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
            created_at=msg.created_at
        ))
    return result
