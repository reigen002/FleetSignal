"""Environment settings with project-relative defaults, independent of cwd."""
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLEETSIGNAL_")

    database_url: str = f"sqlite:///{(PROJECT_ROOT / '.fleetsignal' / 'fleetsignal.db').as_posix()}"
    data_dir: Path = PROJECT_ROOT / "data"
    demo_mode: bool = False
    sqlite_busy_timeout_ms: int = Field(default=5000, gt=0, le=60000)
    allowed_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ])

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("data_dir must be an absolute path")
        return value.resolve()

    @field_validator("database_url")
    @classmethod
    def absolute_sqlite_database(cls, value: str) -> str:
        try:
            url = make_url(value)
        except ArgumentError as error:
            raise ValueError("database_url must be a valid database URL") from error
        if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
            raise ValueError("database_url must use file-backed SQLite; memory and other database backends are unsupported")
        if not Path(url.database).is_absolute():
            raise ValueError("SQLite database_url must use an absolute file path")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def explicit_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            origin = urlsplit(value)
            # Accessing port also validates malformed/out-of-range port numbers.
            origin.port
            if (
                "*" in value or any(character.isspace() for character in value)
                or origin.scheme not in ("http", "https") or not origin.hostname
                or origin.username is not None or origin.password is not None
                or origin.path or origin.query or origin.fragment
            ):
                raise ValueError("allowed_origins must contain explicit HTTP(S) origins without paths or credentials")
        return values
