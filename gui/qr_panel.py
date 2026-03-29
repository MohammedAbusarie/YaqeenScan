"""QR code display widget for the professor-facing GUI."""

import logging
import os
from typing import Callable

import customtkinter as ctk
import qrcode
from PIL import Image

from core.config import DATA_DIR, THEME_ACCENT, THEME_BG_ELEVATED, THEME_TEXT_PRIMARY, THEME_TEXT_SECONDARY

logger = logging.getLogger(__name__)

_QR_CACHE_DIR = os.path.join(DATA_DIR, "qr_cache")
_QR_IMAGE_FILENAME = "yaqeen_qr.png"

_NO_SESSION_LINES = "Start a session to display the QR code."

_NO_HOTSPOT_LINES = (
    "YaqeenScan Hotspot unavailable on this adapter.\n\n"
    "To connect students:\n"
    "1. Turn on your phone's Mobile Hotspot\n"
    "2. Connect this laptop to that hotspot\n"
    "3. Have students join the same hotspot\n"
    "4. The QR code will appear automatically."
)


def _ensure_qr_cache_dir() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(_QR_CACHE_DIR, exist_ok=True)
    return _QR_CACHE_DIR


def _url_to_qr_image_path(url: str) -> str | None:
    """Generate a QR code image from URL and return path to saved file."""
    if not url or not url.strip():
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(url.strip())
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        if not isinstance(img, Image.Image):
            img = img.convert("RGB") if hasattr(img, "convert") else Image.new("RGB", (200, 200), "white")
        cache_dir = _ensure_qr_cache_dir()
        path = os.path.join(cache_dir, _QR_IMAGE_FILENAME)
        img.save(path, format="PNG")
        return path
    except OSError as e:
        logger.exception("Failed to save QR image: %s", e)
        return None
    except Exception as e:
        logger.exception("Failed to generate QR code: %s", e)
        return None


class QRPanel(ctk.CTkFrame):
    """Displays an auto-refreshing QR code that encodes the attendance URL.

    Shows the QR image, the URL as selectable text below it, and a network
    mode badge (YaqeenScan Hotspot / LAN Fallback). When no session is active
    or no URL is available, shows a contextual instruction message instead.
    """

    def __init__(self, master: ctk.CTk, on_qr_click_cb: Callable[[], None] | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._last_url: str = ""
        self._session_active: bool = False
        self._last_hotspot_active: bool = False
        self._on_qr_click_cb = on_qr_click_cb

        self._placeholder = ctk.CTkLabel(
            self,
            text=_NO_SESSION_LINES,
            text_color=THEME_TEXT_SECONDARY,
            font=("", 16),
            wraplength=280,
            justify="center",
        )

        self._network_badge = ctk.CTkLabel(
            self,
            text="",
            font=("", 13),
            height=26,
            corner_radius=4,
        )

        self._image_label = ctk.CTkLabel(self, text="", cursor="hand2")
        if on_qr_click_cb is not None:
            self._image_label.bind("<Button-1>", self._on_image_click)

        self._url_label = ctk.CTkLabel(
            self,
            text="",
            font=("Consolas", 13),
            text_color=THEME_TEXT_SECONDARY,
            wraplength=300,
            justify="center",
            cursor="hand2",
        )
        if on_qr_click_cb is not None:
            self._url_label.bind("<Button-1>", self._on_image_click)

        self._placeholder.pack(expand=True, fill="both", padx=20, pady=20)
        self.bind("<Configure>", self._on_configure)

    def _on_image_click(self, event) -> None:
        if self._session_active and self._on_qr_click_cb is not None:
            self._on_qr_click_cb()

    def _on_configure(self, event) -> None:
        if self._last_url and self._session_active:
            self.update_qr(
                self._last_url,
                hotspot_active=self._last_hotspot_active,
                session_active=True,
                force_refresh=True,
            )

    def _qr_display_size(self) -> int:
        w = max(0, self.winfo_width() - 32)
        h = max(0, self.winfo_height() - 32)
        raw = min(w, h)
        if raw < 200:
            return 260
        return min(raw, 500)

    def update_qr(
        self,
        url: str,
        hotspot_active: bool = False,
        session_active: bool = False,
        force_refresh: bool = False,
    ) -> None:
        """Render the QR code for url, or show the appropriate instruction screen.

        Args:
            url: Full attendance URL. Empty string when no URL is available.
            hotspot_active: True when the YaqeenScan hotspot is running.
            session_active: True when an attendance session is in progress.
            force_refresh: If True, refresh the display even when url unchanged (e.g. on resize).
        """
        self._session_active = session_active
        self._last_hotspot_active = hotspot_active

        if not url or not url.strip():
            self._show_placeholder(session_active=session_active, hotspot_active=hotspot_active)
            return

        if url == self._last_url and not force_refresh:
            return

        path = _url_to_qr_image_path(url)
        if path is None:
            self._show_placeholder(session_active=session_active, hotspot_active=hotspot_active)
            return

        try:
            size = self._qr_display_size()
            pil_img = Image.open(path).convert("RGB")
            image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(size, size))
            self._image_label.configure(image=image)
            self._image_label.image = image
            self._url_label.configure(text=url)
            self._last_url = url

            badge_text, badge_fg, badge_text_color = _badge_for_mode(hotspot_active)
            self._network_badge.configure(
                text=badge_text,
                fg_color=badge_fg,
                text_color=badge_text_color,
            )

            self._placeholder.pack_forget()
            self._network_badge.pack(pady=(8, 0))
            self._image_label.pack(pady=(4, 0), fill="both", expand=True)
            self._url_label.pack(pady=(4, 8), padx=8)
        except OSError as e:
            logger.exception("Failed to open QR image file: %s", e)
            self._show_placeholder(session_active=session_active, hotspot_active=hotspot_active)
        except Exception as e:
            logger.exception("Failed to display QR image: %s", e)
            self._show_placeholder(session_active=session_active, hotspot_active=hotspot_active)

    def _show_placeholder(self, session_active: bool, hotspot_active: bool) -> None:
        self._image_label.pack_forget()
        self._url_label.pack_forget()
        self._network_badge.pack_forget()
        self._last_url = ""

        if not session_active:
            msg = _NO_SESSION_LINES
        elif not hotspot_active:
            msg = _NO_HOTSPOT_LINES
        else:
            msg = "Waiting for network…"

        self._placeholder.configure(text=msg)
        self._placeholder.pack(expand=True, fill="both", padx=20, pady=20)


def _badge_for_mode(hotspot_active: bool) -> tuple[str, str, str]:
    """Return (label, bg_color, text_color) for the network mode badge."""
    if hotspot_active:
        return "  YaqeenScan Hotspot  ", THEME_ACCENT, "#FFFFFF"
    return "  LAN Fallback — connect laptop & students to same network  ", THEME_BG_ELEVATED, THEME_TEXT_SECONDARY
