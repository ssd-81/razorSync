"""Agents config API - inspect and configure real agents.

GET /api/v1/agents -> list agents from config.yaml (single source)
POST /api/v1/agents/reload -> reload yaml without restart
"""
import logging
from fastapi import APIRouter, HTTPException
from app.agents import load_agents_config
from app.simulation.agents import AGENT_DEFS, WEBHOOK_AGENT_MAP

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

@router.get("")
def list_agents():
    agents, wmap = load_agents_config()
    if agents:
        return {
            "source": "config.yaml",
            "agents": agents,
            "webhook_map": wmap,
            "count": len(agents),
        }
    return {
        "source": "fallback AGENT_DEFS",
        "agents": AGENT_DEFS,
        "webhook_map": WEBHOOK_AGENT_MAP,
        "count": len(AGENT_DEFS),
    }

@router.get("/{agent_type}")
def get_agent(agent_type: str):
    agents, wmap = load_agents_config()
    src = agents if agents else AGENT_DEFS
    if agent_type not in src:
        raise HTTPException(status_code=404, detail=f"Agent {agent_type} not found")
    # find events this agent handles
    reverse_map = {}
    map_src = wmap if wmap else WEBHOOK_AGENT_MAP
    events = [e for e, lst in map_src.items() if agent_type in lst]
    return {
        "agent_type": agent_type,
        "config": src[agent_type],
        "events": events,
    }

@router.post("/reload")
def reload_agents():
    # Re-load and update in-memory AGENT_DEFS (for simulation)
    agents, wmap = load_agents_config()
    if not agents:
        raise HTTPException(status_code=500, detail="Failed to load config.yaml")
    # Mutate globals so dispatcher picks new config
    from app.simulation import agents as ag_mod
    ag_mod.AGENT_DEFS.clear()
    ag_mod.AGENT_DEFS.update(agents)
    ag_mod.WEBHOOK_AGENT_MAP.clear()
    ag_mod.WEBHOOK_AGENT_MAP.update(wmap)
    return {"status": "reloaded", "agents": list(agents.keys()), "webhook_map": wmap}

@router.get("/llm/status")
def llm_status():
    from app.llm.registry import get_llm_config
    cfg = get_llm_config()
    return cfg

@router.get("/llm/models")
def llm_models():
    import os, yaml
    path = os.path.join(os.path.dirname(__file__), "..", "llm", "models.yaml")
    if not os.path.exists(path):
        return {"providers": {}}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data
