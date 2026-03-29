"""Route definitions for the student-facing attendance web server."""

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, session, current_app
from core.database import (
    add_attendance,
    block_device,
    get_active_session,
    is_device_blocked,
    is_student_id_submitted,
)
from core.exceptions import YaqeenError
from core.fingerprint import compute_fingerprint_hash
from core.models import AttendanceRecord
from network.arp_scanner import get_mac_for_ip

logger = logging.getLogger(__name__)

bp = Blueprint("attendance", __name__, template_folder="templates")

_rate_limit_lock = threading.Lock()
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


class SubmissionError(YaqeenError):
    """Raised when an attendance submission fails validation."""

    pass


class TokenExpiredError(YaqeenError):
    """Raised when a submitted token is expired or invalid."""

    pass


def _honeypot_response(app):
    response = app.make_response("")
    response.status_code = 404
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _get_config(app):
    return app.config["CONFIG"]


def _with_db_lock(app, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) holding DB_LOCK if configured."""
    lock = app.config.get("DB_LOCK")
    if lock is not None:
        with lock:
            return fn(*args, **kwargs)
    return fn(*args, **kwargs)


def _check_rate_limit(app, session_id: int, client_key: str) -> bool:
    """Return True if this client is within the rate limit window."""
    cfg = _get_config(app)
    max_req = getattr(cfg, "RATE_LIMIT_MAX_REQUESTS", 2)
    window = getattr(cfg, "RATE_LIMIT_WINDOW_SECONDS", 5)
    now = time.monotonic()
    with _rate_limit_lock:
        key = f"{session_id}:{client_key}"
        times = _rate_limit_store[key]
        times[:] = [t for t in times if now - t < window]
        if len(times) >= max_req:
            return False
        times.append(now)
    return True


def _clear_session_rate_limits(session_id: int) -> None:
    prefix = f"{session_id}:"
    with _rate_limit_lock:
        keys = [k for k in _rate_limit_store if k.startswith(prefix)]
        for k in keys:
            del _rate_limit_store[k]


def _make_csrf_token() -> str:
    return secrets.token_hex(16)


def _sign_submitted_cookie(app, session_id: int) -> str:
    key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
    payload = str(session_id).encode()
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return f"{session_id}.{sig}"


def _verify_submitted_cookie(app, value: str, session_id: int) -> bool:
    if not value or "." not in value:
        return False
    try:
        sid_str, sig = value.rsplit(".", 1)
        if int(sid_str) != session_id:
            return False
        key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
        expected = hmac.new(key, sid_str.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except (ValueError, TypeError):
        return False


def _validate_student_id(cfg, raw: str) -> str | None:
    raw = (raw or "").strip()
    if len(raw) > getattr(cfg, "MAX_STUDENT_ID_LENGTH", 20):
        return None
    pattern = getattr(cfg, "STUDENT_ID_REGEX", r"^[a-zA-Z0-9]{1,20}$")
    if not re.match(pattern, raw):
        return None
    return raw


def _validate_student_name(cfg, raw: str) -> str | None:
    raw = (raw or "").strip()
    if len(raw) > getattr(cfg, "MAX_STUDENT_NAME_LENGTH", 100):
        return None
    pattern = getattr(cfg, "STUDENT_NAME_REGEX", r"^[a-zA-Z\u00C0-\u024F\u0400-\u04FF\s\-]{1,100}$")
    if not re.match(pattern, raw):
        return None
    return raw


def _build_screen_data(request_obj) -> str:
    parts = [
        request_obj.form.get("screen_resolution") or "",
        request_obj.form.get("timezone") or "",
        request_obj.form.get("platform") or "",
    ]
    return "|".join(parts)


def _build_extra_fp_fields(request_obj) -> dict[str, str]:
    """Extract the extra JS-collected fingerprint fields from the form."""
    keys = ("color_depth", "pixel_ratio", "hw_concurrency", "touch_points", "canvas_hash")
    return {k: (request_obj.form.get(k) or "") for k in keys}


def clear_session_ip_submissions(session_id: int) -> None:
    """Clear in-memory anti-abuse tracking for a session. Call when session ends."""
    _clear_session_rate_limits(session_id)


def _get_client_rate_key(ip: str) -> str:
    nonce = session.get("client_nonce", "")
    if nonce:
        return nonce
    ua = request.headers.get("User-Agent", "")
    al = request.headers.get("Accept-Language", "")
    raw = f"{ip}|{ua}|{al}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


@bp.route("/")
def index() -> object:
    """Return a bland response for scanners."""
    return _honeypot_response(current_app)


@bp.route("/attend")
def attend() -> object:
    """Show attendance form if token is valid and device not blocked."""
    token = request.args.get("token", "").strip()
    app = current_app
    token_mgr = app.config["TOKEN_MANAGER"]
    db_conn = app.config["DB_CONN"]
    cfg = _get_config(app)

    if not token_mgr.validate(token):
        return _honeypot_response(app)

    active = _with_db_lock(app, get_active_session, db_conn)
    if active is None:
        return render_template("error.html", message="No active attendance session. Please try again later."), 503

    cookie_name = getattr(cfg, "COOKIE_SUBMITTED_NAME", "yaqeen_submitted")
    cookie_val = request.cookies.get(cookie_name, "")
    if _verify_submitted_cookie(app, cookie_val, active.id):
        return render_template("error.html", message="You have already submitted attendance."), 403

    ip = request.remote_addr or ""
    mac = ""
    try:
        mac = get_mac_for_ip(ip) or ""
    except YaqeenError as e:
        logger.warning("ARP lookup failed for %s: %s", ip, e)

    user_agent = request.headers.get("User-Agent", "")
    accept_lang = request.headers.get("Accept-Language", "")
    fp_hash = compute_fingerprint_hash(user_agent, accept_lang, "")

    if _with_db_lock(app, is_device_blocked, db_conn, active.id, mac or "unknown", fp_hash):
        return render_template("error.html", message="You have already submitted attendance from this device."), 403

    session["csrf_token"] = _make_csrf_token()
    session["client_nonce"] = secrets.token_hex(8)
    session["fp_partial"] = fp_hash
    csrf = session["csrf_token"]

    return render_template(
        "form.html",
        token=token,
        session_id=active.id,
        csrf_token=csrf,
    )


@bp.route("/submit", methods=["POST"])
def submit():
    """Process attendance submission."""
    app = current_app
    db_conn = app.config["DB_CONN"]
    token_mgr = app.config["TOKEN_MANAGER"]
    cfg = _get_config(app)

    ip = request.remote_addr or ""
    active = _with_db_lock(app, get_active_session, db_conn)
    if active is None:
        return render_template("error.html", message="No active attendance session. Please try again later."), 503

    csrf = request.form.get("csrf_token", "")
    stored_csrf = session.pop("csrf_token", "")
    if not csrf or not stored_csrf or not secrets.compare_digest(csrf, stored_csrf):
        return render_template("error.html", message="Something went wrong. Please try again."), 400

    if not _check_rate_limit(app, active.id, _get_client_rate_key(ip)):
        return render_template("error.html", message="Too many requests. Please wait a moment and try again."), 429

    token = request.form.get("token", "").strip()
    if not token_mgr.validate(token):
        return render_template("error.html", message="This link has expired or is invalid. Please scan the QR code again."), 400

    student_id = _validate_student_id(cfg, request.form.get("student_id", ""))
    student_name = _validate_student_name(cfg, request.form.get("student_name", ""))
    if student_id is None:
        return render_template(
            "error.html",
            message="Invalid student ID format. Please use only letters and numbers (up to 20 characters) and try again.",
        ), 400
    if student_name is None:
        return render_template(
            "error.html",
            message="Invalid name format. Please use only letters and spaces (up to 100 characters) and try again.",
        ), 400
    if len(student_id) <= 6:
        return render_template(
            "error.html",
            message="Student ID must be more than 6 digits. Please enter your full ID and resubmit.",
        ), 400
    word_count = len([w for w in student_name.split() if w.strip()])
    if word_count < 2:
        return render_template(
            "error.html",
            message="Full name must contain at least two words (e.g. first name and last name). Please enter your full name and resubmit.",
        ), 400

    mac = ""
    try:
        mac = get_mac_for_ip(ip) or ""
    except YaqeenError as e:
        logger.warning("ARP lookup failed for %s: %s", ip, e)
    mac = mac or "unknown"

    user_agent = request.headers.get("User-Agent", "")
    accept_lang = request.headers.get("Accept-Language", "")
    screen_data = _build_screen_data(request)
    fp_hash = compute_fingerprint_hash(user_agent, accept_lang, screen_data)

    if _with_db_lock(app, is_device_blocked, db_conn, active.id, mac, fp_hash):
        return render_template("error.html", message="You have already submitted attendance from this device."), 403

    if _with_db_lock(app, is_student_id_submitted, db_conn, active.id, student_id):
        return render_template("error.html", message="This student ID has already been recorded for this session."), 409

    record = AttendanceRecord(
        id=0,
        session_id=active.id,
        student_id=student_id,
        student_name=student_name,
        mac_address=mac,
        fingerprint_hash=fp_hash,
        token_used=token,
        submitted_at=datetime.now().isoformat(),
        ip_address=ip,
    )
    try:
        _with_db_lock(app, add_attendance, db_conn, record)
    except YaqeenError as e:
        logger.exception("Submit failed during attendance insert: %s", e)
        return render_template("error.html", message="Something went wrong. Please try again."), 500

    try:
        _with_db_lock(app, block_device, db_conn, mac, fp_hash, active.id)
    except YaqeenError as e:
        logger.error("Block device failed after attendance recorded for session %s: %s", active.id, e)

    cookie_name = getattr(cfg, "COOKIE_SUBMITTED_NAME", "yaqeen_submitted")
    cookie_max_age = getattr(cfg, "COOKIE_MAX_AGE_SECONDS", 86400 * 7)
    response = current_app.make_response(render_template("success.html"))
    signed = _sign_submitted_cookie(app, active.id)
    response.set_cookie(
        cookie_name,
        signed,
        max_age=cookie_max_age,
        httponly=True,
        samesite="Strict",
        secure=False,
    )
    return response
