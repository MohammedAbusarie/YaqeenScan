"""ARP table scanner to resolve IP addresses to MAC addresses."""

import logging
import re
import subprocess

from core.exceptions import YaqeenError

logger = logging.getLogger(__name__)


class ARPScanError(YaqeenError):
    """Raised when ARP table scanning or parsing fails."""

    pass


def _normalize_mac(mac: str) -> str:
    """Convert MAC to lowercase with colon separators."""
    cleaned = re.sub(r"[^a-fA-F0-9]", "", mac)
    if len(cleaned) != 12:
        return mac
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2)).lower()


def get_mac_for_ip(ip_address: str) -> str | None:
    """Look up the MAC address for a given IP from the system ARP table.

    Runs 'arp -a' on Windows and parses the output for the given IP.
    Returns None if the IP is not in the ARP table.

    Args:
        ip_address: IPv4 address string (e.g. '192.168.1.5').

    Returns:
        MAC address string with colon separators (e.g. 'aa:bb:cc:dd:ee:ff'),
        or None if not found.

    Raises:
        ARPScanError: If arp command fails or output cannot be parsed.
    """
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            logger.warning("arp -a returned non-zero: %s", proc.stderr or proc.stdout)
            raise ARPScanError(f"arp -a failed: {proc.stderr or proc.stdout or proc.returncode}")
        out = proc.stdout or ""
    except subprocess.TimeoutExpired as e:
        logger.exception("arp -a timed out")
        raise ARPScanError("arp -a timed out") from e
    except OSError as e:
        logger.exception("Failed to run arp")
        raise ARPScanError(f"Cannot run arp: {e}") from e
    ip_pattern = re.escape(ip_address)
    mac_re = re.compile(r"^[0-9a-fA-F]{2}([\-:][0-9a-fA-F]{2}){5}$")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == ip_address and mac_re.match(parts[1].replace("-", ":")):
            return _normalize_mac(parts[1])
    return None
