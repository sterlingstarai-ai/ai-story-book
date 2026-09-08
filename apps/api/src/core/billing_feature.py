"""Availability of new purchases, independent of existing transaction settlement."""

from src.core.config import settings


def purchase_capabilities() -> dict[str, bool]:
    enabled = settings.purchases_enabled and settings.iap_verification_mode == "strict"
    # The mobile client uses StoreKit 2, so legacy shared-secret configuration
    # alone cannot advertise a working Apple checkout. Native notifications also
    # keep paid renewals/refunds synchronized without a custom adapter.
    apple = bool(
        enabled
        and settings.apple_bundle_id
        and (
            settings.apple_notification_environment == "Sandbox"
            or (
                settings.apple_notification_environment == "Production"
                and (settings.apple_app_id or 0) > 0
            )
        )
    )
    google = bool(
        enabled
        and settings.google_play_package_name
        and (
            settings.google_play_access_token
            or settings.google_play_service_account_json
            or settings.google_play_service_account_file
        )
        and settings.google_rtdn_audience
        and settings.google_rtdn_service_account_email
    )
    return {
        "purchases_supported": apple or google,
        "apple_purchases_supported": apple,
        "google_purchases_supported": google,
    }
