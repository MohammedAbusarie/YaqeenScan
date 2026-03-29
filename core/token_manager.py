"""TOTP-style rotating token manager for QR code authentication."""

import logging
import secrets
import threading

from core.config import TOKEN_BYTES
from core.exceptions import YaqeenError


logger = logging.getLogger(__name__)


class TokenError(YaqeenError):
    """Raised when a token operation fails."""
    pass


class TokenManager:
    """Manages rotating tokens for QR code authentication.

    Holds a current and previous token to provide a grace period
    during rotation. Uses secrets module for cryptographic randomness.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._current_token: str = ""
        self._previous_token: str = ""
        self._stop_event: threading.Event = threading.Event()
        self._rotation_thread: threading.Thread | None = None
        self._rotate()

    def _rotate(self) -> None:
        with self._lock:
            self._previous_token = self._current_token
            self._current_token = secrets.token_hex(TOKEN_BYTES)

    def rotate(self) -> None:
        """Generate a new token and push current to previous."""
        with self._lock:
            self._previous_token = self._current_token
            self._current_token = secrets.token_hex(TOKEN_BYTES)
        logger.debug("Token rotated")

    def validate(self, token: str) -> bool:
        """Return True if token matches current or previous (grace period)."""
        if not token or not isinstance(token, str):
            return False
        t = token.strip()
        with self._lock:
            return t == self._current_token or t == self._previous_token

    def get_current(self) -> str:
        """Return the current active token."""
        with self._lock:
            return self._current_token

    def start_auto_rotation(self, interval: int) -> None:
        """Start a daemon thread that calls rotate() every interval seconds."""
        if self._rotation_thread is not None and self._rotation_thread.is_alive():
            logger.warning("Auto-rotation already running")
            return
        self._stop_event.clear()

        def _run() -> None:
            while not self._stop_event.wait(timeout=interval):
                try:
                    self.rotate()
                except Exception as exc:
                    logger.exception("Token rotation failed: %s", exc)

        self._rotation_thread = threading.Thread(target=_run, daemon=True)
        self._rotation_thread.start()
        logger.info("Token auto-rotation started (interval=%ds)", interval)

    def stop(self) -> None:
        """Stop the auto-rotation thread."""
        self._stop_event.set()
        if self._rotation_thread is not None:
            self._rotation_thread.join(timeout=2.0)
            self._rotation_thread = None
        logger.info("Token auto-rotation stopped")
