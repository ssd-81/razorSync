"""Standard LLM contract - single Pydantic schema for all providers."""
from pydantic import BaseModel, Field
from typing import Literal

class AgentProposalSchema(BaseModel):
    channel: Literal["whatsapp", "sms", "email", "push", "in_app"]
    discount_offered: float = Field(default=0.0, ge=0)
    reasoning: str = Field(default="", max_length=300)
    confidence: float = Field(default=0.7, ge=0, le=1)
