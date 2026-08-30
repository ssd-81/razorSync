"""LLM Registry - yaml + .env are single source, provider-agnostic."""
import os
import logging
from typing import Optional, Dict

from app.config import settings

logger = logging.getLogger(__name__)


def get_llm_config() -> Dict:
    """Return resolved {endpoint, model, api_key, timeout, provider} or empty if disabled."""
    if not settings.LLM_ENDPOINT or not settings.LLM_MODEL:
        return {"enabled": False}
    # Try to load models.yaml for provider validation (optional)
    provider = settings.LLM_PROVIDER or "custom"
    try:
        import yaml
        yaml_path = os.path.join(os.path.dirname(__file__), "models.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
                providers = data.get("providers", {})
                if provider in providers:
                    logger.info("LLM provider %s model %s endpoint %s", provider, settings.LLM_MODEL, settings.LLM_ENDPOINT)
    except Exception as e:
        logger.warning("models.yaml load failed: %s", e)
    return {
        "enabled": True,
        "provider": provider,
        "endpoint": settings.LLM_ENDPOINT,
        "model": settings.LLM_MODEL,
        "api_key": settings.LLM_API_KEY,
        "timeout": settings.LLM_TIMEOUT,
    }
