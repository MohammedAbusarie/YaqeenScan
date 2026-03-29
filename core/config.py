"""Centralized configuration constants for YaqeenScan."""

import os


DB_PATH: str = os.path.join(".", "data", "yaqeen.db")

DATA_DIR: str = os.path.join(".", "data")

HOTSPOT_SSID: str = "YaqeenScan"
HOTSPOT_PASSWORD: str = "yaqeen2024"

TOKEN_ROTATION_SECONDS: int = 100

TOKEN_BYTES: int = 16

SERVER_HOST: str = "0.0.0.0"
SERVER_PORT: int = 8080
SERVER_RANDOM_PORT_MIN: int = 49152
SERVER_RANDOM_PORT_MAX: int = 65535
SERVER_RANDOM_PORT_RETRIES: int = 20

QR_REFRESH_MS: int = TOKEN_ROTATION_SECONDS * 1000

ATTENDANCE_POLL_MS: int = 2000

MAX_STUDENT_ID_LENGTH: int = 20
MAX_STUDENT_NAME_LENGTH: int = 100

STUDENT_ID_REGEX: str = r"^[a-zA-Z0-9]{1,20}$"
STUDENT_NAME_REGEX: str = r"^[a-zA-Z\u00C0-\u024F\u0400-\u04FF\u0600-\u06FF\u4E00-\u9FFF\s\-]{1,100}$"

RATE_LIMIT_MAX_REQUESTS: int = 5
RATE_LIMIT_WINDOW_SECONDS: int = 60

FIREWALL_RULE_PREFIX: str = "YaqeenScan Session Allow"

ICS_SERVICE_NAME: str = "SharedAccess"

NETBIOS_INTERFACES_REG_PATH: str = r"SYSTEM\CurrentControlSet\Services\NetBT\Parameters\Interfaces"
NETBIOS_INTERFACE_PREFIX: str = "Tcpip_"
NETBIOS_OPTIONS_VALUE_NAME: str = "NetbiosOptions"
NETBIOS_OPTIONS_DISABLE_VALUE: int = 2

LLMNR_POLICY_REG_PATH: str = r"SOFTWARE\Policies\Microsoft\Windows NT\DNSClient"
LLMNR_ENABLE_MULTICAST_VALUE_NAME: str = "EnableMulticast"
LLMNR_DISABLE_VALUE: int = 0

FLASK_SECRET_KEY: str = os.environ.get("YAQEEN_FLASK_SECRET") or __import__("secrets").token_hex(32)

COOKIE_SUBMITTED_NAME: str = "yaqeen_submitted"
COOKIE_MAX_AGE_SECONDS: int = 86400 * 7

EXPORT_DIR: str = os.path.join(".", "exports")

LOG_FILE: str = os.path.join(".", "data", "yaqeen.log")
LOG_LEVEL: str = "DEBUG"

APP_TITLE: str = "YaqeenScan - Engineered by Mohammed Abusarie"
APP_VERSION: str = "1.0"
STATUS_BAR_RIGHT: str = "Egyptian Chinese University non official tool"
FOOTER_TEXT: str = f"Engineered by Mohammed Abusarie \u00b7 YaqeenScan v{APP_VERSION}"

THEME_BG_PRIMARY: str = "#0F0F0F"
THEME_BG_CARD: str = "#1A1A1E"
THEME_BG_ELEVATED: str = "#252529"
THEME_ACCENT: str = "#C41E3A"
THEME_ACCENT_HOVER: str = "#D9264A"
THEME_TEXT_PRIMARY: str = "#F5F5F5"
THEME_TEXT_SECONDARY: str = "#A0A0A6"
THEME_SUCCESS: str = "#2ECC71"
THEME_ERROR: str = "#E74C3C"
THEME_BORDER: str = "#2A2A2E"

