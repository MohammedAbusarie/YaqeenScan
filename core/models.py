"""Data models for YaqeenScan."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    """Represents a single attendance-taking session."""

    id: int = 0
    course_name: str = ""
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: str = ""
    is_active: bool = True


@dataclass
class AttendanceRecord:
    """Represents a single student attendance submission."""

    id: int = 0
    session_id: int = 0
    student_id: str = ""
    student_name: str = ""
    mac_address: str = ""
    fingerprint_hash: str = ""
    token_used: str = ""
    submitted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    ip_address: str = ""


@dataclass
class BlockedDevice:
    """Represents a device blocked from resubmitting in a session."""

    mac_address: str = ""
    fingerprint_hash: str = ""
    session_id: int = 0
    blocked_at: str = field(default_factory=lambda: datetime.now().isoformat())
