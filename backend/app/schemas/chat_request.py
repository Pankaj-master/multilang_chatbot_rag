# backend/app/schemas/chat_request.py

from pydantic import BaseModel
from typing import List, Optional


class HistoryMessage(BaseModel):
    role: str              # "user" or "assistant"
    content: str           # text content of message


class ChatRequest(BaseModel):
    """
    Incoming chat request from frontend → backend.
    Matches the fields used in routes/chat.py
    """
    message: str
    history: Optional[List[HistoryMessage]] = None
    language: Optional[str] = None
    top_k: int = 5         # number of retrieved chunks (RAG)

    class Config:
        orm_mode = True
        arbitrary_types_allowed = True
