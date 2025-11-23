# backend/app/schemas/chat_response.py

from pydantic import BaseModel
from typing import List, Optional


class SourceItem(BaseModel):
    doc_id: str
    chunk_index: int
    score: Optional[float] = None


class CardItem(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    action: Optional[str] = None  # e.g., "Learn more", "View item"


class ButtonItem(BaseModel):
    label: str
    value: str  # what the button sends back to the bot


class ChatResponse(BaseModel):
    answer: str
    language: str
    sources: List[SourceItem]

    # UI components — optional
    cards: Optional[List[CardItem]] = None
    buttons: Optional[List[ButtonItem]] = None

    class Config:
        orm_mode = True
        arbitrary_types_allowed = True
