"""校准到期：报送拦截、改期、续期共用同一把行锁。

铁律：测缝计到期日只存 meters 一张表。报送前在短事务里
SELECT ... FOR UPDATE 锁住该号这一行再判到期，拦截原因也写回
这同一行；续期 / 改到期日同样锁这一行。于是"续期"和"报送"
即便撞在同一瞬间也被串成确定的先后，绝不可能既收下又显示过期。
"""
import threading
from datetime import date, datetime, timedelta, timezone

from models import (
    CalibrationEvent,
    ConvergenceLog,
    Meter,
    SessionLocal,
    event_dict,
    meter_dict,
    row_dict,
)

# 进程内按测缝计号互斥：生产部署为 gunicorn 单 worker 多线程，
# 这把锁是真实互斥；Postgres 的 with_for_update 行锁再兜底跨连接。
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(code: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(code)
        if lk is None:
            lk = threading.Lock()
            _locks[code] = lk
        return lk


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


class MeterNotFound(Exception):
    pass


class MeterExpired(Exception):
    """校准过期：本次报送未被收下（仅留 blocked 痕迹），须先续期。"""

    def __init__(self, reason: str, expires_on: date, log_row: dict, meter: dict):
        super().__init__(reason)
        self.reason = reason
        self.expires_on = expires_on
        self.log_row = log_row
        self.meter = meter


def _lock_meter(db, code: str) -> Meter | None:
    return (
        db.query(Meter)
        .filter(Meter.code == code)
        .with_for_update()
        .first()
    )


def submit_log(*, meter_code: str, chainage: str, delta_mm: float, username: str) -> dict:
    """报送读数。过期则写回最近拦住原因、留 blocked 痕迹并抛 MeterExpired。"""
    code = meter_code.strip()
    with _lock_for(code):
        db = SessionLocal()
        try:
            meter = _lock_meter(db, code)
            if meter is None:
                raise MeterNotFound(code)
            ts = now()
            log = ConvergenceLog(
                meter_code=code,
                chainage=chainage,
                delta_mm=delta_mm,
                created_by=username,
                created_at=ts,
            )
            if meter.expires_on < ts.date():
                reason = (
                    f"测缝计 {code} 校准已于 {meter.expires_on.isoformat()} 到期，"
                    f"{ts.date().isoformat()} 报送被拦，请先办理续期后再开"
                )
                log.status = "blocked"
                log.reason = reason
                meter.last_block_reason = reason
                meter.last_block_at = ts
                db.add(log)
                db.commit()
                db.refresh(log)
                raise MeterExpired(
                    reason, meter.expires_on, row_dict(log), meter_dict(meter)
                )
            log.status = "pending"
            db.add(log)
            db.commit()
            db.refresh(log)
            return row_dict(log)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _change_expiry(
    *, code: str, new_expires_on: date, kind: str, actor: str
) -> tuple[dict, dict]:
    """kind=renew 续期（新日期不得早于今天）或 expiry_change 手改到期日。"""
    with _lock_for(code):
        db = SessionLocal()
        try:
            meter = _lock_meter(db, code)
            if meter is None:
                raise MeterNotFound(code)
            old = meter.expires_on
            meter.expires_on = new_expires_on
            ev = CalibrationEvent(
                meter_code=code,
                kind=kind,
                old_expires_on=old,
                new_expires_on=new_expires_on,
                actor=actor,
                created_at=now(),
            )
            db.add(ev)
            db.commit()
            db.refresh(meter)
            db.refresh(ev)
            return meter_dict(meter), event_dict(ev)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def change_expiry(*, code: str, new_expires_on: date, actor: str) -> tuple[dict, dict]:
    """测量员改到期日（允许改到过去，过期号再报即被拦）。"""
    return _change_expiry(
        code=code, new_expires_on=new_expires_on, kind="expiry_change", actor=actor
    )


def renew(*, code: str, new_expires_on: date | None = None, actor: str) -> tuple[dict, dict]:
    """续期：新到期日必须在今天之后。"""
    ts = now()
    if new_expires_on is None:
        new_expires_on = ts.date() + timedelta(days=365)
    if new_expires_on < ts.date():
        raise ValueError("续期后的到期日不能早于今天")
    return _change_expiry(
        code=code, new_expires_on=new_expires_on, kind="renew", actor=actor
    )


def create_meter(*, code: str, label: str, expires_on: date, actor: str) -> dict:
    code = code.strip()
    db = SessionLocal()
    try:
        ts = now()
        meter = Meter(
            code=code,
            label=label.strip() or code,
            expires_on=expires_on,
            created_at=ts,
        )
        db.add(meter)
        db.add(
            CalibrationEvent(
                meter_code=code,
                kind="register",
                old_expires_on=None,
                new_expires_on=expires_on,
                actor=actor,
                created_at=ts,
            )
        )
        db.commit()
        db.refresh(meter)
        return meter_dict(meter)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
