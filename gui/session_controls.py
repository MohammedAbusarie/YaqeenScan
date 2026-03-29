"""Session control buttons for the professor-facing GUI."""

import logging
import threading
from datetime import datetime
from typing import Callable

import customtkinter as ctk

from core.config import (
    APP_TITLE,
    THEME_ACCENT,
    THEME_ACCENT_HOVER,
    THEME_BG_CARD,
    THEME_BG_ELEVATED,
    THEME_ERROR,
    THEME_TEXT_PRIMARY,
    THEME_TEXT_SECONDARY,
)
from core.models import Session

logger = logging.getLogger(__name__)

_HOTSPOT_WARN = (
    "⚠  Hotspot unavailable on this WiFi adapter.\n"
    "1. Turn on your phone's Mobile Hotspot\n"
    "2. Connect this laptop to that hotspot\n"
    "3. Have students join the same hotspot\n"
    "The QR code will update automatically."
)


def _iconbitmap_safe(win, path: str) -> None:
    try:
        win.iconbitmap(path)
    except Exception:
        pass


def _format_elapsed(start_time_iso: str) -> str:
    """Return elapsed time string MM:SS from session start time."""
    if not start_time_iso:
        return "00:00"
    try:
        start = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
        now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()
        delta = now - start
        total_seconds = max(0, int(delta.total_seconds()))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "00:00"


