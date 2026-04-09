import logging

from fastapi import FastAPI, Request

from core.config import get_settings
from services.yookassa_webhook import process_yookassa_notification

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="OpenClaw Bot Billing")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/yookassa")
    async def yookassa_webhook(request: Request) -> dict[str, bool]:
        settings = get_settings()
        if not settings.yukassa_configured:
            logger.warning("YooKassa webhook called but shop is not configured")
            return {"ok": False}
        try:
            body = await request.json()
        except Exception:
            logger.exception("Invalid JSON in YooKassa webhook")
            return {"ok": False}
        try:
            await process_yookassa_notification(settings, body)
        except Exception:
            logger.exception("YooKassa webhook handler failed")
            return {"ok": False}
        return {"ok": True}

    return app
