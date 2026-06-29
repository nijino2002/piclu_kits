from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    phase: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    dependency_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    worker_id: Mapped[str | None] = mapped_column(String(255), index=True)
    task_package_path: Mapped[str] = mapped_column(String(255), nullable=False)
    result_package_path: Mapped[str | None] = mapped_column(String(255))
    use_docker: Mapped[bool | None] = mapped_column(Boolean)
    error_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_tasks_status_submitted", "status", "submitted_at"),
        Index("idx_tasks_dependency", "dependency_id"),
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="events")

    __table_args__ = (Index("idx_task_events_task_time", "task_id", "created_at"),)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="online")
    current_task_id: Mapped[str | None] = mapped_column(String(32), index=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
