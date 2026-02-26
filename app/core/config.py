from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "llm-course-backend"
    app_env: str = "development"
    app_port: int = 10723

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:15432/llm_course"

    jwt_secret: str = "change-me"
    access_token_expire_seconds: int = 3600
    refresh_token_expire_seconds: int = 30 * 24 * 3600
    email_code_expire_seconds: int = 300
    dev_fixed_email_code: str = ""
    email_sender_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_from_email: str = ""
    smtp_from_alias: str = ""

    auth_code_window_seconds: int = 600
    auth_code_max_per_email_window: int = 5
    auth_code_max_per_ip_window: int = 20
    auth_code_cooldown_seconds: int = 30

    seed_data: bool = True
    admin_api_key: str = ""

    # OSS / CDN (bundle delivery)
    oss_enabled: bool = False
    oss_region_id: str = ""
    oss_endpoint: str = ""
    oss_bucket_name: str = ""
    oss_cdn_domain: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_role_arn: str = ""
    oss_sts_duration_seconds: int = 1800
    oss_download_signed_url_enabled: bool = False
    oss_download_url_expire_seconds: int = 900
    oss_bundle_prefix: str = "bundles/"

    base_url: str = ""  # e.g. "http://47.93.151.131:10723" — used to build absolute URLs for local uploads

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
