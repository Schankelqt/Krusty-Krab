from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal
from services.metrics_service import record_event


logger = logging.getLogger(__name__)


CREATE_ASSISTANT_STEPS: tuple[str, ...] = (
    "validate_input",
    "create_assistant_instance",
    "configure_defaults",
    "verify_ready",
)


_JOB_STATUSES_IN_PROGRESS: tuple[str, ...] = ("queued", "running", "needs_input")
_STEP_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("queued", "running", "failed", "skipped"),
    "running": ("running", "completed", "failed", "skipped"),
    "failed": ("failed",),
    "completed": ("completed",),
    "skipped": ("skipped",),
}
_GENERIC_FAILURE_MESSAGE = "Internal provisioning error"
_SENSITIVE_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
)


def _safe_error_message(exc: Exception) -> str:
    raw = str(exc or "").strip()
    if not raw:
        return _GENERIC_FAILURE_MESSAGE
    redacted = raw
    for pattern in _SENSITIVE_ERROR_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    redacted = redacted[:200]
    return redacted or _GENERIC_FAILURE_MESSAGE


async def create_assistant_job(
    session: AsyncSession,
    owner_user_id: int,
    template_key: str,
    goal_text: str | None,
) -> int:
    """Create a queued provisioning job with deterministic steps."""
    if owner_user_id <= 0:
        raise ValueError("owner_user_id must be positive")

    normalized_template_key = str(template_key).strip()
    normalized_goal_text = None if goal_text is None else str(goal_text).strip()

    if not normalized_template_key:
        raise ValueError("template_key is required")
    if normalized_goal_text == "":
        raise ValueError("goal_text cannot be blank when provided")

    # Idempotency guard for user-level retries: reuse active jobs with same intent.
    existing = await session.execute(
        text(
            """
            SELECT id
            FROM provision_jobs
            WHERE owner_user_id = :owner_user_id
              AND template_key = :template_key
              AND COALESCE(goal_text, '') = COALESCE(:goal_text, '')
              AND status = ANY(:statuses)
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "template_key": normalized_template_key,
            "goal_text": normalized_goal_text,
            "statuses": list(_JOB_STATUSES_IN_PROGRESS),
        },
    )
    existing_job_id = existing.scalar_one_or_none()
    if existing_job_id is not None:
        await _ensure_job_steps(session, int(existing_job_id))
        await session.commit()
        logger.info(
            "provision_job reused job_id=%s owner_user_id=%s template=%s",
            int(existing_job_id),
            owner_user_id,
            normalized_template_key,
        )
        return int(existing_job_id)

    job_row = await session.execute(
        text(
            """
            INSERT INTO provision_jobs (
                owner_user_id,
                job_type,
                template_key,
                goal_text,
                status,
                error_message
            )
            VALUES (
                :owner_user_id,
                'create_assistant',
                :template_key,
                :goal_text,
                'queued',
                NULL
            )
            RETURNING id
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "template_key": normalized_template_key,
            "goal_text": normalized_goal_text,
        },
    )
    job_id = int(job_row.scalar_one())

    await _ensure_job_steps(session, job_id)

    await session.commit()

    logger.info(
        "provision_job queued job_id=%s owner_user_id=%s template=%s",
        job_id,
        owner_user_id,
        normalized_template_key,
    )
    await record_event(
        "provision_job_queued",
        user_id=owner_user_id,
        payload={
            "job_id": job_id,
            "template_key": normalized_template_key,
            "steps": list(CREATE_ASSISTANT_STEPS),
        },
    )

    return job_id


async def run_next_job(session: AsyncSession) -> bool:
    """
    Pull one queued provisioning job and execute it synchronously.
    Returns False when queue is empty, True when a job was picked.
    """
    picked = await session.execute(
        text(
            """
            WITH next_job AS (
                SELECT id, owner_user_id, template_key, goal_text
                FROM provision_jobs
                WHERE status = 'queued'
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE provision_jobs pj
            SET status = 'running', error_message = NULL
            FROM next_job
            WHERE pj.id = next_job.id
            RETURNING next_job.id, next_job.owner_user_id, next_job.template_key, next_job.goal_text
            """
        )
    )
    job = picked.mappings().first()
    if not job:
        await session.rollback()
        logger.debug("provision_worker idle reason=queue_empty")
        return False
    return await _execute_picked_job(session, dict(job))


