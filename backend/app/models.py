"""Canonical Pydantic models shared across adapters, API, and exporter."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Provider = Literal["chatgpt", "claude", "gemini"]
Role = Literal["user", "assistant", "system", "tool"]


class Message(BaseModel):
    id: str
    conversation_id: str
    parent_id: str | None = None
    role: Role
    content: str
    created_at: float | None = None
    tokens: int | None = None
    model: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class Conversation(BaseModel):
    id: str
    provider: Provider
    external_id: str | None = None
    title: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    model: str | None = None
    raw_ref: str | None = None
    messages: list[Message] = Field(default_factory=list)


class IngestResult(BaseModel):
    provider: Provider
    source: str
    conversations: int
    messages: int
    errors: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    message_id: str
    conversation_id: str
    conversation_title: str | None
    role: Role
    snippet: str
    created_at: float | None
    score: float
    provider: Provider


class TopicInfo(BaseModel):
    id: int
    label: str
    keywords: list[str]
    conversation_count: int = 0
    message_count: int = 0


class ProgressionPoint(BaseModel):
    bucket: str  # e.g. "2024-03"
    avg_user_len: float
    type_token_ratio: float
    followups_per_conv: float
    topic_term_freq: float
    score: float
    sample_count: int
