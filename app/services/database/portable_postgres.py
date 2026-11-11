"""
User-space Portable PostgreSQL + pgvector Lifecycle Manager.
Provides automatic initialization (initdb), background daemon startup (pg_ctl start),
pgvector extension provisioning, and clean shutdown (pg_ctl stop) without administrator
privileges or system-level installers.
"""

import atexit
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("contextcortex.portable_postgres")


def get_bundle_base_dir() -> Path:
    """Resolves the base directory of the application or frozen PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_resource_dir() -> Path:
    """Resolves the directory containing bundled static resources (_MEIPASS when frozen)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return get_bundle_base_dir()


def find_free_port(preferred_port: int = 54329, host: str = "127.0.0.1") -> int:
    """Checks if preferred_port is free; otherwise finds an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, preferred_port)) != 0:
            return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class PortablePostgresManager:
    """
    Manages a user-space portable PostgreSQL + pgvector instance stored inside the
    application bundle or user data directory.
    """

    _instance: Optional["PortablePostgresManager"] = None

    def __init__(
        self,
        pg_bin_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        port: Optional[int] = None,
        user: str = "postgres",
        dbname: str = "contextcortex",
        host: str = "127.0.0.1",
    ):
        base_dir = get_bundle_base_dir()
        env_bin = os.getenv("PORTABLE_PG_BIN_DIR")
        if pg_bin_dir:
            self.pg_bin_dir = Path(pg_bin_dir).resolve()
        elif env_bin:
            self.pg_bin_dir = Path(env_bin).resolve()
        else:
            # Check alongside executable first, then inside _MEIPASS
            candidate = base_dir / "pgsql" / "bin"
            if not candidate.exists():
                candidate = get_resource_dir() / "pgsql" / "bin"
            self.pg_bin_dir = candidate

        env_data = os.getenv("PORTABLE_PG_DATA_DIR")
        if data_dir:
            self.data_dir = Path(data_dir).resolve()
        elif env_data:
            self.data_dir = Path(env_data).resolve()
        else:
            app_data = Path(os.getenv("DATA_DIR", str(base_dir / "data"))).resolve()
            self.data_dir = app_data / "pgdata"

        env_port = os.getenv("PORTABLE_PG_PORT")
        self.preferred_port = int(port or (env_port if env_port and env_port.isdigit() else 54329))
        self.port = self.preferred_port
        self.user = os.getenv("PORTABLE_PG_USER", user)
        self.dbname = os.getenv("PORTABLE_PG_DB", dbname)
        self.host = host
        self.log_file = self.data_dir.parent / "postgres.log"
        self._started_by_us = False

    @classmethod
    def get_instance(cls) -> "PortablePostgresManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _exe(self, name: str) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return self.pg_bin_dir / f"{name}{suffix}"

    def is_available(self) -> bool:
        """Returns True if portable PostgreSQL binaries (initdb, pg_ctl, postgres) exist."""
        return (
            self._exe("initdb").exists()
            and self._exe("pg_ctl").exists()
            and self._exe("postgres").exists()
        )

    def is_initialized(self) -> bool:
        """Returns True if PG_VERSION exists in the target data_dir."""
        return (self.data_dir / "PG_VERSION").exists()

    def is_running(self) -> bool:
        """Checks if the portable PostgreSQL instance is currently running."""
        if not self.is_available() or not self.is_initialized():
            return False
        res = subprocess.run(
            [str(self._exe("pg_ctl")), "-D", str(self.data_dir), "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0

    def get_database_url(self) -> str:
        """Returns the SQLAlchemy-compatible PostgreSQL URL for this portable instance."""
        return f"postgresql+psycopg://{self.user}@127.0.0.1:{self.port}/{self.dbname}"

    def initialize_cluster(self) -> None:
        """Runs initdb in user-space with trust authentication on 127.0.0.1 and UTF8 encoding."""
        if self.is_initialized():
            return

        logger.info("Initializing portable PostgreSQL cluster at %s...", self.data_dir)
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            str(self._exe("initdb")),
            "-D",
            str(self.data_dir),
            "-U",
            self.user,
            "-A",
            "trust",
            "-E",
            "UTF8",
            "--no-locale",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(
                f"Portable PostgreSQL initdb failed (exit {res.returncode}): {res.stderr or res.stdout}"
            )

        # Tune postgresql.conf for local user-space operation
        conf_path = self.data_dir / "postgresql.conf"
        if conf_path.exists():
            with open(conf_path, "a", encoding="utf-8") as f:
                f.write("\n# ContextCortex Portable User-Space Tuning\n")
                f.write(f"listen_addresses = '{self.host}'\n")
                f.write("shared_buffers = 128MB\n")
                f.write("work_mem = 16MB\n")
                f.write("maintenance_work_mem = 64MB\n")
                f.write("max_connections = 50\n")
                if os.name == "nt":
                    f.write("unix_socket_directories = ''\n")

    def start(self) -> str:
        """
        Initializes (if needed) and starts the portable PostgreSQL cluster, creates the
        target database and pgvector extension, and returns the DATABASE_URL.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"Portable PostgreSQL binaries not found in {self.pg_bin_dir}"
            )

        self.initialize_cluster()

        if not self.is_running():
            self.port = find_free_port(self.preferred_port, self.host)
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Starting portable PostgreSQL server on %s:%d (data: %s)...",
                self.host,
                self.port,
                self.data_dir,
            )
            pg_opts = f"-p {self.port} -h {self.host}"
            cmd = [
                str(self._exe("pg_ctl")),
                "-D",
                str(self.data_dir),
                "-l",
                str(self.log_file),
                "-o",
                pg_opts,
                "-w",
                "start",
            ]
            # pg_ctl starts postgres through a child shell that inherits pg_ctl's
            # stdout/stderr handles. On Windows, capture_output=True then blocks
            # forever: the pipes stay open for as long as the server runs. Send
            # pg_ctl's output to a file so that no pipe is inherited.
            out_file = self.log_file.parent / "pg_ctl.out"
            try:
                with open(out_file, "w", encoding="utf-8", errors="ignore") as out:
                    rc = subprocess.run(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=120,
                    ).returncode
            except subprocess.TimeoutExpired:
                rc = -1
            if rc != 0:
                pg_ctl_out = ""
                try:
                    pg_ctl_out = out_file.read_text(encoding="utf-8", errors="ignore")[-1500:]
                except Exception:
                    pass
                log_tail = ""
                if self.log_file.exists():
                    try:
                        log_tail = self.log_file.read_text(encoding="utf-8", errors="ignore")[-1500:]
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Portable PostgreSQL failed to start (exit {rc}): "
                    f"{pg_ctl_out}\nLog tail:\n{log_tail}"
                )
            self._started_by_us = True
            atexit.register(self.stop)
        else:
            # Read active port from postmaster.pid if already running
            pid_file = self.data_dir / "postmaster.pid"
            if pid_file.exists():
                try:
                    lines = pid_file.read_text(encoding="utf-8").splitlines()
                    if len(lines) >= 4 and lines[3].strip().isdigit():
                        self.port = int(lines[3].strip())
                except Exception:
                    pass
            logger.info("Portable PostgreSQL already running on %s:%d", self.host, self.port)

        self._ensure_database_and_extension()
        db_url = self.get_database_url()
        os.environ["DATABASE_URL"] = db_url
        os.environ.setdefault("VECTOR_STORE", "pgvector")
        os.environ.setdefault("VECTOR_STORE_PROVIDER", "pgvector")
        return db_url

    def _ensure_database_and_extension(self) -> None:
        """Creates the target database and enables the pgvector extension."""
        import psycopg

        admin_url = f"postgresql://{self.user}@{self.host}:{self.port}/postgres"
        deadline = time.time() + 15.0
        last_err = None
        while time.time() < deadline:
            try:
                with psycopg.connect(admin_url, autocommit=True, connect_timeout=3) as conn:
                    row = conn.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s", (self.dbname,)
                    ).fetchone()
                    if not row:
                        logger.info("Creating database '%s' in portable PostgreSQL...", self.dbname)
                        conn.execute(f'CREATE DATABASE "{self.dbname}"')
                break
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        else:
            raise RuntimeError(f"Could not connect to portable PostgreSQL admin DB: {last_err}")

        target_url = f"postgresql://{self.user}@{self.host}:{self.port}/{self.dbname}"
        with psycopg.connect(target_url, autocommit=True, connect_timeout=5) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            logger.info("Verified 'vector' (pgvector) extension in database '%s'.", self.dbname)

    def stop(self) -> None:
        """Stops the portable PostgreSQL cluster if it is running."""
        if not self._started_by_us or not self.is_running():
            return
        logger.info("Stopping portable PostgreSQL server at %s...", self.data_dir)
        cmd = [
            str(self._exe("pg_ctl")),
            "-D",
            str(self.data_dir),
            "-m",
            "fast",
            "-w",
            "stop",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=False)
        self._started_by_us = False


def bootstrap_portable_postgres_if_needed() -> Optional[str]:
    """
    Auto-starts portable PostgreSQL if:
    1. PORTABLE_POSTGRES_ENABLED=true (or running as a frozen executable with bundled pgsql/bin), AND
    2. DATABASE_URL is not already explicitly configured.
    """
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")

    mgr = PortablePostgresManager.get_instance()
    enabled_env = os.getenv("PORTABLE_POSTGRES_ENABLED", "").lower().strip()
    should_enable = enabled_env in ("1", "true", "yes") or (
        enabled_env not in ("0", "false", "no") and mgr.is_available()
    )

    if not should_enable:
        return None

    return mgr.start()
