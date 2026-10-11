"""Minimal client for an OpenAI-compatible chat endpoint (LM Studio :1234, Ollama :11434/v1)."""
import os

import requests

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5-7b-instruct")


def chat(system: str, user: str, timeout: int = 120) -> str:
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        json={"model": MODEL, "temperature": 0,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def available() -> bool:
    try:
        return requests.get(f"{BASE_URL}/models", timeout=2).ok
    except requests.RequestException:
        return False
