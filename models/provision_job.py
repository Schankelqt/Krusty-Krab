from sqlalchemy import BigInteger, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class ProvisionJob(Base, TimestampMixin):
    __tablename__ = "provision_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('create_assistant')",
            name="ck_provision_jobs_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'needs_input', 'failed', 'completed')",
            name="ck_provision_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    assistant_instance_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, default="create_assistant")
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    goal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
