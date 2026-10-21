"""Configuration layer: the ONLY layer allowed to read environment variables.

Loads settings once at startup into an immutable `AppConfig` so every other layer
receives plain values instead of touching `os.environ`.

Data lives OUTSIDE the project folder: `DATA_DIR` (default `~/Desktop/projects-data/literature-fetch`) holds
input/, output/, needs_review/, state/, db/ and logs/. The project folder only holds code,
docs and small test fixtures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = "~/Desktop/projects-data/literature-fetch"


def load_dotenv_file(path: Path) -> None:
    """Load `KEY=value` lines from a `.env` file without overriding variables that are already set.

    Args:
        path: The `.env` file (missing files are ignored).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class AppConfig:
    """Immutable application settings.

    Attributes:
        app_env: Deployment environment name, e.g. `development` or `production`.
        log_level: Logging level name, e.g. `INFO` or `DEBUG`.
        log_to_file: Also write `<data_dir>/logs/app.log` and `errors.log` (default on; tests turn it off).
        timeout_seconds: Timeout for outgoing API calls.
        ollama_base_url: Local Ollama endpoint (always 127.0.0.1, never localhost / 0.0.0.0).
        data_dir: Root folder for all data, outside the project folder.
        library_email: University e-mail for the OpenAthens sign-in (`USER_EMAIL`).
        library_password: Its password (`USER_PASSWORD`); hidden from repr so it never reaches logs.
        openathens_domain: OpenAthens organisation domain for the redirector; empty = plain DOI links.
        database_url_override: `DATABASE_URL` from `.env`; empty = SQLite file in `<data_dir>/db/`.
        http_port: Port of the local web app (always bound to 127.0.0.1).
        http_allowed_hosts: Extra Host names accepted by the web app (e.g. `host.docker.internal` for Open
            WebUI in Docker); empty = this machine only.
        ebsco_profile: Library's EBSCO Discovery profile id (`research.ebsco.com/c/<id>`); empty = skip.
    """

    app_env: str = "development"
    log_level: str = "INFO"
    log_to_file: bool = True
    timeout_seconds: int = 15
    ollama_base_url: str = "http://127.0.0.1:11434"
    data_dir: Path = Path(DEFAULT_DATA_DIR).expanduser()
    library_email: str = ""
    library_password: str = field(default="", repr=False)
    openathens_domain: str = "ndhu.edu.tw"
    ebsco_profile: str = "3pnjf3"
    database_url_override: str = ""
    http_port: int = 8765
    http_allowed_hosts: tuple[str, ...] = ()

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL of the database.

        Returns:
            `DATABASE_URL` when set, else `sqlite:///<data_dir>/db/literature.db`.
        """
        return self.database_url_override or f"sqlite:///{self.data_dir / 'db' / 'literature.db'}"

    @property
    def literature_dir(self) -> Path:
        """Folder for downloaded literature PDFs and the download report.

        Returns:
            `<data_dir>/output/literature`.
        """
        return self.output_dir / "literature"

    @property
    def browser_profile_dir(self) -> Path:
        """Persistent Chrome profile used for publisher access (keeps the sign-in between runs).

        Returns:
            `<data_dir>/state/browser_profile`.
        """
        return self.state_dir / "browser_profile"

    @property
    def input_dir(self) -> Path:
        """Folder with files waiting to be processed.

        Returns:
            `<data_dir>/input`.
        """
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """Folder for produced results.

        Returns:
            `<data_dir>/output`.
        """
        return self.data_dir / "output"

    @property
    def needs_review_dir(self) -> Path:
        """Quarantine for failed or low-confidence items (batches never stop for them).

        Returns:
            `<data_dir>/needs_review`.
        """
        return self.data_dir / "needs_review"

    @property
    def state_dir(self) -> Path:
        """Folder for progress / resume state.

        Returns:
            `<data_dir>/state`.
        """
        return self.data_dir / "state"

    @property
    def logs_dir(self) -> Path:
        """Folder for log files.

        Returns:
            `<data_dir>/logs`.
        """
        return self.data_dir / "logs"


def _flag(value: str) -> bool:
    """Interpret an environment flag.

    Args:
        value: Raw text such as `1`, `true`, `yes`.

    Returns:
        True for 1 / true / yes / on (case-insensitive).
    """
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> AppConfig:
    """Read and validate configuration from `.env` and environment variables.

    Returns:
        A populated `AppConfig`.

    Raises:
        ValueError: When a numeric setting is not an integer.
    """
    load_dotenv_file(PROJECT_ROOT / ".env")
    data_dir = Path(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR).strip()).expanduser()
    return AppConfig(
        app_env=os.environ.get("APP_ENV", "development").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
        log_to_file=_flag(os.environ.get("LOG_TO_FILE", "true")),
        timeout_seconds=int(os.environ.get("API_TIMEOUT_SECONDS", "15")),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/"),
        data_dir=data_dir,
        library_email=os.environ.get("USER_EMAIL", "").strip(),
        library_password=os.environ.get("USER_PASSWORD", ""),
        openathens_domain=os.environ.get("OPENATHENS_DOMAIN", "ndhu.edu.tw").strip(),
        ebsco_profile=os.environ.get("EBSCO_PROFILE", "3pnjf3").strip(),
        database_url_override=os.environ.get("DATABASE_URL", "").strip(),
        http_port=int(os.environ.get("HTTP_PORT", "8765")),
        http_allowed_hosts=tuple(
            h.strip() for h in os.environ.get("HTTP_ALLOWED_HOSTS", "").split(",") if h.strip()
        ),
    )
