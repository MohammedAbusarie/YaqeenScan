"""YaqeenScan — Portable QR Attendance System.

Entry point that auto-elevates to admin and orchestrates all subsystems.
"""

import logging
import os
import secrets
import socket
import sys
import threading
import ctypes

from core import config
from core.database import (
    create_session,
    end_session,
    get_active_session,
    get_session_attendance,
    init_db,
)
from core.exceptions import YaqeenError
from core.models import Session
from core.token_manager import TokenManager
from export.exporter import export_csv, export_xlsx, generate_export_filename
from gui.main_window import MainWindow
from network.hotspot import HotspotManager, HotspotStartError
from server.app import create_app
from server.routes import clear_session_ip_submissions
from security.firewall import FirewallSnapshot, apply_lockdown, revert_lockdown
from security.ics import ICSSnapshot, apply_stop_ics, revert_restore_ics
from security.name_resolution import (
    NameResolutionSnapshot,
    apply_disable_netbios_llmnr,
    revert_disable_netbios_llmnr,
)

logger = logging.getLogger(__name__)


def _get_local_ip() -> str:
    """Return a non-loopback IPv4 address for this machine.

    Prefers a locally-resolved interface address; falls back to a short
    UDP connect trick if needed. Returns an empty string if no
    suitable address is available.
    """
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET:
                ip = sockaddr[0]
                if not ip.startswith("127."):
                    return ip
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return ""


def _is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except AttributeError:
        return False


def _elevate() -> None:
    """Re-launch this process with administrator privileges via UAC and exit.

    Passes the project directory as the working directory so all relative
    paths (DB, logs, exports) resolve correctly in the elevated process.
    """
    script = os.path.abspath(sys.argv[0])
    args = " ".join(f'"{a}"' if " " in a else a for a in sys.argv[1:])
    params = f'"{script}"' if not args else f'"{script}" {args}'
    project_dir = os.path.dirname(script)
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, project_dir, 1
        )
    except Exception as e:
        logger.exception("Failed to elevate: %s", e)
    sys.exit(0)


