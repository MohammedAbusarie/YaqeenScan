"""Temporary disabling of NetBIOS over TCP/IP and LLMNR (Windows)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import winreg

from core.config import (
    LLMNR_DISABLE_VALUE,
    LLMNR_ENABLE_MULTICAST_VALUE_NAME,
    LLMNR_POLICY_REG_PATH,
    NETBIOS_INTERFACES_REG_PATH,
    NETBIOS_INTERFACE_PREFIX,
    NETBIOS_OPTIONS_DISABLE_VALUE,
    NETBIOS_OPTIONS_VALUE_NAME,
)
from core.exceptions import YaqeenError

logger = logging.getLogger(__name__)


class NameResolutionError(YaqeenError):
    """Raised when name-resolution hardening operations fail."""


@dataclass(frozen=True)
class RegistryDwordSnapshot:
    key_path: str
    value_name: str
    existed: bool
    value: int | None


@dataclass(frozen=True)
class NameResolutionSnapshot:
    netbios: tuple[RegistryDwordSnapshot, ...]
    llmnr: RegistryDwordSnapshot


def _enum_subkeys(key: winreg.HKEYType) -> list[str]:
    names: list[str] = []
    idx = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, idx))
            idx += 1
        except OSError:
            break
    return names


def _read_dword(root: int, key_path: str, value_name: str) -> RegistryDwordSnapshot:
    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ) as key:
            try:
                value, reg_type = winreg.QueryValueEx(key, value_name)
                if reg_type != winreg.REG_DWORD:
                    raise NameResolutionError(
                        f"Registry value is not REG_DWORD: {key_path}\\{value_name}"
                    )
                return RegistryDwordSnapshot(
                    key_path=key_path,
                    value_name=value_name,
                    existed=True,
                    value=int(value),
                )
            except FileNotFoundError:
                return RegistryDwordSnapshot(
                    key_path=key_path, value_name=value_name, existed=False, value=None
                )
    except FileNotFoundError:
        return RegistryDwordSnapshot(
            key_path=key_path, value_name=value_name, existed=False, value=None
        )
    except PermissionError as e:
        raise NameResolutionError(f"Registry permission denied: {key_path}") from e
    except OSError as e:
        raise NameResolutionError(f"Registry read failed: {key_path}") from e


def _write_dword(root: int, key_path: str, value_name: str, value: int) -> None:
    try:
        with winreg.CreateKeyEx(root, key_path, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, int(value))
    except PermissionError as e:
        raise NameResolutionError(f"Registry permission denied: {key_path}") from e
    except OSError as e:
        raise NameResolutionError(f"Registry write failed: {key_path}") from e


def _delete_value(root: int, key_path: str, value_name: str) -> None:
    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                return
    except FileNotFoundError:
        return
    except PermissionError as e:
        raise NameResolutionError(f"Registry permission denied: {key_path}") from e
    except OSError as e:
        raise NameResolutionError(f"Registry delete failed: {key_path}") from e


def _iter_netbios_interface_key_paths() -> Iterable[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, NETBIOS_INTERFACES_REG_PATH, 0, winreg.KEY_READ) as k:
            for name in _enum_subkeys(k):
                if name.startswith(NETBIOS_INTERFACE_PREFIX):
                    yield f"{NETBIOS_INTERFACES_REG_PATH}\\{name}"
    except FileNotFoundError:
        return
    except PermissionError as e:
        raise NameResolutionError(
            f"Registry permission denied: {NETBIOS_INTERFACES_REG_PATH}"
        ) from e
    except OSError as e:
        raise NameResolutionError(
            f"Registry enumeration failed: {NETBIOS_INTERFACES_REG_PATH}"
        ) from e


def apply_disable_netbios_llmnr() -> NameResolutionSnapshot:
    """Disable NetBIOS and LLMNR temporarily and return a restore snapshot."""
    netbios_snaps: list[RegistryDwordSnapshot] = []
    changed_netbios = 0
    for key_path in _iter_netbios_interface_key_paths():
        snap = _read_dword(
            winreg.HKEY_LOCAL_MACHINE, key_path, NETBIOS_OPTIONS_VALUE_NAME
        )
        netbios_snaps.append(snap)
        if snap.value != NETBIOS_OPTIONS_DISABLE_VALUE:
            _write_dword(
                winreg.HKEY_LOCAL_MACHINE,
                key_path,
                NETBIOS_OPTIONS_VALUE_NAME,
                NETBIOS_OPTIONS_DISABLE_VALUE,
            )
            changed_netbios += 1
    logger.info("NetBIOS disabled: interfaces_changed=%s", changed_netbios)

    llmnr_snap = _read_dword(
        winreg.HKEY_LOCAL_MACHINE, LLMNR_POLICY_REG_PATH, LLMNR_ENABLE_MULTICAST_VALUE_NAME
    )
    if llmnr_snap.value != LLMNR_DISABLE_VALUE:
        _write_dword(
            winreg.HKEY_LOCAL_MACHINE,
            LLMNR_POLICY_REG_PATH,
            LLMNR_ENABLE_MULTICAST_VALUE_NAME,
            LLMNR_DISABLE_VALUE,
        )
    logger.info(
        "LLMNR disabled: key=%s value_name=%s",
        LLMNR_POLICY_REG_PATH,
        LLMNR_ENABLE_MULTICAST_VALUE_NAME,
    )

    return NameResolutionSnapshot(netbios=tuple(netbios_snaps), llmnr=llmnr_snap)


def revert_disable_netbios_llmnr(snapshot: NameResolutionSnapshot) -> None:
    """Restore NetBIOS and LLMNR settings from snapshot (best effort)."""
    restored_netbios = 0
    for snap in snapshot.netbios:
        try:
            if snap.existed and snap.value is not None:
                _write_dword(
                    winreg.HKEY_LOCAL_MACHINE, snap.key_path, snap.value_name, snap.value
                )
            else:
                _delete_value(winreg.HKEY_LOCAL_MACHINE, snap.key_path, snap.value_name)
            restored_netbios += 1
        except NameResolutionError as e:
            logger.warning(
                "NetBIOS restore failed: key=%s value=%s err=%s",
                snap.key_path,
                snap.value_name,
                e,
                exc_info=True,
            )
    logger.info("NetBIOS restore complete: interface_keys=%s", restored_netbios)

    try:
        if snapshot.llmnr.existed and snapshot.llmnr.value is not None:
            _write_dword(
                winreg.HKEY_LOCAL_MACHINE,
                snapshot.llmnr.key_path,
                snapshot.llmnr.value_name,
                snapshot.llmnr.value,
            )
        else:
            _delete_value(
                winreg.HKEY_LOCAL_MACHINE,
                snapshot.llmnr.key_path,
                snapshot.llmnr.value_name,
            )
        logger.info("LLMNR restore complete: key=%s", snapshot.llmnr.key_path)
    except NameResolutionError as e:
        logger.warning("LLMNR restore failed: %s", e, exc_info=True)

