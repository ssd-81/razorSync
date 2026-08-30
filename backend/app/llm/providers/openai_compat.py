"""Single OpenAI-compatible adapter - all free clouds speak this."""
import json
import time
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


def chat_complete(
    endpoint: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 5,
    temperature: float = 0.3,
) -> Optional[Dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 256,
    }
    # Some providers need response_format for JSON mode
    if "openrouter" not in endpoint and "huggingface" not in endpoint:
        payload["response_format"] = {"type": "json_object"}

    start = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
        latency = time.time() - start
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            logger.warning("LLM empty content model %s", model)
            return None
        content = content.strip()
        if content.startswith("```"):
            # strip markdown fence
            parts = content.split("\n", 1)
            if len(parts) > 1:
                content = parts[1].rsplit("```", 1)[0].strip()
        result = json.loads(content)
        result["llm_latency_s"] = round(latency, 3)
        result["llm_model"] = model
        return result
    except httpx.TimeoutException:
        logger.warning("LLM timeout %s after %ds", model, timeout)
        return None
    except Exception as e:
        logger.warning("LLM call failed %s: %s", model, e)
        return None
