"""Settings de la API. Lee variables de entorno (incluido .env si existe)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# tfg/web/backend/app/config.py -> tfg/web/
_WEB_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuracion del backend.

    Los paths del JSON son relativos a tfg/web/ por defecto, coincidiendo
    con la convencion del .env.example.
    """

    # Datos
    extracted_json_path: Path = _WEB_DIR / ".." / "pdfs_extracted.json"
    extracted_codes_json_path: Path = _WEB_DIR / ".." / "pdfs_extracted_codes.json"

    # OpenAI
    openai_api_key: str | None = None

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # CORS (lista separada por comas)
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    # Frontend
    serve_frontend: bool = True
    frontend_dir: Path = _WEB_DIR / "frontend"

    model_config = SettingsConfigDict(
        env_file=_WEB_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """El .env de tfg/web/ tiene prioridad sobre la env del sistema.

        Sin esto, una OPENAI_API_KEY antigua persistida en el entorno de
        Windows pisa la del .env y la app sigue usando la clave caducada.
        """
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def extracted_json_resolved(self) -> Path:
        """Path absoluto resuelto del JSON canonico (etiquetas legibles)."""
        return self.extracted_json_path.resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton para inyectar como dependencia."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
