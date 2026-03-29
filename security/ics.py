"""Temporary stopping/restoring of Windows Internet Connection Sharing (ICS)."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

from core.config import ICS_SERVICE_NAME
from core.exceptions import YaqeenError

logger = logging.getLogger(__name__)


class ICSError(YaqeenError):
    """Raised when ICS hardening operations fail."""


@dataclass(frozen=True)
class ICSSnapshot:
    service_name: str
    service_exists: bool
    was_running: bool


def _run_powershell(command: str) -> str:
    """Run a PowerShell command and return stdout."""
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return (proc.stdout or "").strip()
    except FileNotFoundError as e:
        raise ICSError("PowerShell not found") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        msg = stderr or stdout or "PowerShell command failed"
        raise ICSError(msg) from e
    except OSError as e:
        raise ICSError(f"OS error running PowerShell: {e}") from e


def _service_status(service_name: str) -> tuple[bool, bool]:
    """Return (service_exists, is_running) for a Windows service."""
    raw = _run_powershell(
        f"Get-Service -Name {json.dumps(service_name)} -ErrorAction SilentlyContinue | "
        "Select-Object Status | ConvertTo-Json -Compress"
    )
    if not raw:
        return False, False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ICSError("Could not parse service status JSON") from e
    status = str((data or {}).get("Status", "")).strip().lower()
    return True, status == "running"


def apply_stop_ics() -> ICSSnapshot:
    """Stop ICS (SharedAccess) during a session and return a restore snapshot."""
    service_exists, is_running = _service_status(ICS_SERVICE_NAME)
    snap = ICSSnapshot(
        service_name=ICS_SERVICE_NAME, service_exists=service_exists, was_running=is_running
    )
    if not service_exists:
        logger.info("ICS not present: service=%s", ICS_SERVICE_NAME)
        return snap
    if not is_running:
        logger.info("ICS already stopped: service=%s", ICS_SERVICE_NAME)
        return snap

    _run_powershell(
        f"Stop-Service -Name {json.dumps(ICS_SERVICE_NAME)} -Force -ErrorAction Stop"
    )
    logger.info("ICS stopped for session: service=%s", ICS_SERVICE_NAME)
    return snap


def revert_restore_ics(snapshot: ICSSnapshot) -> None:
    """Restore ICS to its pre-session running state (best effort)."""
    if not snapshot.service_exists:
        logger.info("ICS restore skipped (not present): service=%s", snapshot.service_name)
        return
    if not snapshot.was_running:
        logger.info("ICS restore skipped (was not running): service=%s", snapshot.service_name)
        return

    try:
        _run_powershell(
            f"Start-Service -Name {json.dumps(snapshot.service_name)} -ErrorAction Stop"
        )
        logger.info("ICS restored (started): service=%s", snapshot.service_name)
    except ICSError as e:
        logger.warning("ICS restore failed: service=%s err=%s", snapshot.service_name, e, exc_info=True)

