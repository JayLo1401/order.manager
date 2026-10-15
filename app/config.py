from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://bestellung:bestellung@localhost:5432/bestellung"
    session_secret: str = "change-me"
    session_cookie_secure: bool = False
    log_dir: str = "./data/logs"
    timezone: str = "Europe/Vienna"

    admin_email: str = "admin@example.com"
    admin_password: str = "changeme123"
    admin_name: str = "Admin"

    # Leer = alles ueber die Domain, mit der die Seite gerade aufgerufen wird.
    admin_base_url: str = ""
    guest_base_url: str = ""

    vapid_subject: str = ""

    @property
    def guest_host(self) -> str | None:
        return urlparse(self.guest_base_url).hostname if self.guest_base_url else None

    @property
    def admin_host(self) -> str | None:
        return urlparse(self.admin_base_url).hostname if self.admin_base_url else None


settings = Settings()
