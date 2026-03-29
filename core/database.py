"""SQLite database manager for YaqeenScan.

All SQL queries live exclusively in this module.
No other module may construct or execute SQL strings.
"""

import logging
import os
import sqlite3
from datetime import datetime

from core.exceptions import YaqeenError
from core.models import AttendanceRecord, BlockedDevice, Session

logger = logging.getLogger(__name__)


class DatabaseError(YaqeenError):
    """Raised when a database operation fails."""

    pass


class RecordNotFoundError(YaqeenError):
    """Raised when a requested record does not exist."""

    pass


_SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);
"""

_SCHEMA_ATTENDANCE = """
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    student_id TEXT NOT NULL,
    student_name TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    fingerprint_hash TEXT NOT NULL,
    token_used TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""

_SCHEMA_BLOCKED_DEVICES = """
CREATE TABLE IF NOT EXISTS blocked_devices (
    session_id INTEGER NOT NULL,
    mac_address TEXT NOT NULL,
    fingerprint_hash TEXT NOT NULL,
    blocked_at TEXT NOT NULL,
    PRIMARY KEY (session_id, mac_address, fingerprint_hash),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


def init_db(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    """Initialize the database and create tables if they do not exist.

    Creates the parent directory of db_path if missing. Returns an open
    connection. Caller is responsible for closing it.

    Args:
        db_path: Path to the SQLite database file.
        check_same_thread: If False, allow connection use from multiple threads
            (caller must serialize access with a lock).

    Returns:
        An open sqlite3.Connection.

    Raises:
        DatabaseError: If directory creation or database initialization fails.
    """
    try:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    except OSError as e:
        logger.exception("Failed to create database directory: %s", parent)
        raise DatabaseError(f"Cannot create database directory: {e}") from e
    try:
        conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA_SESSIONS + _SCHEMA_ATTENDANCE + _SCHEMA_BLOCKED_DEVICES)
        conn.commit()
        return conn
    except sqlite3.Error as e:
        logger.exception("Failed to initialize database at %s", db_path)
        raise DatabaseError(f"Database initialization failed: {e}") from e


def create_session(conn: sqlite3.Connection, course_name: str) -> Session:
    """Create a new attendance session.

    Args:
        conn: Active database connection.
        course_name: Display name for the course/session.

    Returns:
        Session instance with id, course_name, start_time set; end_time empty,
        is_active True.

    Raises:
        DatabaseError: If the insert fails.
    """
    start_time = datetime.now().isoformat()
    try:
        cursor = conn.execute(
            "INSERT INTO sessions (course_name, start_time, end_time, is_active) VALUES (?, ?, '', 1)",
            (course_name, start_time),
        )
        conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise DatabaseError("create_session: lastrowid is None")
        return Session(
            id=row_id,
            course_name=course_name,
            start_time=start_time,
            end_time="",
            is_active=True,
        )
    except sqlite3.Error as e:
        logger.exception("Failed to create session for course %s", course_name)
        raise DatabaseError(f"Create session failed: {e}") from e


def end_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Mark a session as ended.

    Sets end_time to current time and is_active to 0.

    Args:
        conn: Active database connection.
        session_id: Primary key of the session.

    Raises:
        DatabaseError: If the update fails.
    """
    end_time = datetime.now().isoformat()
    try:
        conn.execute(
            "UPDATE sessions SET end_time = ?, is_active = 0 WHERE id = ?",
            (end_time, session_id),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.exception("Failed to end session %s", session_id)
        raise DatabaseError(f"End session failed: {e}") from e


def add_attendance(conn: sqlite3.Connection, record: AttendanceRecord) -> None:
    """Insert a new attendance record.

    Args:
        conn: Active database connection.
        record: AttendanceRecord with all fields set (id may be 0; it is ignored).

    Raises:
        DatabaseError: If the insert fails.
    """
    try:
        conn.execute(
            """INSERT INTO attendance (
                session_id, student_id, student_name, mac_address,
                fingerprint_hash, token_used, submitted_at, ip_address
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.session_id,
                record.student_id,
                record.student_name,
                record.mac_address,
                record.fingerprint_hash,
                record.token_used,
                record.submitted_at,
                record.ip_address,
            ),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.exception("Failed to add attendance for session %s student %s", record.session_id, record.student_id)
        raise DatabaseError(f"Add attendance failed: {e}") from e


def is_device_blocked(
    conn: sqlite3.Connection, session_id: int, mac: str, fingerprint: str
) -> bool:
    """Check if a device is blocked for a given session.

    Args:
        conn: Active database connection.
        session_id: Session primary key.
        mac: MAC address string.
        fingerprint: Fingerprint hash string.

    Returns:
        True if the (mac, fingerprint) pair is blocked for this session.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        cursor = conn.execute(
            """SELECT 1 FROM blocked_devices
             WHERE session_id = ? AND mac_address = ? AND fingerprint_hash = ?
             LIMIT 1""",
            (session_id, mac, fingerprint),
        )
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.exception("Failed to check device block for session %s", session_id)
        raise DatabaseError(f"Device block check failed: {e}") from e


def block_device(
    conn: sqlite3.Connection, mac: str, fingerprint: str, session_id: int
) -> None:
    """Block a device from resubmitting in a session.

    Args:
        conn: Active database connection.
        mac: MAC address string.
        fingerprint: Fingerprint hash string.
        session_id: Session primary key.

    Raises:
        DatabaseError: If the insert fails.
    """
    blocked_at = datetime.now().isoformat()
    try:
        conn.execute(
            """INSERT INTO blocked_devices (session_id, mac_address, fingerprint_hash, blocked_at)
             VALUES (?, ?, ?, ?)""",
            (session_id, mac, fingerprint, blocked_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
    except sqlite3.Error as e:
        logger.exception("Failed to block device for session %s", session_id)
        raise DatabaseError(f"Block device failed: {e}") from e


def get_session_attendance(
    conn: sqlite3.Connection, session_id: int
) -> list[AttendanceRecord]:
    """Retrieve all attendance records for a session, ordered by submitted_at.

    Args:
        conn: Active database connection.
        session_id: Session primary key.

    Returns:
        List of AttendanceRecord instances (id and all columns populated).

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        cursor = conn.execute(
            """SELECT id, session_id, student_id, student_name, mac_address,
                      fingerprint_hash, token_used, submitted_at, ip_address
               FROM attendance WHERE session_id = ? ORDER BY submitted_at""",
            (session_id,),
        )
        return [
            AttendanceRecord(
                id=row[0],
                session_id=row[1],
                student_id=row[2],
                student_name=row[3],
                mac_address=row[4],
                fingerprint_hash=row[5],
                token_used=row[6],
                submitted_at=row[7],
                ip_address=row[8],
            )
            for row in cursor.fetchall()
        ]
    except sqlite3.Error as e:
        logger.exception("Failed to get attendance for session %s", session_id)
        raise DatabaseError(f"Get session attendance failed: {e}") from e


def is_student_id_submitted(
    conn: sqlite3.Connection, session_id: int, student_id: str
) -> bool:
    """Check if a student ID has already submitted for a session.

    Args:
        conn: Active database connection.
        session_id: Session primary key.
        student_id: Student identifier string.

    Returns:
        True if at least one attendance record exists for this session and student_id.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        cursor = conn.execute(
            "SELECT 1 FROM attendance WHERE session_id = ? AND student_id = ? LIMIT 1",
            (session_id, student_id),
        )
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.exception("Failed to check student submission for session %s", session_id)
        raise DatabaseError(f"Student submission check failed: {e}") from e


def get_active_session(conn: sqlite3.Connection) -> Session | None:
    """Return the single active session, if any.

    Args:
        conn: Active database connection.

    Returns:
        Session instance for the active session, or None if no session is active.

    Raises:
        DatabaseError: If the query fails.
    """
    try:
        cursor = conn.execute(
            "SELECT id, course_name, start_time, end_time, is_active FROM sessions WHERE is_active = 1 LIMIT 1",
            (),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Session(
            id=row[0],
            course_name=row[1],
            start_time=row[2],
            end_time=row[3],
            is_active=bool(row[4]),
        )
    except sqlite3.Error as e:
        logger.exception("Failed to get active session")
        raise DatabaseError(f"Get active session failed: {e}") from e
