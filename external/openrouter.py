import httpx

from utils import get_env_var


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"

def make_request_openrouter(payload: dict) -> dict:

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}",
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(f"{OPENROUTER_ENDPOINT}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
