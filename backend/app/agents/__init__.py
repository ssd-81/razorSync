"""Agents config loader - yaml is single source, fallback to hardcoded AGENT_DEFS."""
import os
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

def load_agents_config():
    yaml_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(yaml_path):
        return None, None
    try:
        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        agents = data.get("agents", {})
        webhook_map = data.get("webhook_map", {})
        return agents, webhook_map
    except Exception as e:
        logger.warning("Failed to load agents/config.yaml: %s", e)
        return None, None
