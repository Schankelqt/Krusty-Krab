import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, Request

from core.config import get_settings
from core.database import SessionLocal
from services.metrics_aggregate import load_summary, summary_to_json_dict
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

    @app.get("/internal/metrics/summary")
    async def internal_metrics_summary(authorization: str | None = Header(None)) -> dict:
        """Сводка за 24 ч UTC; только с заголовком Authorization: Bearer &lt;METRICS_INTERNAL_TOKEN&gt;."""
        settings = get_settings()
        token = settings.metrics_internal_token.strip()
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(status_code=404)
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=1)
        async with SessionLocal() as session:
            m = await load_summary(session, since, now)
        return summary_to_json_dict(m)

    return app
