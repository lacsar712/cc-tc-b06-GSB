import os
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request
from jose import JWTError, jwt
from passlib.context import CryptContext

import calibration
from claimer import start as start_claimer
from models import (
    Base,
    CalibrationEvent,
    ConvergenceLog,
    Meter,
    SessionLocal,
    engine,
    event_dict,
    meter_dict,
    migrate,
    row_dict,
)

SECRET = os.environ.get("JWT_SECRET", "tunnelconv-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

app = Flask(__name__)


def seed():
    migrate()
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        if db.query(Meter).count() == 0:
            ts = datetime.now(timezone.utc)
            # 甲号在有效期内；乙号校准昨天到期（专页上直接能看到过期与拦截）。
            for code, label, expires_on in (
                ("JFJ-A", "甲号测缝计", today + timedelta(days=180)),
                ("JFJ-B", "乙号测缝计", today - timedelta(days=1)),
            ):
                db.add(
                    Meter(
                        code=code,
                        label=label,
                        expires_on=expires_on,
                        created_at=ts,
                    )
                )
                db.add(
                    CalibrationEvent(
                        meter_code=code,
                        kind="register",
                        old_expires_on=None,
                        new_expires_on=expires_on,
                        actor="system",
                        created_at=ts,
                    )
                )
        if db.query(ConvergenceLog).count() > 0:
            db.commit()
            return
        now = datetime.now(timezone.utc)
        for meter_code, chainage, delta, expect in (
            ("JFJ-A", "K12+180", 1.2, "合格"),
            ("JFJ-B", "K18+040", 5.6, "超限"),
        ):
            from rules import judge

            verdict, reason = judge(delta)
            assert verdict == expect
            db.add(
                ConvergenceLog(
                    meter_code=meter_code,
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
if not os.environ.get("DISABLE_CLAIMER"):
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
            return jsonify({"detail": "仅测量员可操作，巡检员只读"}), 403
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
    """到期专页数据：各号到期日 + 最近拦住的原因。"""
    db = SessionLocal()
    try:
        rows = db.query(Meter).order_by(Meter.code).all()
        return jsonify([meter_dict(r) for r in rows])
    finally:
        db.close()


@app.get("/api/calibration-events")
@require_login
def list_calibration_events():
    """续期 / 改期痕迹，新事件在前，可按测缝计号过滤。"""
    code = (request.args.get("meter_code") or "").strip()
    db = SessionLocal()
    try:
        q = db.query(CalibrationEvent).order_by(CalibrationEvent.id.desc())
        if code:
            q = q.filter(CalibrationEvent.meter_code == code)
        return jsonify([event_dict(r) for r in q.limit(200).all()])
    finally:
        db.close()


def _parse_expiry(body) -> tuple[date | None, str | None]:
    raw = (body.get("expires_on") or "").strip()
    if not raw:
        return None, "到期日不能为空（格式 YYYY-MM-DD）"
    try:
        return calibration.parse_date(raw), None
    except (ValueError, TypeError):
        return None, "到期日格式应为 YYYY-MM-DD"


@app.put("/api/meters/<code>/expiry")
@require_writer
def set_meter_expiry(code):
    """测量员改到期日：可以改到昨天——过期后该号再报即被拦。"""
    body = request.get_json(silent=True) or {}
    expires_on, err = _parse_expiry(body)
    if err:
        return jsonify({"detail": err}), 400
    try:
        meter, event = calibration.change_expiry(
            code=code, new_expires_on=expires_on, actor=g.user["username"]
        )
    except calibration.MeterNotFound:
        return jsonify({"detail": f"测缝计 {code} 不存在"}), 404
    return jsonify({"meter": meter, "event": event})


@app.post("/api/meters/<code>/renew")
@require_writer
def renew_meter(code):
    """续期：默认顺延一年，也可传 expires_on（不得早于今天）。"""
    body = request.get_json(silent=True) or {}
    expires_on = None
    if (body.get("expires_on") or "").strip():
        expires_on, err = _parse_expiry(body)
        if err:
            return jsonify({"detail": err}), 400
    try:
        meter, event = calibration.renew(
            code=code, new_expires_on=expires_on, actor=g.user["username"]
        )
    except calibration.MeterNotFound:
        return jsonify({"detail": f"测缝计 {code} 不存在"}), 404
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify({"meter": meter, "event": event})


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
    meter_code = (body.get("meter_code") or "").strip()
    if not meter_code:
        return jsonify({"detail": "必须选择测缝计号"}), 400
    chainage = (body.get("chainage") or "").strip()
    if not chainage:
        return jsonify({"detail": "桩号不能为空"}), 400
    try:
        delta_mm = float(body.get("delta_mm"))
    except (TypeError, ValueError):
        return jsonify({"detail": "收敛值必须是数字"}), 400
    try:
        row = calibration.submit_log(
            meter_code=meter_code,
            chainage=chainage,
            delta_mm=delta_mm,
            username=g.user["username"],
        )
    except calibration.MeterNotFound:
        return jsonify({"detail": f"测缝计 {meter_code} 不存在"}), 404
    except calibration.MeterExpired as blocked:
        # 423 Locked：读数没进待认领队列，提示续期以后再开
        return (
            jsonify(
                {
                    "detail": blocked.reason,
                    "code": "meter_expired",
                    "meter": blocked.meter,
                    "log": blocked.log_row,
                }
            ),
            423,
        )
    return jsonify(row), 201
