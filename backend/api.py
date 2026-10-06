import os
from datetime import datetime, time, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import text

from claimer import start as start_claimer
from models import (
    ConvergenceLog,
    JointMeter,
    MeterBlock,
    MeterRenewal,
    SessionLocal,
    ensure_schema,
    meter_dict,
    renewal_dict,
    row_dict,
)

SECRET = os.environ.get("JWT_SECRET", "tunnelconv-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

app = Flask(__name__)


def parse_calibrated_until(raw: str) -> datetime | None:
    """'2026-10-06' 视为当日有效（至 23:59:59 UTC）；带时间的 ISO 串缺时区按 UTC。"""
    if not raw or not str(raw).strip():
        return None
    text_value = str(raw).strip()
    try:
        if len(text_value) == 10:
            day = datetime.strptime(text_value, "%Y-%m-%d")
            return datetime.combine(day.date(), time(23, 59, 59), tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def expire_reason(meter_no: str, until: datetime) -> str:
    return (
        f"测缝计 {meter_no} 的校准已于 {until.strftime('%Y-%m-%d')} 到期，"
        "该铭牌不许再报送，请先办理续期后再开报"
    )


def seed():
    ensure_schema()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        if db.query(JointMeter).count() == 0:
            valid_until = now + timedelta(days=365)
            expired_until = now - timedelta(days=1)
            db.add(JointMeter(meter_no="甲", calibrated_until=valid_until))
            db.add(JointMeter(meter_no="乙", calibrated_until=expired_until))
            db.add(
                MeterBlock(
                    meter_no="乙",
                    chainage="K18+040",
                    reason=expire_reason("乙", expired_until),
                    blocked_by="surveyor",
                    blocked_at=now - timedelta(hours=2),
                )
            )
        if db.query(ConvergenceLog).count() == 0:
            from rules import judge

            for meter_no, chainage, delta, expect in (
                ("甲", "K12+180", 1.2, "合格"),
                ("乙", "K18+040", 5.6, "超限"),
            ):
                verdict, reason = judge(delta)
                assert verdict == expect
                db.add(
                    ConvergenceLog(
                        meter_no=meter_no,
                        chainage=chainage,
                        delta_mm=delta,
                        status="done",
                        verdict=verdict,
                        reason=reason,
                        created_by="surveyor",
                        created_at=now,
                        processed_at=now,
                    )
                )
        db.commit()
    finally:
        db.close()


seed()
start_claimer()


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth[7:].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def require_writer(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        if user["role"] != "writer":
            return jsonify({"detail": "巡检员只读，不能办理此类操作"}), 403
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "tunnel-convergence-desk"})


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        return jsonify({"detail": "用户名或密码错误"}), 401
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return jsonify({"access_token": token, "username": username, "role": user["role"]})


@app.get("/api/meters")
@require_login
def list_meters():
    """到期专页数据：各号到期日 + 最近一次拦住原因 + 续期痕迹。"""
    db = SessionLocal()
    try:
        meters = db.query(JointMeter).order_by(JointMeter.meter_no).all()
        latest_blocks = {
            b.meter_no: b
            for b in (
                db.query(MeterBlock)
                .distinct(MeterBlock.meter_no)
                .order_by(MeterBlock.meter_no, MeterBlock.id.desc())
                .all()
            )
        }
        latest_renewals = {
            r.meter_no: r
            for r in (
                db.query(MeterRenewal)
                .distinct(MeterRenewal.meter_no)
                .order_by(MeterRenewal.meter_no, MeterRenewal.id.desc())
                .all()
            )
        }
        renewals = {}
        for r in db.query(MeterRenewal).order_by(MeterRenewal.id.desc()).all():
            renewals.setdefault(r.meter_no, []).append(renewal_dict(r))
        now = datetime.now(timezone.utc)
        result = []
        for m in meters:
            item = meter_dict(m, latest_blocks.get(m.meter_no), latest_renewals.get(m.meter_no))
            item["expired"] = m.calibrated_until < now
            item["renewals"] = renewals.get(m.meter_no, [])
            result.append(item)
        return jsonify(result)
    finally:
        db.close()


@app.put("/api/meters/<meter_no>")
@require_writer
def update_meter(meter_no):
    """测量员登记/修改校准到期日；与报送互斥（同号同把咨询锁），每次改动留痕。"""
    meter_no = meter_no.strip()
    if not meter_no:
        return jsonify({"detail": "测缝计号不能为空"}), 400
    body = request.get_json(silent=True) or {}
    new_until = parse_calibrated_until(body.get("calibrated_until"))
    if new_until is None:
        return jsonify({"detail": "到期日格式应为 YYYY-MM-DD"}), 400

    db = SessionLocal()
    try:
        # 事务级咨询锁：同一测缝计号的续期与报送完全串行，行不存在时也成立
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"joint_meter:{meter_no}"},
        )
        meter = db.query(JointMeter).filter(JointMeter.meter_no == meter_no).one_or_none()
        if meter is None:
            meter = JointMeter(meter_no=meter_no, calibrated_until=new_until)
            db.add(meter)
            old_until = None
        else:
            old_until = meter.calibrated_until
            meter.calibrated_until = new_until
        db.add(
            MeterRenewal(
                meter_no=meter_no,
                old_until=old_until,
                new_until=new_until,
                changed_by=g.user["username"],
                changed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        db.refresh(meter)
        return jsonify(meter_dict(meter))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/api/logs")
@require_login
def list_logs():
    db = SessionLocal()
    try:
        rows = db.query(ConvergenceLog).order_by(ConvergenceLog.id.desc()).all()
        return jsonify([row_dict(r) for r in rows])
    finally:
        db.close()


@app.post("/api/logs")
@require_writer
def create_log():
    body = request.get_json(silent=True) or {}
    meter_no = (body.get("meter_no") or "").strip()
    if not meter_no:
        return jsonify({"detail": "测缝计号不能为空"}), 400
    chainage = (body.get("chainage") or "").strip()
    if not chainage:
        return jsonify({"detail": "桩号不能为空"}), 400
    try:
        delta_mm = float(body.get("delta_mm"))
    except (TypeError, ValueError):
        return jsonify({"detail": "收敛值必须是数字"}), 400

    db = SessionLocal()
    try:
        # 与续期同一把锁（同 key）：同瞬间对撞时按拿锁顺序只有一种结局，
        # 绝不会既收下报送又显示过期
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"joint_meter:{meter_no}"},
        )
        meter = db.query(JointMeter).filter(JointMeter.meter_no == meter_no).one_or_none()
        if meter is None:
            return jsonify({"detail": f"测缝计 {meter_no} 未登记，不能报送"}), 400

        now = datetime.now(timezone.utc)
        if meter.calibrated_until < now:
            reason = expire_reason(meter_no, meter.calibrated_until)
            db.add(
                MeterBlock(
                    meter_no=meter_no,
                    chainage=chainage,
                    reason=reason,
                    blocked_by=g.user["username"],
                    blocked_at=now,
                )
            )
            db.commit()
            return (
                jsonify(
                    {
                        "detail": reason,
                        "code": "calibration_expired",
                        "meter_no": meter_no,
                        "calibrated_until": meter.calibrated_until.isoformat(),
                    }
                ),
                403,
            )

        row = ConvergenceLog(
            meter_no=meter_no,
            chainage=chainage,
            delta_mm=delta_mm,
            status="pending",
            created_by=g.user["username"],
            created_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return jsonify(row_dict(row)), 201
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