async def _execute_picked_job(session: AsyncSession, job: dict[str, Any]) -> bool:
    job_id = int(job["id"])
    owner_user_id = int(job["owner_user_id"])
    template_key = str(job["template_key"] or "").strip()
    goal_text = None if job["goal_text"] is None else str(job["goal_text"]).strip()

    current_step: str | None = None
    assistant_instance_id: int | None = None
    started_monotonic = time.monotonic()

    logger.info(
        "provision_worker picked job_id=%s owner_user_id=%s template=%s",
        job_id,
        owner_user_id,
        template_key,
    )
    await record_event(
        "provision_job_running",
        user_id=owner_user_id,
        payload={"job_id": job_id, "template_key": template_key},
    )

    try:
        for step_key in CREATE_ASSISTANT_STEPS:
            current_step = step_key
            await _set_step_status(session, job_id, step_key, "running")
            logger.info(
                "provision_step running job_id=%s step=%s",
                job_id,
                step_key,
            )

            if step_key == "validate_input":
                if not template_key:
                    raise ValueError("template_key is required")
                if goal_text == "":
                    raise ValueError("goal_text cannot be blank when provided")

            elif step_key == "create_assistant_instance":
                template_title = {
                    "content": "Контент-ассистент",
                    "sales": "Sales-ассистент",
                    "support": "Support-ассистент",
                    "custom": "Кастомный ассистент",
                }.get(template_key, "Ассистент")
                purpose_text = (goal_text or f"Шаблон {template_key}").strip()[:512]
                created = await session.execute(
                    text(
                        """
                        INSERT INTO assistant_instances (
                            owner_user_id,
                            name,
                            purpose,
                            goal_text,
                            template_key,
                            route_mode,
                            status
                        )
                        VALUES (
                            :owner_user_id,
                            :name,
                            :purpose,
                            :goal_text,
                            :template_key,
                            'auto',
                            'provisioning'
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "owner_user_id": owner_user_id,
                        "name": template_title,
                        "purpose": purpose_text,
                        "template_key": template_key,
                        "goal_text": goal_text,
                    },
                )
                assistant_instance_id = int(created.scalar_one())
                await session.execute(
                    text(
                        """
                        UPDATE provision_jobs
                        SET assistant_instance_id = :assistant_instance_id
                        WHERE id = :job_id
                        """
                    ),
                    {"assistant_instance_id": assistant_instance_id, "job_id": job_id},
                )

            elif step_key == "configure_defaults":
                if assistant_instance_id is None:
                    raise RuntimeError("assistant instance was not created")
                # TODO: Apply OpenClaw defaults/config templates in external integration stage.

            elif step_key == "verify_ready":
                if assistant_instance_id is None:
                    raise RuntimeError("assistant instance was not created")
                verify = await session.execute(
                    text(
                        """
                        SELECT id
                        FROM assistant_instances
                        WHERE id = :assistant_instance_id
                          AND owner_user_id = :owner_user_id
                        """
                    ),
                    {
                        "assistant_instance_id": assistant_instance_id,
                        "owner_user_id": owner_user_id,
                    },
                )
                if verify.scalar_one_or_none() is None:
                    raise RuntimeError("assistant instance not found for verification")

                await session.execute(
                    text(
                        """
                        UPDATE assistant_instances
                        SET status = 'ready'
                        WHERE id = :assistant_instance_id
                        """
                    ),
                    {"assistant_instance_id": assistant_instance_id},
                )
                # TODO: Perform real readiness check once external runtime exists.

            await _set_step_status(session, job_id, step_key, "completed")
            logger.info(
                "provision_step completed job_id=%s step=%s",
                job_id,
                step_key,
            )

        updated = await session.execute(
            text(
                """
                UPDATE provision_jobs
                SET status = 'completed', error_message = NULL
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id},
        )
        if updated.rowcount != 1:
            raise RuntimeError("job status update failed")
        await session.commit()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        logger.info(
            "provision_job completed job_id=%s owner_user_id=%s template=%s duration_ms=%s",
            job_id,
            owner_user_id,
            template_key,
            duration_ms,
        )
        await record_event(
            "provision_job_completed",
            user_id=owner_user_id,
            payload={
                "job_id": job_id,
                "template_key": template_key,
                "duration_ms": duration_ms,
                "assistant_instance_id": assistant_instance_id,
            },
        )
    except Exception as exc:
        await session.rollback()
        safe_error = _safe_error_message(exc)

        if current_step is not None:
            await _set_step_status(session, job_id, current_step, "failed", error_message=safe_error)
            logger.warning(
                "provision_step failed job_id=%s step=%s error=%s",
                job_id,
                current_step,
                safe_error,
            )

        if assistant_instance_id is not None:
            await session.execute(
                text(
                    """
                    UPDATE assistant_instances
                    SET status = 'failed'
                    WHERE id = :assistant_instance_id
                    """
                ),
                {"assistant_instance_id": assistant_instance_id},
            )

        await session.execute(
            text(
                """
                UPDATE provision_jobs
                SET status = 'failed', error_message = :error_message
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "error_message": safe_error},
        )
        await session.commit()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        logger.exception(
            "provision_job failed job_id=%s owner_user_id=%s template=%s step=%s duration_ms=%s error=%s",
            job_id,
            owner_user_id,
            template_key,
            current_step,
            duration_ms,
            safe_error,
        )
        await record_event(
            "provision_job_failed",
            user_id=owner_user_id,
            payload={
                "job_id": job_id,
                "template_key": template_key,
                "step": current_step,
                "duration_ms": duration_ms,
                "error": safe_error,
            },
        )

    return True


async def has_active_jobs_for_user(session: AsyncSession, owner_user_id: int) -> bool:
    result = await session.execute(
        text(
            """
            SELECT 1
            FROM provision_jobs
            WHERE owner_user_id = :owner_user_id
              AND status = ANY(:statuses)
            LIMIT 1
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "statuses": list(_JOB_STATUSES_IN_PROGRESS),
        },
    )
    return result.scalar_one_or_none() is not None