def _setup_logging() -> None:
    """Configure root logger with file and console handlers."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.DEBUG))
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        logger.warning("Could not create log file %s: %s", config.LOG_FILE, e)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    for noisy in ("PIL", "PIL.PngImagePlugin", "PIL.Image", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _run_export_for_session(conn, db_lock, session: Session) -> None:
    """Export attendance for the given session to CSV and XLSX in EXPORT_DIR."""
    with db_lock:
        records = get_session_attendance(conn, session.id)
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    date_str = (session.start_time or "")[:10] or "export"
    csv_path = os.path.join(config.EXPORT_DIR, generate_export_filename(session.course_name, date_str, "csv"))
    xlsx_path = os.path.join(config.EXPORT_DIR, generate_export_filename(session.course_name, date_str, "xlsx"))
    try:
        export_csv(records, csv_path)
        logger.info("Exported CSV: %s", csv_path)
    except YaqeenError as e:
        logger.exception("Export CSV failed: %s", e)
    try:
        export_xlsx(records, xlsx_path)
        logger.info("Exported XLSX: %s", xlsx_path)
    except YaqeenError as e:
        logger.exception("Export XLSX failed: %s", e)


def main() -> None:
    """Application entry point: elevate, wire subsystems, run GUI."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        try:
            os.chdir(exe_dir)
        except OSError:
            pass
        if not _is_admin():
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Please run YaqeenScan as administrator.\n"
                    "Right-click the EXE and choose 'Run as administrator'.",
                    "YaqeenScan",
                    0,
                )
            except Exception:
                pass
            return
    else:
        if not _is_admin():
            _elevate()

    _setup_logging()
    logger.info("YaqeenScan starting")

    # So Windows uses our app icon in the taskbar instead of the Python icon
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YaqeenScan.app.1.0")
    except Exception:
        pass

    db_lock = threading.Lock()
    try:
        conn = init_db(config.DB_PATH, check_same_thread=False)
    except YaqeenError as e:
        logger.exception("Database init failed: %s", e)
        sys.exit(1)

    with db_lock:
        stale = get_active_session(conn)
    if stale is not None:
        logger.warning(
            "Closing stale session '%s' (id=%s) left over from previous run",
            stale.course_name, stale.id,
        )
        with db_lock:
            end_session(conn, stale.id)

    token_manager = TokenManager()
    hotspot = HotspotManager()
    flask_app = create_app(conn, token_manager, config, db_lock=db_lock)

    try:
        from werkzeug.serving import make_server
    except ImportError:
        logger.error("werkzeug not available; install flask dependencies")
        conn.close()
        sys.exit(1)

    server = None
    server_thread = None
    server_host = ""
    server_port = 0
    firewall_snapshot: FirewallSnapshot | None = None
    name_resolution_snapshot: NameResolutionSnapshot | None = None
    ics_snapshot: ICSSnapshot | None = None

    def _choose_bind_ip() -> str:
        if hotspot.is_running():
            try:
                ip = hotspot.get_hosted_ip()
                if ip:
                    return ip
            except YaqeenError as e:
                logger.warning("Hotspot hosted IP unavailable: %s", e, exc_info=True)
        ip = _get_local_ip()
        if ip:
            return ip
        return config.SERVER_HOST

    def _pick_random_high_port() -> int:
        low = int(getattr(config, "SERVER_RANDOM_PORT_MIN", 49152))
        high = int(getattr(config, "SERVER_RANDOM_PORT_MAX", 65535))
        if high < low:
            low, high = high, low
        span = high - low + 1
        return low + secrets.randbelow(span)

    def _start_session_server() -> tuple[str, int]:
        nonlocal server, server_thread, server_host, server_port
        if server is not None:
            return server_host, server_port
        bind_ip = _choose_bind_ip()
        last_err: OSError | None = None
        for _ in range(int(getattr(config, "SERVER_RANDOM_PORT_RETRIES", 20))):
            port = _pick_random_high_port()
            try:
                server = make_server(bind_ip, port, flask_app)
                server_host = bind_ip
                server_port = port
                def _run() -> None:
                    server.serve_forever()
                server_thread = threading.Thread(target=_run, daemon=True)
                server_thread.start()
                logger.info("InvisibleMode server started host=%s port=%s", server_host, server_port)
                return server_host, server_port
            except OSError as e:
                last_err = e
                server = None
                server_thread = None
        msg = f"Could not start server on {bind_ip} with random high ports"
        if last_err is not None:
            raise OSError(msg) from last_err
        raise OSError(msg)

    def _stop_session_server() -> None:
        nonlocal server, server_thread, server_host, server_port
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
            logger.info("InvisibleMode server stopped host=%s port=%s", server_host, server_port)
        except OSError as e:
            logger.warning("Flask shutdown failed: %s", e, exc_info=True)
        finally:
            server = None
            server_thread = None
            server_host = ""
            server_port = 0

    def get_base_url() -> str:
        if server_host and server_port:
            return f"http://{server_host}:{server_port}"
        return ""

    def get_system_status() -> tuple[bool, Session | None]:
        running = hotspot.is_running()
        with db_lock:
            session = get_active_session(conn)
        return running, session

    def start_session_cb(course_name: str) -> tuple[Session | None, bool]:
        """Start a session. Returns (session, hotspot_ok).

        hotspot_ok is False when the WiFi adapter does not support hosted
        networks — the session still starts and uses LAN fallback.
        Returns (None, False) if the DB session could not be created.
        """
        nonlocal firewall_snapshot, name_resolution_snapshot, ics_snapshot
        with db_lock:
            existing = get_active_session(conn)
        if existing is not None:
            logger.warning(
                "Start session ignored — session %s is already active", existing.id
            )
            return existing, hotspot.is_running()

        hotspot_ok = False
        try:
            hotspot.start(config.HOTSPOT_SSID, config.HOTSPOT_PASSWORD)
            hotspot_ok = True
        except HotspotStartError as e:
            logger.warning(
                "Hotspot could not start (session will continue without it): %s", e
            )
        try:
            with db_lock:
                session = create_session(conn, course_name)
            token_manager.start_auto_rotation(config.TOKEN_ROTATION_SECONDS)
            _, port = _start_session_server()
            try:
                firewall_snapshot = apply_lockdown(port)
            except YaqeenError as e:
                logger.warning(
                    "Firewall lockdown failed (continuing without it): %s", e, exc_info=True
                )
            try:
                name_resolution_snapshot = apply_disable_netbios_llmnr()
            except YaqeenError as e:
                logger.warning(
                    "NetBIOS/LLMNR disable failed (continuing without it): %s", e, exc_info=True
                )
            try:
                ics_snapshot = apply_stop_ics()
            except YaqeenError as e:
                logger.warning(
                    "ICS stop failed (continuing without it): %s", e, exc_info=True
                )
            logger.info(
                "Session started: %s (id=%s, hotspot=%s)",
                course_name, session.id, "up" if hotspot_ok else "unavailable",
            )
            return session, hotspot_ok
        except YaqeenError as e:
            logger.exception("Start session failed: %s", e)
            if hotspot_ok:
                try:
                    hotspot.stop()
                except YaqeenError as stop_err:
                    logger.warning("Hotspot stop during rollback failed: %s", stop_err)
            return None, False
        except OSError as e:
            logger.warning("Server start failed: %s", e, exc_info=True)
            try:
                token_manager.stop()
            except Exception as stop_err:
                logger.warning("Token manager stop during rollback failed: %s", stop_err, exc_info=True)
            try:
                with db_lock:
                    end_session(conn, session.id)
            except YaqeenError as end_err:
                logger.warning("End session during rollback failed: %s", end_err, exc_info=True)
            if hotspot_ok:
                try:
                    hotspot.stop()
                except YaqeenError as stop_err:
                    logger.warning("Hotspot stop during rollback failed: %s", stop_err)
            return None, hotspot_ok

    def end_session_cb() -> None:
        nonlocal firewall_snapshot, name_resolution_snapshot, ics_snapshot
        with db_lock:
            session = get_active_session(conn)
        if session is not None:
            token_manager.stop()
            with db_lock:
                end_session(conn, session.id)
            clear_session_ip_submissions(session.id)
            _run_export_for_session(conn, db_lock, session)
            logger.info("Session ended: %s", session.course_name)
        if firewall_snapshot is not None:
            try:
                revert_lockdown(firewall_snapshot)
            except YaqeenError as e:
                logger.warning("Firewall restore failed: %s", e, exc_info=True)
            finally:
                firewall_snapshot = None
        if name_resolution_snapshot is not None:
            try:
                revert_disable_netbios_llmnr(name_resolution_snapshot)
            except YaqeenError as e:
                logger.warning("NetBIOS/LLMNR restore failed: %s", e, exc_info=True)
            finally:
                name_resolution_snapshot = None
        if ics_snapshot is not None:
            try:
                revert_restore_ics(ics_snapshot)
            except YaqeenError as e:
                logger.warning("ICS restore failed: %s", e, exc_info=True)
            finally:
                ics_snapshot = None
        _stop_session_server()
        try:
            if hotspot.is_running():
                hotspot.stop()
        except YaqeenError as e:
            logger.warning("Hotspot stop failed: %s", e)

    def export_cb() -> str:
        with db_lock:
            session = get_active_session(conn)
        if session is None:
            raise YaqeenError("No active session to export. Start a session first.")
        _run_export_for_session(conn, db_lock, session)
        return config.EXPORT_DIR

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "appicon.png")
        if not os.path.isfile(icon_path):
            icon_path = os.path.join(script_dir, "appicon.ico")
        if not os.path.isfile(icon_path):
            icon_path = None
        win = MainWindow(
            db_conn=conn,
            token_manager=token_manager,
            config=config,
            start_session_cb=start_session_cb,
            end_session_cb=end_session_cb,
            get_base_url_cb=get_base_url,
            get_system_status_cb=get_system_status,
            export_cb=export_cb,
            db_lock=db_lock,
            icon_path=icon_path,
        )
    except Exception as e:
        logger.exception("GUI initialization failed: %s", e)
        _stop_session_server()
        token_manager.stop()
        conn.close()
        sys.exit(1)

    def on_closing() -> None:
        nonlocal firewall_snapshot, name_resolution_snapshot, ics_snapshot
        win.on_closing()
        try:
            if hotspot.is_running():
                hotspot.stop()
        except YaqeenError as e:
            logger.warning("Hotspot stop: %s", e)
        if firewall_snapshot is not None:
            try:
                revert_lockdown(firewall_snapshot)
            except YaqeenError as e:
                logger.warning("Firewall restore failed: %s", e, exc_info=True)
            finally:
                firewall_snapshot = None
        if name_resolution_snapshot is not None:
            try:
                revert_disable_netbios_llmnr(name_resolution_snapshot)
            except YaqeenError as e:
                logger.warning("NetBIOS/LLMNR restore failed: %s", e, exc_info=True)
            finally:
                name_resolution_snapshot = None
        if ics_snapshot is not None:
            try:
                revert_restore_ics(ics_snapshot)
            except YaqeenError as e:
                logger.warning("ICS restore failed: %s", e, exc_info=True)
            finally:
                ics_snapshot = None
        _stop_session_server()
        try:
            token_manager.stop()
        except Exception as e:
            logger.warning("Token manager stop: %s", e)
        try:
            conn.close()
        except Exception as e:
            logger.warning("DB close: %s", e)
        sys.exit(0)

    win.protocol("WM_DELETE_WINDOW", on_closing)
    try:
        win.mainloop()
    except Exception as e:
        logger.exception("GUI mainloop crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
