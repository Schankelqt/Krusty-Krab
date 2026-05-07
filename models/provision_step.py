from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ProvisionStep(Base):
    __tablename__ = "provision_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'failed', 'completed', 'skipped')",
            name="ck_provision_steps_status",
        ),
        Index("ix_provision_steps_job_id_step_key", "job_id", "step_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    details: Mapped[dict | str | None] = mapped_column(
        JSONB().with_variant(Text, "sqlite"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
