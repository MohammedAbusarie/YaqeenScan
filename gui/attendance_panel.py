"""Live attendance list panel for the professor-facing GUI."""

import customtkinter as ctk

from core.config import THEME_TEXT_PRIMARY, THEME_TEXT_SECONDARY
from core.models import AttendanceRecord


def _format_submitted_time(iso_str: str) -> str:
    """Return a short time string from an ISO datetime string."""
    if not iso_str:
        return ""
    try:
        if "T" in iso_str:
            part = iso_str.split("T")[1]
            return part[:8] if len(part) >= 8 else part
        return iso_str[:19] if len(iso_str) >= 19 else iso_str
    except Exception:
        return iso_str


class AttendancePanel(ctk.CTkFrame):
    """Displays a scrollable list of submitted attendance records.

    Polling is performed by the parent; this panel only rebuilds
    the list when refresh is called.
    """

    def __init__(self, master: ctk.CTk, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._scroll = ctk.CTkScrollableFrame(self)
        self._scroll.pack(fill="both", expand=True)
        self._header = self._make_header_row()
        self._header.pack(fill="x", padx=4, pady=(0, 4))
        self._rows: list[ctk.CTkFrame] = []

    def _make_header_row(self) -> ctk.CTkFrame:
        """Build the table header row with column titles."""
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        num_label = ctk.CTkLabel(
            row,
            text="#",
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="e",
            width=36,
        )
        id_label = ctk.CTkLabel(
            row,
            text="Student ID",
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="w",
            width=120,
        )
        name_label = ctk.CTkLabel(
            row,
            text="Name",
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="w",
        )
        time_label = ctk.CTkLabel(
            row,
            text="Time",
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="e",
            width=80,
        )
        num_label.pack(side="left", padx=(4, 4), pady=4)
        id_label.pack(side="left", padx=(0, 8), pady=4)
        name_label.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        time_label.pack(side="right", padx=4, pady=4)
        return row

    def refresh(self, records: list[AttendanceRecord]) -> None:
        """Rebuild the attendance list display from the given records."""
        for r in self._rows:
            r.destroy()
        self._rows.clear()
        for idx, rec in enumerate(records, start=1):
            row = self._make_row(rec, idx)
            row.pack(fill="x", padx=4, pady=2)
            self._rows.append(row)

    def _make_row(self, record: AttendanceRecord, row_number: int) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        num_label = ctk.CTkLabel(
            row,
            text=str(row_number),
            font=("", 14),
            text_color=THEME_TEXT_SECONDARY,
            anchor="e",
            width=36,
        )
        id_label = ctk.CTkLabel(
            row,
            text=record.student_id,
            font=("Consolas", 14),
            text_color=THEME_TEXT_PRIMARY,
            anchor="w",
            width=120,
        )
        name_label = ctk.CTkLabel(
            row,
            text=record.student_name or "—",
            font=("", 14),
            text_color=THEME_TEXT_PRIMARY,
            anchor="w",
        )
        time_label = ctk.CTkLabel(
            row,
            text=_format_submitted_time(record.submitted_at),
            font=("", 13),
            text_color=THEME_TEXT_SECONDARY,
            anchor="e",
            width=80,
        )
        num_label.pack(side="left", padx=(4, 4), pady=4)
        id_label.pack(side="left", padx=(0, 8), pady=4)
        name_label.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        time_label.pack(side="right", padx=4, pady=4)
        return row
