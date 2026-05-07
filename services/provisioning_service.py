from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


CREATE_ASSISTANT_STEPS: tuple[str, ...] = (
    "validate_input",
    "create_assistant_instance",
    "configure_defaults",
    "verify_ready",
)


async def create_assistant_job(
    session: AsyncSession,
    owner_user_id: int,
    template_key: str,
    goal_text: str | None,
) -> int:
    """Create a queued provisioning job with deterministic steps."""
    job_row = await session.execute(
        text(
            """
            INSERT INTO provision_jobs (owner_user_id, template_key, goal_text, status, error_message)
            VALUES (:owner_user_id, :template_key, :goal_text, 'queued', NULL)
            RETURNING id
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "template_key": template_key,
            "goal_text": goal_text,
        },
    )
    job_id = int(job_row.scalar_one())

    for step_key in CREATE_ASSISTANT_STEPS:
        await session.execute(
            text(
                """
                INSERT INTO provision_steps (job_id, step_key, status, error_message)
                VALUES (:job_id, :step_key, 'queued', NULL)
                """
            ),
            {"job_id": job_id, "step_key": step_key},
        )

    await session.commit()
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
        return False

    job_id = int(job["id"])
    owner_user_id = int(job["owner_user_id"])
    template_key = str(job["template_key"])
    goal_text = job["goal_text"]

    current_step: str | None = None
    assistant_instance_id: int | None = None

    try:
        for step_key in CREATE_ASSISTANT_STEPS:
            current_step = step_key
            await _set_step_status(session, job_id, step_key, "running")

            if step_key == "validate_input":
                if not template_key.strip():
                    raise ValueError("template_key is required")
                if goal_text is not None and not str(goal_text).strip():
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

        await session.execute(
            text(
                """
                UPDATE provision_jobs
                SET status = 'completed', error_message = NULL
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id},
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()

        if current_step is not None:
            await _set_step_status(session, job_id, current_step, "failed", error_message=str(exc))

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
            {"job_id": job_id, "error_message": str(exc)},
        )
        await session.commit()

    return True


async def get_user_jobs(
    session: AsyncSession,
    owner_user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
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
    return [dict(row) for row in result.mappings().all()]


async def _set_step_status(
    session: AsyncSession,
    job_id: int,
    step_key: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    updated = await session.execute(
        text(
            """
            UPDATE provision_steps
            SET status = :status, error_message = :error_message
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
