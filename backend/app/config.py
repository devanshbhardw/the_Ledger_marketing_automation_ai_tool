"""Application settings loaded from environment / .env."""
from __future__ import annotations

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_ttl_seconds: int = 1800
    refresh_interval_min: int = 30
    cors_origins: str = "http://localhost:3000"

    # Path to the service-account JSON key. Its email must be added as a Viewer
    # (or higher) on the GA4 property. Falls back to the standard
    # GOOGLE_APPLICATION_CREDENTIALS env var if unset.
    service_account_file: str = ""

    # Optional GCP project for quota/billing attribution -> sets the
    # `x-goog-user-project` header on API calls.
    quota_project_id: str = ""

    # Force demo mode (synthetic data, no GA4 calls). When unset, demo mode
    # turns on automatically if no service-account key is configured.
    demo_mode: bool = False

    # Claude API key + model for AI insights (see the claude-api model catalog).
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    # Currency symbol used in insight phrasing.
    currency_symbol: str = "₹"  # ₹

    # OAuth apps for account discovery. Users sign in with Google / Meta and we
    # list the GA4 properties / ad accounts their account can access.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:3030/oauth/google/callback"
    # Required for Google Ads account discovery (developer-token header on the
    # Google Ads API). Discovery skips Ads accounts when unset.
    google_ads_developer_token: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = "http://localhost:3030/oauth/meta/callback"

    # Fernet key used to encrypt OAuth tokens at rest. Must stay stable across
    # restarts in production — regenerating it invalidates every stored token.
    token_encryption_key: str = ""

    def model_post_init(self, __context) -> None:
        if not self.token_encryption_key:
            from cryptography.fernet import Fernet

            self.token_encryption_key = Fernet.generate_key().decode()
            logger.warning(
                "TOKEN_ENCRYPTION_KEY is not set; generated an ephemeral key for "
                "this process. Pin it in .env for production — regenerating the "
                "key invalidates every stored OAuth token."
            )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
