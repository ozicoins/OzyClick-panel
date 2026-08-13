import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base
import enum


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    DEAD = "DEAD"
    FROZEN = "FROZEN"


REQUIRED_COOKIES = {
    "NID", "AEC", "SID", "HSID", "SSID", "APISID", "SAPISID",
    "GAPS", "_GRECAPTCHA", "__Secure-1PSID", "__Secure-1PSIDCC",
    "__Secure-3PSID", "__Secure-STRP", "__Secure-1PSIDTS",
}


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    proxy_ip: Mapped[str | None] = mapped_column(String(255))
    profile_index: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    warming_keywords: Mapped[dict | None] = mapped_column(JSON)
    cookie_count: Mapped[int] = mapped_column(Integer, default=14)
    local_storage_status: Mapped[str] = mapped_column(String(20), default="COMPLETE")
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus), default=SessionStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="sessions")
    batch = relationship("Batch", back_populates="sessions")
