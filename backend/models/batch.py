import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base
import enum


class BatchStatus(str, enum.Enum):
    PENDING = "PENDING"
    FARMING = "FARMING"
    COMPLETED = "COMPLETED"
    COMPLETED_PARTIAL = "COMPLETED_PARTIAL"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    total_profiles: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_profiles: Mapped[int] = mapped_column(Integer, default=0)
    failed_profiles: Mapped[int] = mapped_column(Integer, default=0)
    sector: Mapped[str | None] = mapped_column(String(100))
    farming_mode: Mapped[str] = mapped_column(String(10), default="SAFE")
    warming_keywords: Mapped[dict | None] = mapped_column(JSON)
    lifespan_days: Mapped[int] = mapped_column(Integer, default=5)
    proxy_location: Mapped[str] = mapped_column(String(10), default="TR")
    output_directory: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[BatchStatus] = mapped_column(
        SAEnum(BatchStatus), default=BatchStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="batches")
    sessions = relationship("Session", back_populates="batch", lazy="selectin")
