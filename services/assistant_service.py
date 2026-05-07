from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_user_assistants(
    session: AsyncSession,
    owner_user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if owner_user_id <= 0:
        return []

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
    return [_serialize_assistant_row(dict(row)) for row in result.mappings().all()]


async def get_user_assistant(
    session: AsyncSession,
    owner_user_id: int,
    assistant_instance_id: int,
) -> dict[str, Any] | None:
    if owner_user_id <= 0 or assistant_instance_id <= 0:
        return None

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
    return _serialize_assistant_row(dict(row)) if row is not None else None


def _serialize_assistant_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "owner_user_id": int(row["owner_user_id"]),
        "name": str(row.get("name") or ""),
        "purpose": str(row.get("purpose") or ""),
        "template_key": str(row.get("template_key") or ""),
        "route_mode": str(row.get("route_mode") or "auto"),
        "goal_text": None if row.get("goal_text") is None else str(row.get("goal_text")),
        "status": str(row.get("status") or "draft"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
