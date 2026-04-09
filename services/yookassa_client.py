import base64
import uuid
from typing import Any

import httpx

from core.config import Settings

YOOKASSA_API = "https://api.yookassa.ru/v3"


def _basic_auth(settings: Settings) -> str:
    raw = f"{settings.yukassa_shop_id}:{settings.yukassa_secret_key}".encode()
    return base64.b64encode(raw).decode()


async def create_payment(
    settings: Settings,
    *,
    amount_value: str,
    currency: str,
    return_url: str,
    description: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    payload = {
        "amount": {"value": amount_value, "currency": currency},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True,
        "description": description,
        "metadata": metadata,
    }
    headers = {
        "Authorization": f"Basic {_basic_auth(settings)}",
        "Content-Type": "application/json",
        "Idempotence-Key": str(uuid.uuid4()),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{YOOKASSA_API}/payments", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


async def get_payment(settings: Settings, payment_id: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Basic {_basic_auth(settings)}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{YOOKASSA_API}/payments/{payment_id}", headers=headers)
        r.raise_for_status()
        return r.json()