async def run_user_job(session: AsyncSession, owner_user_id: int, job_id: int) -> bool:
    picked = await session.execute(
        text(
            """
            WITH selected AS (
                SELECT id, owner_user_id, template_key, goal_text
                FROM provision_jobs
                WHERE id = :job_id
                  AND owner_user_id = :owner_user_id
                  AND status = 'queued'
                FOR UPDATE SKIP LOCKED
            )
            UPDATE provision_jobs pj
            SET status = 'running', error_message = NULL
            FROM selected
            WHERE pj.id = selected.id
            RETURNING selected.id, selected.owner_user_id, selected.template_key, selected.goal_text
            """
        ),
        {"job_id": job_id, "owner_user_id": owner_user_id},
    )
    job = picked.mappings().first()
    if not job:
        await session.rollback()
        logger.debug(
            "provision_worker idle reason=user_job_not_picked job_id=%s owner_user_id=%s",
            job_id,
            owner_user_id,
        )
        return False
    return await _execute_picked_job(session, dict(job))


async def get_user_jobs(
    session: AsyncSession,
    owner_user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if owner_user_id <= 0:
        return []

    result = await session.execute(
        text(
            """
            SELECT id, owner_user_id, template_key, goal_text, status, error_message, created_at, updated_at
            FROM provision_jobs
            WHERE owner_user_id = :owner_user_id
            ORDER BY id DESC
            LIMIT :limit
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "limit": max(1, min(limit, 100)),
        },
    )
    return [_serialize_job_row(dict(row)) for row in result.mappings().all()]


async def _set_step_status(
    session: AsyncSession,
    job_id: int,
    step_key: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    existing = await session.execute(
        text(
            """
            SELECT status
            FROM provision_steps
            WHERE job_id = :job_id AND step_key = :step_key
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"job_id": job_id, "step_key": step_key},
    )
    previous_status = existing.scalar_one_or_none()
    if previous_status is not None and not _is_valid_step_transition(
        str(previous_status), status
    ):
        raise RuntimeError(
            f"invalid step transition for {step_key}: {previous_status} -> {status}"
        )

    updated = await session.execute(
        text(
            """
            UPDATE provision_steps
            SET status = :status,
                error_message = :error_message,
                started_at = CASE
                    WHEN :status = 'running' AND started_at IS NULL THEN NOW()
                    ELSE started_at
                END,
                finished_at = CASE
                    WHEN :status IN ('completed', 'failed', 'skipped') THEN NOW()
                    WHEN :status = 'running' THEN NULL
                    ELSE finished_at
                END
            WHERE job_id = :job_id AND step_key = :step_key
            """
        ),
        {
            "status": status,
            "error_message": error_message,
            "job_id": job_id,
            "step_key": step_key,
        },
    )

    if updated.rowcount == 0:
        await session.execute(
            text(
                """
                INSERT INTO provision_steps (job_id, step_key, status, error_message)
                VALUES (:job_id, :step_key, :status, :error_message)
                """
            ),
            {
                "job_id": job_id,
                "step_key": step_key,
                "status": status,
                "error_message": error_message,
            },
        )


async def _ensure_job_steps(session: AsyncSession, job_id: int) -> None:
    for step_key in CREATE_ASSISTANT_STEPS:
        await session.execute(
            text(
                """
                INSERT INTO provision_steps (job_id, step_key, status, error_message)
                SELECT :job_id, :step_key, 'queued', NULL
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM provision_steps
                    WHERE job_id = :job_id AND step_key = :step_key
                )
                """
            ),
            {"job_id": job_id, "step_key": step_key},
        )


def _is_valid_step_transition(previous: str, next_status: str) -> bool:
    allowed = _STEP_ALLOWED_TRANSITIONS.get(previous)
    if allowed is None:
        return next_status in {"queued", "running", "failed", "completed", "skipped"}
    return next_status in allowed


def _serialize_job_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "owner_user_id": int(row["owner_user_id"]),
        "template_key": str(row.get("template_key") or ""),
        "goal_text": None if row.get("goal_text") is None else str(row.get("goal_text")),
        "status": str(row.get("status") or "queued"),
        "error_message": None
        if row.get("error_message") is None
        else str(row.get("error_message")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# Per-user re-entrancy guard for provisioning callbacks (in-process only; the
# bot is single-process today). Prevents duplicate job creation on rapid
# double-presses of the same confirm/apply button. The background worker loop
# in bot/main.py handles persistent at-most-once execution via FOR UPDATE
# SKIP LOCKED, so this guard is a UX-layer protection only.
_USER_LOCKS: dict[int, asyncio.Lock] = {}
_USER_LOCKS_GUARD = asyncio.Lock()


class _UserProvisionLock:
    """Async context manager for an opportunistic per-user provision lock.

    Resolves to ``True`` when the lock was acquired and ``False`` when another
    in-flight operation already holds it. The body should bail out quickly when
    ``False`` to avoid duplicate work.
    """

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id
        self._lock: asyncio.Lock | None = None

    async def __aenter__(self) -> bool:
        async with _USER_LOCKS_GUARD:
            lock = _USER_LOCKS.setdefault(self._user_id, asyncio.Lock())
            if lock.locked():
                return False
            await lock.acquire()
            self._lock = lock
            return True

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._lock is not None:
            try:
                self._lock.release()
            finally:
                self._lock = None


def acquire_user_provision_lock(user_id: int) -> _UserProvisionLock:
    """Best-effort per-user lock to deduplicate concurrent provisioning callbacks."""
    return _UserProvisionLock(user_id)


def schedule_run_next_job() -> asyncio.Task[None]:
    """Fire-and-forget background dispatch of the next queued provisioning job.

    Used by callback handlers to nudge the worker without blocking on the
    multi-step DB pipeline. The persistent worker loop still drains the queue
    on a fixed interval, so missed schedules are not fatal.
    """
    return asyncio.create_task(_run_next_job_safely(), name="provisioning_run_next_job_oneshot")


async def _run_next_job_safely() -> None:
    try:
        async with SessionLocal() as session:
            await run_next_job(session)
    except Exception:
        logger.exception("oneshot run_next_job failed in background task")
