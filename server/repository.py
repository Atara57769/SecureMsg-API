from sqlalchemy.orm import Session
from .models import User, Message

def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, username: str, password_hash: str) -> User:
    new_user = User(username=username, password_hash=password_hash)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def create_message(db: Session, sender: str, recipient: str, ciphertext: str) -> Message:
    new_message = Message(
        sender=sender,
        recipient=recipient,
        ciphertext=ciphertext
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    return new_message

def get_messages_for_user(db: Session, username: str) -> list[Message]:
    return db.query(Message).filter(
        ((Message.sender == username) | (Message.recipient == username)),
        Message.is_deleted == False
    ).order_by(Message.created_at).all()

def get_message_by_id(db: Session, message_id: int) -> Message | None:
    return db.query(Message).filter(Message.id == message_id).first()

def update_message(db: Session, message: Message, **kwargs) -> Message:
    for key, value in kwargs.items():
        setattr(message, key, value)
    db.commit()
    db.refresh(message)
    return message
