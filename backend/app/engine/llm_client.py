"""Legacy shim - delegates to app.llm.client for backward compat."""
from app.llm.client import call_llm  # noqa: F401
from app.config import settings

LLM_ENABLED = settings.llm_enabled
LLM_ENDPOINT = settings.LLM_ENDPOINT
LLM_MODEL = settings.LLM_MODEL
LLM_API_KEY = settings.LLM_API_KEY
LLM_TIMEOUT = settings.LLM_TIMEOUT
