"""
AtcoGenie AI Engine — Configuration Module
Loads settings from environment variables with Pydantic validation.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # --- Application ---
    app_name: str = "AtcoGenie-AI"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "DEBUG"
    cors_origins: str = "http://localhost:5173,http://localhost:5256"

    # --- LLM Provider ---
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    openai_fallback_model: str = "gpt-4o"
    google_api_key: str = ""
    google_model: str = "gemini-2.5-flash"

    # --- Pharma CRM (MS SQL) ---
    pharma_db_host: str = "10.10.0.88"
    pharma_db_port: int = 1433
    pharma_db_name: str = "PharmaCRM"
    pharma_db_user: str = "dakiadbreader"
    pharma_db_password: str = ""
    pharma_db_driver: str = "ODBC Driver 18 for SQL Server"
    pharma_pool_min: int = 2
    pharma_pool_max: int = 10


    # --- Third-Party (MS SQL) ---
    thirdparty_db_host: str = "10.10.0.88"
    thirdparty_db_port: int = 1433
    thirdparty_db_name: str = "ThirdPartyDB"
    thirdparty_db_user: str = "dakiadbreader"
    thirdparty_db_password: str = ""
    thirdparty_db_driver: str = "ODBC Driver 18 for SQL Server"
    thirdparty_pool_min: int = 2
    thirdparty_pool_max: int = 10

    # --- PostgreSQL (Checkpointer + IMD) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "AtcoGenie_Checkpoints"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    imd_db: str = "AtcoGenie_IMD"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_role_cache_ttl: int = 900
    redis_session_ttl: int = 1800

    # --- Active Directory ---
    ad_server: str = "ldap://dc01.atcolab.local"
    ad_base_dn: str = "DC=atcolab,DC=local"
    ad_domain: str = "ATCO"

    # --- JWT ---
    jwt_secret_key: str = "change-this-to-a-secure-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480

    # --- Rate Limiting ---
    rate_limit_per_minute: int = 30
    rate_limit_per_hour: int = 300

    # --- Observability ---
    langsmith_api_key: str = ""
    langsmith_project: str = "atcogenie-production"
    langsmith_tracing: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def pharma_odbc_dsn(self) -> str:
        return (
            f"DRIVER={{{self.pharma_db_driver}}};"
            f"SERVER={self.pharma_db_host},{self.pharma_db_port};"
            f"DATABASE={self.pharma_db_name};"
            f"UID={self.pharma_db_user};"
            f"PWD={{{self.pharma_db_password}}};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
        )

    @property
    def thirdparty_odbc_dsn(self) -> str:
        return (
            f"DRIVER={{{self.thirdparty_db_driver}}};"
            f"SERVER={self.thirdparty_db_host},{self.thirdparty_db_port};"
            f"DATABASE={self.thirdparty_db_name};"
            f"UID={self.thirdparty_db_user};"
            f"PWD={{{self.thirdparty_db_password}}};"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def imd_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.imd_db}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False, "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
