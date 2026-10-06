import os
from datetime import datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54401/tunnelconv"
)
engine = create_engine(DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Meter(Base):
    """测缝计台账：校准到期日与最近一次拦截原因的唯一落点。

    报送拦截、测量员改期、续期都在同一短事务内锁本行后读写，
    任何一边的判断都不另存副本。
    """

    __tablename__ = "meters"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_on: Mapped["datetime"] = mapped_column(Date, nullable=False)
    last_block_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_block_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CalibrationEvent(Base):
    """校准续期 / 到期日改动痕迹。"""

    __tablename__ = "calibration_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # renew=续期，expiry_change=测量员手改到期日
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    old_expires_on: Mapped["datetime | None"] = mapped_column(Date, nullable=True)
    new_expires_on: Mapped["datetime"] = mapped_column(Date, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ConvergenceLog(Base):
    __tablename__ = "convergence_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    chainage: Mapped[str] = mapped_column(String, nullable=False)
    delta_mm: Mapped[float] = mapped_column(Float, nullable=False)
    # pending=待认领，done=已判，blocked=校准过期被拦
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def migrate():
    """轻量迁移：旧库补 meters / calibration_events 与新列。"""
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("convergence_logs")}
    if "meter_code" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE convergence_logs ADD COLUMN meter_code VARCHAR(32)"
            )


def meter_dict(row: Meter) -> dict:
    today = datetime.now(timezone.utc).date()
    return {
        "code": row.code,
        "label": row.label,
        "expires_on": row.expires_on.isoformat(),
        "is_expired": row.expires_on < today,
        "last_block_reason": row.last_block_reason,
        "last_block_at": row.last_block_at.isoformat() if row.last_block_at else None,
    }


def event_dict(row: CalibrationEvent) -> dict:
    return {
        "id": row.id,
        "meter_code": row.meter_code,
        "kind": row.kind,
        "old_expires_on": row.old_expires_on.isoformat()
        if row.old_expires_on
        else None,
        "new_expires_on": row.new_expires_on.isoformat(),
        "actor": row.actor,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def row_dict(row: ConvergenceLog) -> dict:
    return {
        "id": row.id,
        "meter_code": row.meter_code,
        "chainage": row.chainage,
        "delta_mm": row.delta_mm,
        "status": row.status,
        "verdict": row.verdict,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }
