# project/api/chat.py

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import List, Optional
import datetime

router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)

# --- Models ---

class ChatMessage(BaseModel):
    id: int
    sender: str
    message: str
    timestamp: datetime.datetime

class CreateMessage(BaseModel):
    sender: str
    message: str


# --- In-memory chat store (for demo only) ---
chat_messages: List[ChatMessage] = []


# --- Routes ---

@router.get("/", response_model=List[ChatMessage])
async def get_all_messages():
    """Get all chat messages"""
    return chat_messages


@router.post("/", response_model=ChatMessage, status_code=status.HTTP_201_CREATED)
async def send_message(payload: CreateMessage):
    """Send a new chat message"""
    new_message = ChatMessage(
        id=len(chat_messages) + 1,
        sender=payload.sender,
        message=payload.message,
        timestamp=datetime.datetime.utcnow()
    )
    chat_messages.append(new_message)
    return new_message


@router.get("/{message_id}", response_model=ChatMessage)
async def get_message(message_id: int):
    """Get a single chat message by ID"""
    for msg in chat_messages:
        if msg.id == message_id:
            return msg
    raise HTTPException(status_code=404, detail="Message not found")


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(message_id: int):
    """Delete a message by ID"""
    global chat_messages
    chat_messages = [m for m in chat_messages if m.id != message_id]
    return None
