"""Chat calls to the local Ollama server that answer in JSON."""

import json
import re
from typing import Any

import httpx

from app.settings import settings


async def chat_json(model: str, system: str | None, user: str, options: dict[str, Any]) -> str:
    """One chat call in JSON mode; the model's reply, as text."""
    messages = [{"role": "user", "content": user}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": options,
    }
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url, timeout=settings.ollama_request_timeout
    ) as client:
        response = await client.post("/api/chat", json=body)
        response.raise_for_status()
        return response.json()["message"]["content"]


def parse_json_object(raw: str) -> dict | None:
    """The reply as a JSON object, or None. Models sometimes wrap it in a code fence."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
