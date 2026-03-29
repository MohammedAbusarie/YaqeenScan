"""Flask application factory for the student-facing web server."""

import os
import sqlite3
import sys
from typing import Any

from flask import Flask

from core.config import FLASK_SECRET_KEY
from core.token_manager import TokenManager


def _template_and_static_folders() -> tuple[str, str]:
    """Return (template_folder, static_folder) for Flask, valid when frozen or not."""
    if getattr(sys, "frozen", False):
        base = os.path.join(sys._MEIPASS, "server")
        return os.path.join(base, "templates"), os.path.join(base, "static")
    return "templates", "static"


def create_app(
    db_conn: sqlite3.Connection,
    token_manager: TokenManager,
    config: Any,
    db_lock: Any = None,
) -> Flask:
    """Create and configure the Flask application.

    Stores db_conn, db_lock, token_manager, and config in app.config for route access.
    Registers all routes from routes module.

    Args:
        db_conn: Shared SQLite connection for attendance and session data.
        token_manager: Rotating token manager for QR validation.
        config: Configuration module (e.g. core.config) for constants.
        db_lock: Optional threading.Lock to serialize DB access from multiple threads.

    Returns:
        Configured Flask application instance.
    """
    template_folder, static_folder = _template_and_static_folders()
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    app.secret_key = getattr(config, "FLASK_SECRET_KEY", FLASK_SECRET_KEY)
    app.config["DB_CONN"] = db_conn
    app.config["DB_LOCK"] = db_lock
    app.config["TOKEN_MANAGER"] = token_manager
    app.config["CONFIG"] = config
    from server import routes

    app.register_blueprint(routes.bp)

    @app.context_processor
    def inject_footer():
        from core.config import FOOTER_TEXT
        return {"footer_text": FOOTER_TEXT}

    return app
