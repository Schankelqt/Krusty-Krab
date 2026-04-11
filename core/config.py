from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _comma_separated_int_ids(raw: str) -> set[int]:
    """ADMIN_IDS / whitelist: «123,456», лишние «=» (часто от ADMIN_IDS==… в .env) игнорируем."""
    out: set[int] = set()
    for piece in (raw or "").replace(";", ",").split(","):
        p = piece.strip().lstrip("=").strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_ids: str = Field(default="", alias="ADMIN_IDS")
    # Один чат для алертов команды (опционально); иначе личные сообщения всем ADMIN_IDS
    admin_team_chat_id: str = Field(default="", alias="ADMIN_TEAM_CHAT_ID")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    # LLM routing
    llm_mode: Literal["auto", "primary", "fallback"] = Field(default="auto", alias="LLM_MODE")
    primary_provider: Literal["openai", "openclaw", "mock"] = Field(default="mock", alias="PRIMARY_PROVIDER")
    fallback_provider: Literal["ollama", "mock", "openclaw"] = Field(default="mock", alias="FALLBACK_PROVIDER")
    trial_provider: Literal["ollama", "mock", "openclaw"] = Field(default="mock", alias="TRIAL_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514", alias="ANTHROPIC_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")

    # OpenClaw Gateway (HTTP OpenResponses: POST /v1/responses, см. docs.openclaw.ai)
    openclaw_url: str = Field(default="", alias="OPENCLAW_URL")
    openclaw_api_key: str = Field(default="", alias="OPENCLAW_API_KEY")
    openclaw_model: str = Field(default="openclaw", alias="OPENCLAW_MODEL")
    openclaw_agent_id: str = Field(default="", alias="OPENCLAW_AGENT_ID")

    # Limits
    daily_msg_limit_basic: int = Field(default=50, alias="DAILY_MSG_LIMIT_BASIC")
    daily_msg_limit_standard: int = Field(default=150, alias="DAILY_MSG_LIMIT_STANDARD")
    daily_msg_limit_pro: int = Field(default=500, alias="DAILY_MSG_LIMIT_PRO")
    paid_token_limit_basic: int = Field(default=1_000_000, alias="PAID_TOKEN_LIMIT_BASIC")
    paid_token_limit_standard: int = Field(default=2_000_000, alias="PAID_TOKEN_LIMIT_STANDARD")
    paid_token_limit_pro: int = Field(default=3_000_000, alias="PAID_TOKEN_LIMIT_PRO")
    trial_duration_hours: int = Field(default=24, alias="TRIAL_DURATION_HOURS")
    trial_message_limit: int = Field(default=50, alias="TRIAL_MESSAGE_LIMIT")
    soft_daily_message_limit: int = Field(default=3, alias="SOFT_DAILY_MESSAGE_LIMIT")
    paid_fallback_daily_message_limit: int = Field(default=300, alias="PAID_FALLBACK_DAILY_MESSAGE_LIMIT")

    # Reply keyboard (можно переименовать под маркетинг)
    btn_trial: str = Field(default="🪄 Познакомиться с OpenClaw", alias="BTN_TRIAL")
    btn_plans: str = Field(default="💳 Тарифы и оплата", alias="BTN_PLANS")

    # Ответ бота: суффикс (provider, model) — для отладки; в проде обычно false
    show_llm_debug_in_reply: bool = Field(default=False, alias="SHOW_LLM_DEBUG_IN_REPLY")

    # Internal testing
    internal_test_mode: bool = Field(default=True, alias="INTERNAL_TEST_MODE")
    internal_whitelist_ids: str = Field(default="", alias="INTERNAL_WHITELIST_IDS")

    # Метрики: события в БД + отчёт в Telegram
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    metrics_report_enabled: bool = Field(default=False, alias="METRICS_REPORT_ENABLED")
    metrics_report_chat_id: str = Field(default="", alias="METRICS_REPORT_CHAT_ID")
    metrics_report_hour_utc: int = Field(default=8, ge=0, le=23, alias="METRICS_REPORT_HOUR_UTC")
    metrics_report_on_start: bool = Field(default=False, alias="METRICS_REPORT_ON_START")
    metrics_internal_token: str = Field(default="", alias="METRICS_INTERNAL_TOKEN")

    # HTTP API (вебхуки ЮKassa)
    billing_http_enabled: bool = Field(default=True, alias="BILLING_HTTP_ENABLED")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8080, alias="API_PORT")

    # ЮKassa (https://yookassa.ru/developers/api)
    yukassa_shop_id: str = Field(default="", alias="YUKASSA_SHOP_ID")
    yukassa_secret_key: str = Field(default="", alias="YUKASSA_SECRET_KEY")
    billing_return_url: str = Field(default="https://t.me/", alias="BILLING_RETURN_URL")
    yukassa_plan: str = Field(default="basic", alias="YUKASSA_PLAN")
    yukassa_currency: str = Field(default="RUB", alias="YUKASSA_CURRENCY")

    # Сетка: линия модели × пакет токенов за период (basic=1M, standard=2M, pro=3M)
    billing_gpt_basic_rub: str = Field(default="1300.00", alias="BILLING_GPT_BASIC_RUB")
    billing_gpt_standard_rub: str = Field(default="2700.00", alias="BILLING_GPT_STANDARD_RUB")
    billing_gpt_pro_rub: str = Field(default="4000.00", alias="BILLING_GPT_PRO_RUB")
    billing_claude_basic_rub: str = Field(default="2000.00", alias="BILLING_CLAUDE_BASIC_RUB")
    billing_claude_standard_rub: str = Field(default="3500.00", alias="BILLING_CLAUDE_STANDARD_RUB")
    billing_claude_pro_rub: str = Field(default="5000.00", alias="BILLING_CLAUDE_PRO_RUB")
    billing_gemini_basic_rub: str = Field(default="500.00", alias="BILLING_GEMINI_BASIC_RUB")
    billing_gemini_standard_rub: str = Field(default="950.00", alias="BILLING_GEMINI_STANDARD_RUB")
    billing_gemini_pro_rub: str = Field(default="1500.00", alias="BILLING_GEMINI_PRO_RUB")

    @property
    def admin_id_set(self) -> set[int]:
        return _comma_separated_int_ids(self.admin_ids)

    @property
    def internal_whitelist_id_set(self) -> set[int]:
        return _comma_separated_int_ids(self.internal_whitelist_ids)

    @property
    def metering_primary_providers(self) -> frozenset[str]:
        """Провайдеры, ответы которых учитываются в лимите токенов платного периода."""
        return frozenset({"openai", "openclaw", "anthropic", "gemini"})

    @property
    def yukassa_configured(self) -> bool:
        return bool(self.yukassa_shop_id.strip() and self.yukassa_secret_key.strip())

    def billing_amount_rub(self, llm_line: str, plan: str) -> str:
        line = llm_line.strip().lower()
        pl = plan.strip().lower()
        if line not in ("gpt", "claude", "gemini"):
            line = "gpt"
        if pl not in ("basic", "standard", "pro"):
            pl = "basic"
        attr = f"billing_{line}_{pl}_rub"
        return str(getattr(self, attr))

    def paid_token_limit_for_plan(self, plan: str | None) -> int:
        """Лимит токенов за оплаченный период по тарифу (basic / standard / pro)."""
        p = (plan or "basic").strip().lower()
        if p == "standard":
            return self.paid_token_limit_standard
        if p == "pro":
            return self.paid_token_limit_pro
        return self.paid_token_limit_basic


@lru_cache
def get_settings() -> Settings:
    return Settings()
