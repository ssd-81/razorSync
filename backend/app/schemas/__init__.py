from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
from datetime import datetime
from pydantic import confloat, conint

AgentType = Literal["autopay_retry", "payment_link_recovery", "invoice_dunning", "x_payout_growth"]  # v3: Razorpay-native agents
ChannelType = Literal["email", "whatsapp", "sms", "push", "in_app"]
RuleType = Literal["frequency_cap", "budget_limit", "cooldown", "channel_priority", "escalation_ceiling", "time_window"]
VerdictType = Literal["approved", "throttled", "blocked", "rerouted", "deferred"]
ArchetypeType = Literal["loyal_regular", "price_sensitive", "low_engagement", "high_value_at_risk", "new_customer"]


class ActionProposeRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    agent_type: AgentType
    customer_id: str = Field(..., min_length=1)
    merchant_id: Optional[str] = None
    action_type: str = Field(..., min_length=1)
    channel: ChannelType
    priority: conint(ge=1, le=10)  # type: ignore
    message_template: Optional[str] = None
    discount_offered: float = Field(default=0.0, ge=0)
    amount_involved: float = Field(default=0.0, ge=0)
    proposed_at: Optional[datetime] = None
    proposed_delay_seconds: int = Field(default=0, ge=0)
    confidence: confloat(ge=0, le=1) = 0.5  # type: ignore
    reasoning: Optional[str] = None

    @field_validator("message_template")
    @classmethod
    def validate_template(cls, v):
        if v and "<script" in v.lower():
            raise ValueError("message_template contains forbidden content")
        return v


class ActionProposeResponse(BaseModel):
    action_id: str
    decision_id: str
    verdict: VerdictType
    block_reason: Optional[str] = None
    approved_channel: Optional[str] = None
    reasoning: Optional[str] = None


class RuleCreateRequest(BaseModel):
    merchant_id: Optional[str] = None
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    applies_to_agents: Optional[List[str]] = None
    applies_to_channels: Optional[List[str]] = None
    rule_type: RuleType
    rule_config: dict
    priority: conint(ge=1, le=10) = 5  # type: ignore
    is_active: bool = True

    @field_validator("rule_config")
    @classmethod
    def validate_config(cls, v, info):
        rt = info.data.get("rule_type")
        if rt == "frequency_cap":
            if "max_contacts" not in v or "window_hours" not in v:
                raise ValueError("frequency_cap requires max_contacts and window_hours")
        elif rt == "cooldown":
            if "cooldown_hours" not in v:
                raise ValueError("cooldown requires cooldown_hours")
        elif rt == "time_window":
            if "start_hour" not in v or "end_hour" not in v:
                raise ValueError("time_window requires start_hour and end_hour")
        elif rt == "budget_limit":
            if "max_discount" not in v:
                raise ValueError("budget_limit requires max_discount")
        elif rt == "escalation_ceiling":
            if "max_escalations" not in v:
                raise ValueError("escalation_ceiling requires max_escalations")
        return v


class RuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    applies_to_agents: Optional[List[str]] = None
    applies_to_channels: Optional[List[str]] = None
    rule_config: Optional[dict] = None
    priority: Optional[conint(ge=1, le=10)] = None  # type: ignore
    is_active: Optional[bool] = None


class SimulationRunRequest(BaseModel):
    num_customers: conint(ge=1, le=2000) = 500  # type: ignore
    seeds: List[conint(ge=0)] = Field(default=[42, 137, 256])  # type: ignore
    duration_days: conint(ge=1, le=30) = 7  # type: ignore
    merchant_id: Optional[str] = None


class OrderCreateRequest(BaseModel):
    amount: conint(ge=100, le=10000000)  # paise, >=1 INR  # type: ignore
    currency: str = Field(default="INR", min_length=3, max_length=3)
    customer_id: str = Field(..., min_length=1)
    receipt: Optional[str] = None
    notes: Optional[dict] = None


class SimulationScorecardRequest(BaseModel):
    num_customers: conint(ge=1, le=2000) = 500  # type: ignore
    seeds: List[conint(ge=0)] = Field(default=[42, 137, 256])  # type: ignore
    duration_days: conint(ge=1, le=30) = 7  # type: ignore
    merchant_id: Optional[str] = None
