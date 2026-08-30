"""Provider-agnostic LLM client - standard structure for all agents."""
import logging
from typing import Optional, Dict, Any

from app.config import settings
from app.llm.registry import get_llm_config
from app.llm.schemas import AgentProposalSchema

logger = logging.getLogger(__name__)


def build_system_prompt(agent_type: str, merchant_id: str) -> str:
    # Try agents/config.yaml first
    try:
        from app.agents import load_agents_config
        agents, _ = load_agents_config()
        if agents and agent_type in agents:
            prompt = agents[agent_type].get("system_prompt")
            if prompt:
                # ensure strict JSON contract appended
                strict = " Output ONLY valid JSON with keys channel, discount_offered, reasoning, confidence. No explanation, no markdown. Example: {\"channel\":\"whatsapp\",\"discount_offered\":0,\"reasoning\":\"nudge via whatsapp\",\"confidence\":0.7}"
                base = prompt.format(merchant_id=merchant_id, agent_type=agent_type)
                return base + strict
    except Exception:
        pass
    return f"""You are {agent_type} for merchant {merchant_id}.
Goal maximize est_revenue but MUST call check_coordination before send. If BLOCKED propose alternative or suppress. Never bypass.
Output ONLY valid JSON with keys channel, discount_offered, reasoning, confidence. Example: {{"channel":"whatsapp","discount_offered":0,"reasoning":"nudge via whatsapp","confidence":0.7}}"""


def build_user_prompt(event: str, customer_id: str, amount: float, agent_type: str, customer_context: Optional[Dict[str, Any]] = None) -> str:
    ctx = ""
    if customer_context:
        ctx = f"""
Customer: LTV ₹{customer_context.get('lifetime_value',0)} risk {customer_context.get('risk_score',0.5)} contacts {customer_context.get('total_contacts_received',0)} churn_thr {customer_context.get('churn_threshold',5)} archetype {customer_context.get('archetype','unknown')}
"""
    return f"Event: {event}\nAgent: {agent_type}\nAmount: ₹{amount}\nCustomer: {customer_id}{ctx}\nPropose action. Output JSON only."


def call_llm(
    agent_type: str,
    merchant_id: str,
    event: str,
    customer_id: str,
    amount: float,
    customer_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    cfg = get_llm_config()
    if not cfg.get("enabled"):
        return None
    try:
        from app.llm.providers.openai_compat import chat_complete
        system_prompt = build_system_prompt(agent_type, merchant_id)
        user_prompt = build_user_prompt(event, customer_id, amount, agent_type, customer_context)
        raw = chat_complete(
            endpoint=cfg["endpoint"],
            model=cfg["model"],
            api_key=cfg["api_key"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout=cfg["timeout"],
        )
        if not raw:
            return None
        # Validate against standard schema, with lenient mapping for qwen/gpt-oss variants
        try:
            # lenient mapping: action -> channel, discount -> discount_offered, reason -> reasoning
            if "channel" not in raw:
                if "action" in raw:
                    act = str(raw["action"]).lower()
                    for ch in ["whatsapp","sms","email","push","in_app"]:
                        if ch in act:
                            raw["channel"] = ch
                            break
                    else:
                        raw["channel"] = "whatsapp"
                elif "channel" not in raw:
                    raw["channel"] = "whatsapp"
            if "discount_offered" not in raw:
                if "discount" in raw:
                    try:
                        raw["discount_offered"] = float(raw["discount"] or 0)
                    except:
                        raw["discount_offered"] = 0
                else:
                    raw["discount_offered"] = float(raw.get("discount_offered", 0))
            if "reasoning" not in raw and "reason" in raw:
                raw["reasoning"] = str(raw["reason"])
            if "confidence" not in raw:
                raw["confidence"] = float(raw.get("confidence", 0.7))
            validated = AgentProposalSchema.model_validate(raw)
            return {
                "channel": validated.channel,
                "discount_offered": float(validated.discount_offered),
                "reasoning": validated.reasoning,
                "confidence": float(validated.confidence),
                "llm_latency_s": raw.get("llm_latency_s"),
                "llm_model": raw.get("llm_model"),
            }
        except Exception as e:
            logger.warning("LLM schema validation failed for %s: %s raw=%s", agent_type, e, raw)
            return None
    except Exception as e:
        logger.warning("call_llm failed %s: %s", agent_type, e)
        return None
