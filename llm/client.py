"""
Multi-provider client for OpenAI-compatible chat endpoints:
- Local LM Studio (http://localhost:1234/v1)
- Local Ollama (http://localhost:11434/v1)
- Remote endpoints (OpenAI, Gemini, Groq) via LLM_BASE_URL and LLM_API_KEY
"""

import os
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5-7b-instruct")
API_KEY = os.environ.get("LLM_API_KEY", "")


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return headers


def chat(system: str, user: str, timeout: int = 120, temperature: float = 0.0) -> str:
    """Send chat request to configured OpenAI-compatible endpoint."""
    url = f"{BASE_URL}/chat/completions"
    payload = {
        "model": MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(url, json=payload, headers=get_headers(), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def available(timeout: float = 2.0) -> bool:
    """Check if the configured LLM endpoint is reachable and responsive."""
    try:
        url = f"{BASE_URL}/models"
        resp = requests.get(url, headers=get_headers(), timeout=timeout)
        return resp.ok
    except requests.RequestException:
        return False