class SessionControls(ctk.CTkFrame):
    """Provides Start/End Session and Export buttons.

    Manages the lifecycle of an attendance session via callbacks.
    start_session_cb(course_name) must return (Session | None, hotspot_ok: bool).
    Displays a persistent hotspot warning banner when the hotspot is unavailable.
    """

    def __init__(
        self,
        master: ctk.CTk,
        start_session_cb: Callable[[str], tuple[Session | None, bool]],
        end_session_cb: Callable[[], None],
        export_cb: Callable[[], str],
        on_about_cb: Callable[[], None] | None = None,
        get_session_cb: Callable[[], Session | None] | None = None,
        on_session_started_cb: Callable[[], None] | None = None,
        dialog_icon_path: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._start_cb = start_session_cb
        self._end_cb = end_session_cb
        self._export_cb = export_cb
        self._on_about_cb = on_about_cb
        self._get_session_cb = get_session_cb or (lambda: None)
        self._on_session_started_cb = on_session_started_cb
        self._dialog_icon_path = dialog_icon_path
        self._export_in_progress = False

        self._hotspot_banner = ctk.CTkFrame(
            self,
            fg_color=THEME_BG_ELEVATED,
            corner_radius=6,
        )
        self._hotspot_banner_label = ctk.CTkLabel(
            self._hotspot_banner,
            text=_HOTSPOT_WARN,
            font=("", 13),
            text_color=THEME_TEXT_PRIMARY,
            justify="left",
            wraplength=340,
            anchor="w",
        )
        self._hotspot_banner_label.pack(padx=10, pady=8, anchor="w")

        self._timer_label = ctk.CTkLabel(
            self,
            text="Session: —",
            font=("", 14),
            text_color=THEME_TEXT_SECONDARY,
        )
        self._timer_label.pack(pady=(0, 4))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x")
        self._btn_start = ctk.CTkButton(
            btn_frame,
            text="Start Session",
            fg_color=THEME_ACCENT,
            hover_color=THEME_ACCENT_HOVER,
            command=self._on_start,
            height=38,
            font=("", 14),
        )
        self._btn_end = ctk.CTkButton(
            btn_frame,
            text="End Session",
            fg_color=THEME_BG_CARD,
            command=self._on_end,
            height=38,
            font=("", 14),
        )
        self._btn_export = ctk.CTkButton(
            btn_frame,
            text="Export",
            fg_color=THEME_BG_CARD,
            command=self._on_export,
            height=38,
            font=("", 14),
        )
        self._btn_about = ctk.CTkButton(
            btn_frame,
            text="About",
            fg_color=THEME_BG_CARD,
            command=self._on_about,
            height=38,
            font=("", 14),
        )
        self._btn_start.pack(side="left", padx=4, pady=4)
        self._btn_end.pack(side="left", padx=4, pady=4)
        self._btn_export.pack(side="left", padx=4, pady=4)
        self._btn_about.pack(side="left", padx=4, pady=4)
        self._update_buttons_for_session(None)

    def show_hotspot_warning(self, visible: bool) -> None:
        """Show or hide the hotspot-unavailable instruction banner."""
        if visible:
            self._hotspot_banner.pack(fill="x", padx=4, pady=(4, 0), before=self._timer_label)
        else:
            self._hotspot_banner.pack_forget()

    def update_timer(self) -> None:
        """Update the session timer label and button states from current session."""
        session = self._get_session_cb()
        if session is None:
            self._timer_label.configure(text="Session: —")
        else:
            elapsed = _format_elapsed(session.start_time)
            self._timer_label.configure(text=f"Session: {session.course_name} ({elapsed})")
        self._update_buttons_for_session(session)

    def _update_buttons_for_session(self, session: Session | None) -> None:
        """Enable/disable buttons based on whether a session is active.
        Start is enabled only when no session; End and Export only when session is active.
        About is always enabled.
        """
        if session is None:
            self._btn_start.configure(state="normal")
            self._btn_end.configure(state="disabled")
            self._btn_export.configure(state="disabled")
        else:
            self._btn_start.configure(state="disabled")
            self._btn_end.configure(state="normal")
            self._btn_export.configure(state="normal")
        self._btn_about.configure(state="normal")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._btn_start.configure(state=state)
        self._btn_end.configure(state=state)
        self._btn_export.configure(state=state)

    def _on_about(self) -> None:
        if self._on_about_cb is not None:
            self._on_about_cb()

    def _input_dialog_with_icon(self, title: str, text: str) -> str | None:
        """Show a modal input dialog with the app icon. Returns entered text or None if cancelled."""
        root = self.winfo_toplevel()
        dialog = ctk.CTkToplevel(root)
        dialog.title(title)
        dialog.geometry("400x160")
        dialog.transient(root)
        dialog.grab_set()
        if self._dialog_icon_path:
            try:
                dialog.iconbitmap(self._dialog_icon_path)
                dialog.after(200, lambda: _iconbitmap_safe(dialog, self._dialog_icon_path))
            except Exception:
                pass
        result: list[str | None] = [None]
        label = ctk.CTkLabel(dialog, text=text, font=("", 13), wraplength=360)
        label.pack(pady=(16, 8), padx=20, anchor="w")
        entry = ctk.CTkEntry(dialog, width=360, font=("", 14))
        entry.pack(pady=(0, 16), padx=20)
        entry.focus_set()

        def on_ok() -> None:
            result[0] = entry.get().strip() or None
            dialog.destroy()

        def on_cancel() -> None:
            result[0] = None
            dialog.destroy()

        def on_return(event) -> None:
            on_ok()

        entry.bind("<Return>", on_return)
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=(0, 12))
        ctk.CTkButton(btn_frame, text="OK", command=on_ok, width=100, height=32).pack(side="left", padx=4)
        ctk.CTkButton(btn_frame, text="Cancel", command=on_cancel, width=100, height=32).pack(side="left", padx=4)
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)
        dialog.wait_window()
        return result[0]

    def _on_start(self) -> None:
        if self._dialog_icon_path:
            course_name = self._input_dialog_with_icon("Start Session", f"Enter course name for {APP_TITLE}")
        else:
            dialog = ctk.CTkInputDialog(
                text=f"Enter course name for {APP_TITLE}",
                title="Start Session",
            )
            course_name = dialog.get_input()
        if course_name is None:
            return
        course_name = course_name.strip()
        if not course_name:
            return
        self._set_buttons_enabled(False)
        self._timer_label.configure(text="Starting session…")

        def _run() -> None:
            try:
                session, hotspot_ok = self._start_cb(course_name)
                if session is None:
                    logger.warning("Start session callback returned None")
                    def _update_for_existing_or_failed() -> None:
                        current = self._get_session_cb()
                        if current is not None:
                            elapsed = _format_elapsed(current.start_time)
                            self._timer_label.configure(
                                text=f"Session already active: {current.course_name} ({elapsed})"
                            )
                        else:
                            self._timer_label.configure(
                                text="Failed to start — check log for details"
                            )
                    self.after(0, _update_for_existing_or_failed)
                else:
                    logger.info("Session started: %s", course_name)
                    if not hotspot_ok:
                        self.after(0, lambda: self.show_hotspot_warning(True))
                    if self._on_session_started_cb is not None:
                        self.after(0, self._on_session_started_cb)
            except Exception as e:
                logger.exception("Start session failed: %s", e)
                msg = str(e)
                def _show_err() -> None:
                    from tkinter import messagebox
                    messagebox.showerror("Start Session", msg)
                self.after(0, _show_err)
            finally:
                self.after(0, lambda: self._update_buttons_for_session(self._get_session_cb()))

        threading.Thread(target=_run, daemon=True).start()

    def _on_end(self) -> None:
        self._set_buttons_enabled(False)
        self._timer_label.configure(text="Ending session…")

        def _run() -> None:
            try:
                self._end_cb()
                self.after(0, lambda: self.show_hotspot_warning(False))
            except Exception as e:
                logger.exception("End session failed: %s", e)
                msg = str(e)
                def _show_err() -> None:
                    from tkinter import messagebox
                    messagebox.showerror("End Session", msg)
                self.after(0, _show_err)
            finally:
                self.after(0, lambda: self._update_buttons_for_session(self._get_session_cb()))

        threading.Thread(target=_run, daemon=True).start()

    def _on_export(self) -> None:
        if self._export_in_progress:
            return
        self._export_in_progress = True
        self._set_buttons_enabled(False)

        def _run() -> None:
            try:
                path = self._export_cb()
                if path:
                    def _show_ok() -> None:
                        from tkinter import messagebox
                        messagebox.showinfo(
                            "Export",
                            f"Attendance exported to:\n{path}",
                        )
                    self.after(0, _show_ok)
            except Exception as e:
                logger.exception("Export failed: %s", e)
                msg = str(e)
                def _show_err() -> None:
                    from tkinter import messagebox
                    messagebox.showerror("Export", msg)
                self.after(0, _show_err)
            finally:
                def _reset() -> None:
                    self._export_in_progress = False
                    self._update_buttons_for_session(self._get_session_cb())
                self.after(0, _reset)

        threading.Thread(target=_run, daemon=True).start()
