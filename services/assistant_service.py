from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_user_assistants(
    session: AsyncSession,
    owner_user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT
              id,
              owner_user_id,
              name,
              purpose,
              template_key,
              route_mode,
              goal_text,
              status,
              created_at,
              updated_at
            FROM assistant_instances
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


async def get_user_assistant(
    session: AsyncSession,
    owner_user_id: int,
    assistant_instance_id: int,
) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            """
            SELECT
              id,
              owner_user_id,
              name,
              purpose,
              template_key,
              route_mode,
              goal_text,
              status,
              created_at,
              updated_at
            FROM assistant_instances
            WHERE id = :assistant_instance_id AND owner_user_id = :owner_user_id
            """
        ),
        {
            "assistant_instance_id": assistant_instance_id,
            "owner_user_id": owner_user_id,
        },
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None
