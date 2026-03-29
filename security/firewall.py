"""Temporary Windows Firewall lockdown for a session."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

from core.config import FIREWALL_RULE_PREFIX
from core.exceptions import YaqeenError

logger = logging.getLogger(__name__)


class FirewallError(YaqeenError):
    """Raised when firewall lockdown operations fail."""


@dataclass(frozen=True)
class FirewallProfileSnapshot:
    name: str
    enabled: bool
    default_inbound_action: str
    default_outbound_action: str


@dataclass(frozen=True)
class FirewallSnapshot:
    profiles: tuple[FirewallProfileSnapshot, ...]
    allow_rule_name: str


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
        raise FirewallError("PowerShell not found") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        msg = stderr or stdout or "PowerShell command failed"
        raise FirewallError(msg) from e
    except OSError as e:
        raise FirewallError(f"OS error running PowerShell: {e}") from e


def _get_profiles_snapshot() -> tuple[FirewallProfileSnapshot, ...]:
    raw = _run_powershell(
        "Get-NetFirewallProfile | "
        "Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction | "
        "ConvertTo-Json -Compress"
    )
    if not raw:
        raise FirewallError("Empty firewall profile snapshot")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FirewallError("Could not parse firewall profile snapshot JSON") from e

    items = data if isinstance(data, list) else [data]
    profiles: list[FirewallProfileSnapshot] = []
    for item in items:
        profiles.append(
            FirewallProfileSnapshot(
                name=str(item.get("Name", "")),
                enabled=bool(item.get("Enabled", False)),
                default_inbound_action=str(item.get("DefaultInboundAction", "")),
                default_outbound_action=str(item.get("DefaultOutboundAction", "")),
            )
        )
    profiles = [p for p in profiles if p.name]
    if not profiles:
        raise FirewallError("No firewall profiles found in snapshot")
    return tuple(profiles)


def apply_lockdown(port: int) -> FirewallSnapshot:
    """Apply temporary firewall lockdown allowing only the given TCP port.

    Returns a snapshot to be used with revert_lockdown().
    """
    if port <= 0 or port > 65535:
        raise FirewallError(f"Invalid port: {port}")

    profiles = _get_profiles_snapshot()
    allow_rule_name = f"{FIREWALL_RULE_PREFIX} {port}"

    _run_powershell(
        "Set-NetFirewallProfile -Profile Domain,Public,Private "
        "-Enabled True -DefaultInboundAction Block -DefaultOutboundAction Allow"
    )
    logger.info(
        "Firewall lockdown applied: inbound=Block outbound=Allow profiles=%s",
        ",".join(p.name for p in profiles),
    )

    _run_powershell(
        f"New-NetFirewallRule -DisplayName {json.dumps(allow_rule_name)} "
        f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort {int(port)} "
        "-Profile Any -EdgeTraversalPolicy Block"
    )
    logger.info("Firewall allow rule created: name=%s port=%s", allow_rule_name, port)

    return FirewallSnapshot(profiles=profiles, allow_rule_name=allow_rule_name)


def revert_lockdown(snapshot: FirewallSnapshot) -> None:
    """Revert firewall lockdown to the given snapshot (best effort)."""
    removed = False
    try:
        _run_powershell(
            f"Get-NetFirewallRule -DisplayName {json.dumps(snapshot.allow_rule_name)} "
            "-ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue"
        )
        removed = True
    except FirewallError as primary_err:
        logger.warning(
            "Firewall allow rule removal via PowerShell failed: %s", primary_err, exc_info=True
        )
        try:
            _run_powershell(
                f'netsh advfirewall firewall delete rule name={json.dumps(snapshot.allow_rule_name)}'
            )
            removed = True
        except FirewallError as fallback_err:
            logger.warning(
                "Firewall allow rule removal via netsh failed: %s", fallback_err, exc_info=True
            )
    if removed:
        logger.info("Firewall allow rule removed: name=%s", snapshot.allow_rule_name)
    for p in snapshot.profiles:
        try:
            enabled = "$true" if p.enabled else "$false"
            _run_powershell(
                "Set-NetFirewallProfile "
                f"-Profile {json.dumps(p.name)} "
                f"-Enabled {enabled} "
                f"-DefaultInboundAction {json.dumps(p.default_inbound_action)} "
                f"-DefaultOutboundAction {json.dumps(p.default_outbound_action)}"
            )
        except FirewallError as e:
            logger.warning(
                "Firewall profile restore failed: profile=%s err=%s", p.name, e, exc_info=True
            )
    logger.info(
        "Firewall lockdown reverted: profiles=%s",
        ",".join(p.name for p in snapshot.profiles),
    )

