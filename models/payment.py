from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    yookassa_payment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    amount_value: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    plan: Mapped[str] = mapped_column(String(32), default="basic")
    llm_line: Mapped[str | None] = mapped_column(String(16), nullable=True)
