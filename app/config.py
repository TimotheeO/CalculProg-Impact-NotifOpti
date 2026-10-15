import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str = f"sqlite:///{ROOT / 'var' / 'impactflow.sqlite3'}"
    environment: str = "development"

    def __post_init__(self):
        url = make_url(self.database_url)
        if url.drivername != "sqlite":
            raise ValueError(
                "C1-02 utilise SQLite : DATABASE_URL doit commencer par sqlite:///"
            )
        if (
            url.database not in (None, "", ":memory:")
            and not Path(url.database).is_absolute()
        ):
            raise ValueError(
                "DATABASE_URL doit utiliser un chemin absolu pour éviter deux bases différentes"
            )
        if url.query or url.host or url.username or url.password:
            raise ValueError(
                "DATABASE_URL contient des options SQLite non prises en charge"
            )
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENV doit valoir development, test ou production")
        if url.database in (None, "", ":memory:") and self.environment != "test":
            raise ValueError("Une base sur disque est obligatoire hors des tests")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            environment=os.getenv("APP_ENV", "development"),
        )
