"""
test_llm.py — Phase 2 Handshake: DeepSeek API Connection Test

Run: python tools/test_llm.py
Expected output: DeepSeek connected. Model: deepseek-v4-pro | Response received.
"""

import sys
import os
import json
import requests
from pathlib import Path

# Fix Windows CP1252 encoding for Unicode output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


# Load .env from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    print("❌ python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def test_connection() -> bool:
    if not API_KEY or API_KEY == "your_api_key_here":
        print("❌ DEEPSEEK_API_KEY is not set in .env")
        print("   → Copy .env.example to .env and add your API key.")
        return False

    # Simple ping — use enough tokens for reasoning models that spend
    # tokens on reasoning_content before producing the visible content.
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Reply with only the word: ok"}
        ],
        "temperature": 0,
        "max_tokens": 200
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        print(f"   → Connecting to {BASE_URL}/chat/completions ...")
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )

        if not response.ok:
            print(f"❌ HTTP {response.status_code}: {response.text[:300]}")
            return False

        data = response.json()
        message = data["choices"][0]["message"]
        content = (message.get("content") or "").strip()

        # Reasoning models (deepseek-v4-pro) may return content in reasoning_content
        if not content:
            reasoning = message.get("reasoning_content") or ""
            # Extract the last meaningful line from reasoning
            content = reasoning.strip()

        if content:
            print(f"✅ DeepSeek connected. Model: {MODEL} | Response: '{content}'")
            return True
        else:
            print(f"⚠️  Empty response from API. Raw: {data}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed — check your internet connection.")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP error: {e.response.status_code} — {e.response.text[:300]}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Phase 2 — DeepSeek API Handshake Test")
    print("=" * 50)
    success = test_connection()
    sys.exit(0 if success else 1)
