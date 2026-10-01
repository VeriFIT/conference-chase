"""Client for any OpenAI-compatible Chat Completions endpoint.

Configured via environment:
  LLM_API_KEY   API key (GitHub secret)
  LLM_BASE_URL  endpoint base URL, e.g. https://openrouter.ai/api/v1 (optional)
  LLM_MODEL     model name
"""
from __future__ import annotations

import os

from openai import OpenAI


def make_client() -> tuple[OpenAI, str]:
    key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")
    if not key or not model:
        raise SystemExit("LLM_API_KEY and LLM_MODEL must be set")
    client = OpenAI(api_key=key, base_url=os.environ.get("LLM_BASE_URL") or None, max_retries=3, timeout=120)
    return client, model
