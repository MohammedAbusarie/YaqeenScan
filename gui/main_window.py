"""Main application window for the professor-facing desktop GUI."""

import logging
import os
from typing import Callable

import customtkinter as ctk

from core.config import (
    APP_TITLE,
    ATTENDANCE_POLL_MS,
    QR_REFRESH_MS,
    STATUS_BAR_RIGHT,
    THEME_ACCENT,
    THEME_BG_CARD,
    THEME_BG_PRIMARY,
    THEME_TEXT_SECONDARY,
)
from core.database import get_session_attendance
from core.models import Session
from gui.attendance_panel import AttendancePanel
from gui.qr_panel import QRPanel
from gui.session_controls import SessionControls

logger = logging.getLogger(__name__)


class MainWindow(ctk.CTk):
    """Root window containing QR display, attendance list, and session controls.

    Layout: left panel for QR code, right panel for attendance list
    and session controls, status bar at bottom. Uses dependency injection
    for all I/O and session lifecycle (callbacks).
    """

    def __init__(
        self,
        db_conn,
        token_manager,
        config,
        start_session_cb: Callable[[str], Session | None],
        end_session_cb: Callable[[], None],
        get_base_url_cb: Callable[[], str],
        get_system_status_cb: Callable[[], tuple[bool, Session | None]],
        export_cb: Callable[[], str],
        db_lock=None,
        icon_path: str | None = None,
    ) -> None:
        super().__init__(fg_color=THEME_BG_PRIMARY)
        self._conn = db_conn
        self._token_manager = token_manager
        self._config = config
        self._db_lock = db_lock
        self._get_base_url = get_base_url_cb
        self._get_system_status = get_system_status_cb
        self.title(APP_TITLE)
        self._set_window_icon(icon_path)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self._build_layout(
            start_session_cb,
            end_session_cb,
            get_system_status_cb,
            export_cb,
        )
        self._schedule_polling()

    def _set_window_icon(self, icon_path: str | None) -> None:
        """Set the window and taskbar icon from appicon.png (or .ico). Uses .ico on Windows for taskbar."""
        if not icon_path or not os.path.isfile(icon_path):
            self._icon_ico_path = None
            return
        icon_path = os.path.abspath(icon_path)
        base, ext = os.path.splitext(icon_path)
        try:
            if ext.lower() == ".ico":
                self._icon_ico_path = icon_path
                self.iconbitmap(icon_path)
                self.after(200, lambda p=icon_path: self._iconbitmap_safe(p))
                return
            # PNG (or other): convert to .ico so Windows taskbar and title bar show it
            from PIL import Image
            import tempfile
            img = Image.open(icon_path).convert("RGBA")
            sizes = [(16, 16), (32, 32), (48, 48), (256, 256)]
            ico_path = os.path.join(tempfile.gettempdir(), "yaqeen_icon.ico")
            img.save(ico_path, format="ICO", sizes=sizes)
            self._icon_ico_path = ico_path
            self.iconbitmap(ico_path)
            # Set again after window is realized (helps taskbar on Windows)
            self.after(200, lambda p=ico_path: self._iconbitmap_safe(p))
        except Exception as e:
            logger.warning("Could not set window icon from %s: %s", icon_path, e)
            self._icon_ico_path = None

    def _iconbitmap_safe(self, path: str) -> None:
        try:
            self.iconbitmap(path)
        except Exception:
            pass

    def _build_layout(
        self,
        start_session_cb: Callable[[str], Session | None],
        end_session_cb: Callable[[], None],
        get_system_status_cb: Callable[[], tuple[bool, Session | None]],
        export_cb: Callable[[], str],
    ) -> None:
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=8, pady=8)
        content.grid_columnconfigure(0, minsize=320, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(content, fg_color=THEME_BG_CARD, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
        self._qr_panel = QRPanel(left, on_qr_click_cb=self._on_qr_click)
        self._qr_panel.pack(fill="both", expand=True, padx=8, pady=8)
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        self._attendance_panel = AttendancePanel(right)
        self._attendance_panel.pack(fill="both", expand=True, pady=(0, 8))
        self._session_controls = SessionControls(
            right,
            start_session_cb=start_session_cb,
            end_session_cb=end_session_cb,
            export_cb=export_cb,
            on_about_cb=self._show_about_dialog,
            get_session_cb=lambda: get_system_status_cb()[1],
            on_session_started_cb=self._poll_qr,
            dialog_icon_path=getattr(self, "_icon_ico_path", None),
        )
        self._session_controls.pack(fill="x")
        self._status_bar = ctk.CTkFrame(self, fg_color=THEME_BG_CARD, height=28)
        self._status_bar.pack(side="bottom", fill="x")
        self._status_bar.pack_propagate(False)
        self._status_left = ctk.CTkLabel(
            self._status_bar,
            text="Hotspot: —  |  Session: —",
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="w",
        )
        self._status_left.pack(side="left", padx=8, pady=4)
        self._status_right = ctk.CTkLabel(
            self._status_bar,
            text=STATUS_BAR_RIGHT,
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="e",
        )
        self._status_right.pack(side="right", padx=8, pady=4)

    def _show_about_dialog(self) -> None:
        lines = [
            "YaqeenScan — Egyptian Chinese University (Non Offical)",
            "",
            "This tool is a solution engineered by Mohammed Abusarie to make the flow of taking attendance easy and secure:",
            "- Students cannot submit on behalf of others (per-device fingerprints, cookies, and rate limiting).",
            "- Smart, fully offline-friendly QR workflow (local Flask server with rotating tokens).",
            "- Optional Windows hotspot support with graceful LAN fallback.",
            "- Automatic export to CSV/XLSX at session end for record keeping.",
            "- Temporary security hardening on the host (firewall lockdown, NetBIOS/LLMNR disable, ICS stop) with best-effort revert.",
        ]
        text = "\n".join(lines)
        import tkinter.messagebox as messagebox
        messagebox.showinfo("About YaqeenScan", text)

    def _schedule_polling(self) -> None:
        self._poll_status_and_attendance()
        self._poll_qr()
        self._after_status = self.after(
            ATTENDANCE_POLL_MS,
            self._poll_status_and_attendance,
        )
        self._after_qr = self.after(QR_REFRESH_MS, self._poll_qr)

    def _on_qr_click(self) -> None:
        """Rotate token and refresh QR so a new code is shown (click-to-refresh)."""
        self._token_manager.rotate()
        self._poll_qr()

    def _poll_status_and_attendance(self) -> None:
        try:
            hotspot_running, session = self._get_system_status()
            if session is not None:
                if hotspot_running:
                    network_label = "Hotspot: Running (YaqeenScan)"
                else:
                    base = self._get_base_url()
                    network_label = f"Network: LAN  {base}" if base else "Network: No connection"
                status_left = f"{network_label}  |  Session: {session.course_name}"
            else:
                status_left = "No active session"
            self._status_left.configure(text=status_left)
            self._session_controls.update_timer()
            if session is not None:
                if self._db_lock is not None:
                    with self._db_lock:
                        records = get_session_attendance(self._conn, session.id)
                else:
                    records = get_session_attendance(self._conn, session.id)
                self._attendance_panel.refresh(records)
            else:
                self._attendance_panel.refresh([])
        except Exception as e:
            logger.warning("Poll status/attendance failed: %s", e, exc_info=True)
        self._after_status = self.after(
            ATTENDANCE_POLL_MS,
            self._poll_status_and_attendance,
        )

    def _poll_qr(self) -> None:
        try:
            hotspot_running, session = self._get_system_status()
            session_active = session is not None
            if session_active:
                base = self._get_base_url()
                token = self._token_manager.get_current()
                url = f"{base.rstrip('/')}/attend?token={token}" if base and token else ""
            else:
                url = ""
            self._qr_panel.update_qr(
                url,
                hotspot_active=hotspot_running,
                session_active=session_active,
            )
        except Exception as e:
            logger.warning("Poll QR failed: %s", e, exc_info=True)
        self._after_qr = self.after(QR_REFRESH_MS, self._poll_qr)

    def set_status_message(self, message: str) -> None:
        """Set the left part of the status bar (e.g. error or info)."""
        self._status_left.configure(text=message)

    def on_closing(self) -> None:
        """Cancel polling and allow window to close."""
        for attr in ("_after_status", "_after_qr"):
            aid = getattr(self, attr, None)
            if aid is not None:
                self.after_cancel(aid)
                setattr(self, attr, None)
        self.destroy()
