"""WiFi hotspot manager for Windows using netsh commands."""

import logging
import re
import subprocess
from typing import List

from core.exceptions import YaqeenError

logger = logging.getLogger(__name__)


class HotspotError(YaqeenError):
    """Base exception for hotspot operations."""

    pass


class HotspotStartError(HotspotError):
    """Raised when the hotspot fails to start."""

    pass


class HotspotStopError(HotspotError):
    """Raised when the hotspot fails to stop."""

    pass


def _run_netsh(args: List[str], error_class: type[HotspotError]) -> subprocess.CompletedProcess[str]:
    """Run netsh with the given arguments. Re-raises on failure as error_class."""
    cmd = ["netsh", "wlan"] + args
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except subprocess.TimeoutExpired as e:
        logger.exception("netsh command timed out: %s", cmd)
        raise error_class(f"Command timed out: {cmd}") from e
    except subprocess.CalledProcessError as e:
        logger.exception("netsh command failed: %s stderr=%s", cmd, e.stderr)
        raise error_class(f"Command failed: {e.stderr or e.stdout or str(e)}") from e
    except OSError as e:
        logger.exception("Failed to run netsh: %s", cmd)
        raise error_class(f"Cannot run netsh: {e}") from e


def _parse_hosted_ip_from_ipconfig(stdout: str) -> str | None:
    """Parse ipconfig output for the hosted network adapter IPv4 address.

    Looks for adapter blocks containing 'Local Area Connection*' or
    'Wireless Network Connection*' (Windows hosted network) and returns
    the first IPv4 address in that block.
    """
    blocks = re.split(r"\r?\n\r?\n", stdout)
    for block in blocks:
        if "*" not in block and "Local Area Connection" not in block and "Wireless Network Connection" not in block:
            continue
        if "Local Area Connection*" not in block and "Wireless Network Connection*" not in block:
            continue
        match = re.search(r"IPv4\s+Address[.\s]*:\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", block, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


class HotspotManager:
    """Manages a Windows hosted network (WiFi hotspot) via netsh commands.

    Provides start/stop/status operations for the local WiFi hotspot
    that students connect to for attendance submission.
    """

    def start(self, ssid: str, password: str) -> bool:
        """Create and start the hosted network.

        Sets mode=allow, ssid, and key in one set call, then starts the
        hosted network. Password must be at least 8 characters.

        Args:
            ssid: Network name (SSID).
            password: Network key (WPA2).

        Returns:
            True if the hosted network was started successfully.

        Raises:
            HotspotStartError: If netsh set or start fails.
        """
        _run_netsh(
            ["set", "hostednetwork", "mode=allow", f"ssid={ssid}", f"key={password}"],
            HotspotStartError,
        )
        _run_netsh(["start", "hostednetwork"], HotspotStartError)
        return True

    def stop(self) -> bool:
        """Stop the hosted network.

        Returns:
            True if the hosted network was stopped successfully.

        Raises:
            HotspotStopError: If netsh stop fails.
        """
        _run_netsh(["stop", "hostednetwork"], HotspotStopError)
        return True

    def is_running(self) -> bool:
        """Check if the hosted network is currently active.

        Returns:
            True if 'netsh wlan show hostednetwork' reports Status : Started.
        """
        try:
            proc = subprocess.run(
                ["netsh", "wlan", "show", "hostednetwork"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return False
            return "Started" in (proc.stdout or "") and "Status" in (proc.stdout or "")
        except (subprocess.TimeoutExpired, OSError):
            logger.debug("Failed to check hosted network status", exc_info=True)
            return False

    def get_hosted_ip(self) -> str:
        """Return the IP address assigned to the hosted network adapter.

        Parses ipconfig output for the virtual adapter used by the
        hosted network (Local Area Connection* / Wireless Network Connection*).

        Returns:
            IPv4 address string (e.g. '192.168.173.1').

        Raises:
            HotspotError: If the hosted network IP could not be determined.
        """
        try:
            proc = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                raise HotspotError("ipconfig failed")
            out = proc.stdout or ""
        except subprocess.TimeoutExpired as e:
            logger.exception("ipconfig timed out")
            raise HotspotError("ipconfig timed out") from e
        except OSError as e:
            logger.exception("Failed to run ipconfig")
            raise HotspotError(f"Cannot run ipconfig: {e}") from e
        ip = _parse_hosted_ip_from_ipconfig(out)
        if ip is None:
            raise HotspotError("Could not determine hosted network adapter IP from ipconfig")
        return ip
