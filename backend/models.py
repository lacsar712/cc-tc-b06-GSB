import os
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54401/tunnelconv")
engine = create_engine(DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class JointMeter(Base):
    """测缝计：编号 + 校准有效期至。报送拦截口与到期专页共同的唯一事实源。"""

    __tablename__ = "joint_meters"

    meter_no: Mapped[str] = mapped_column(String, primary_key=True)
    calibrated_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeterRenewal(Base):
    """改期/续期痕迹：每次测量员修改到期日都落一行。"""

    __tablename__ = "meter_renewals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_no: Mapped[str] = mapped_column(
        String, ForeignKey("joint_meters.meter_no"), nullable=False, index=True
    )
    old_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    new_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[str] = mapped_column(String, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeterBlock(Base):
    """报送拦截痕迹：校准过期被拦下时落一行，供到期专页展示最近原因。"""

    __tablename__ = "meter_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_no: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chainage: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_by: Mapped[str] = mapped_column(String, nullable=False)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConvergenceLog(Base):
    __tablename__ = "convergence_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_no: Mapped[str | None] = mapped_column(String, nullable=True)
    chainage: Mapped[str] = mapped_column(String, nullable=False)
    delta_mm: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def ensure_schema():
    """建表并给旧库的 convergence_logs 补 meter_no 列（幂等）。"""
    Base.metadata.create_all(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("convergence_logs")}
    if "meter_no" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE convergence_logs ADD COLUMN meter_no VARCHAR"))


def _iso(value):
    return value.isoformat() if value else None


def meter_dict(meter: JointMeter, latest_block=None, latest_renewal=None) -> dict:
    return {
        "meter_no": meter.meter_no,
        "calibrated_until": _iso(meter.calibrated_until),
        "latest_block": None
        if latest_block is None
        else {
            "reason": latest_block.reason,
            "chainage": latest_block.chainage,
            "blocked_by": latest_block.blocked_by,
            "blocked_at": _iso(latest_block.blocked_at),
        },
        "latest_renewal": None
        if latest_renewal is None
        else {
            "old_until": _iso(latest_renewal.old_until),
            "new_until": _iso(latest_renewal.new_until),
            "changed_by": latest_renewal.changed_by,
            "changed_at": _iso(latest_renewal.changed_at),
        },
    }


def renewal_dict(row: MeterRenewal) -> dict:
    return {
        "id": row.id,
        "meter_no": row.meter_no,
        "old_until": _iso(row.old_until),
        "new_until": _iso(row.new_until),
        "changed_by": row.changed_by,
        "changed_at": _iso(row.changed_at),
    }


def row_dict(row: ConvergenceLog) -> dict:
    return {
        "id": row.id,
        "meter_no": row.meter_no,
        "chainage": row.chainage,
        "delta_mm": row.delta_mm,
        "status": row.status,
        "verdict": row.verdict,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "processed_at": _iso(row.processed_at),
    }
