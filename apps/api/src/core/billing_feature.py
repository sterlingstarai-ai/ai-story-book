"""Availability of new purchases, independent of existing transaction settlement."""
from src.core.config import settings


def purchase_capabilities() -> dict[str, bool]:
    enabled = (settings.purchases_enabled and settings.iap_verification_mode == "strict"
               and bool(settings.iap_webhook_secret))
    apple = bool(enabled and settings.apple_iap_shared_secret and settings.apple_bundle_id)
    google = bool(enabled and settings.google_play_package_name and (
        settings.google_play_access_token or settings.google_play_service_account_json
        or settings.google_play_service_account_file
    ))
    return {
        "purchases_supported": apple or google,
        "apple_purchases_supported": apple,
        "google_purchases_supported": google,
    }
