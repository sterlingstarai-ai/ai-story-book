# MOBILE PACKAGE KNOWLEDGE

## SCOPE

- Standalone Flutter package `ai_story_book`; Flutter CI uses 3.38.7.
- Android and iOS are product targets. Desktop/web directories are mostly Flutter scaffold.
- Package bootstrap, dependency injection, lifecycle hooks, theme, and named routes live in `lib/main.dart`.

## ARCHITECTURE

- `lib/providers/providers.dart` is the handwritten Riverpod composition root.
- `sharedPreferencesProvider` intentionally throws until application or test scope overrides it.
- Keep reusable async state in providers/notifiers; keep widget-only transient state local.
- `ApiClient` is the only backend transport boundary. Add endpoint calls there, not inline Dio calls.
- `apiClientProvider` derives base URL, generated user key, and active profile ID.
- Profile switches must invalidate `apiClientProvider` and all profile-scoped data providers.
- Preserve request telemetry and `X-Request-ID`, `X-User-Key`, and optional `X-Profile-Id` headers.
- Parse stable responses into models under `lib/models`; use `JsonParsing` for defensive coercion.
- Newer map-shaped endpoints still validate top-level map/list/scalar shapes in `ApiClient`.
- Dio failures remain wrapped with `ApiError`; UI payment handling inspects `DioException.error`.
- `lib/screens/screens.dart` is the route-screen barrel. Register routes in `buildAppRoute`.
- Validate route arguments and retain the safe home fallback for malformed input.
- Main creation flow: create screen -> `BookCreationNotifier` -> bounded polling -> viewer.
- `bookDetailProvider` is network-first with a `SharedPreferences` JSON cache fallback.
- Native/plugin services should expose injectable interfaces when tests need deterministic fakes.

## PRODUCT-SAFETY CONSTRAINTS

- Preserve startup consent -> onboarding -> home gating.
- Preserve the 30-minute parental age-gate session and screen-time lock overlay.
- Photo/drawing character entry points must share `ensurePhotoConsent`; do not fork consent wording.
- Do not weaken fail-closed ranking behavior for young children or parental purchase/report gates.
- Use `AppShell` for the four-tab home/create/library/characters family.
- Use design tokens from `lib/utils/constants.dart`; minimum child-facing touch target is 64 px.

## LOCALIZATION AND GENERATED FILES

- English ARB is the template; every user-facing key must exist in English, Korean, and Japanese.
- Edit `lib/l10n/app_{en,ko,ja}.arb`, then run `flutter gen-l10n`.
- Never hand-edit `lib/l10n/app_localizations*.dart`.
- Never hand-edit `linux|macos|windows/flutter/generated_*` plugin registrants.
- Icon and splash outputs derive from `pubspec.yaml`, `assets/icons`, and `assets/branding`.
- Keep tracked `pubspec.lock` and iOS `Podfile.lock` synchronized after dependency changes.
- Do not commit `.dart_tool`, `build`, `coverage`, Pods, ephemeral files, or signing material.

## CONFIGURATION

- Debug default is `10.0.2.2:8000` on Android emulator and `localhost:8000` elsewhere.
- `--dart-define=API_BASE_URL=...` overrides debug/local transport.
- Release startup rejects missing or placeholder `PROD_API_URL`.
- Store-ready builds also require `KAKAO_NATIVE_APP_KEY`.
- Android release signing reads ignored `android/key.properties`; use the tracked example as shape only.

## TESTING

- Unit/widget tests live in `test`; cross-screen journeys live in `integration_test`.
- Override providers, subclass `ApiClient`, and use `SharedPreferences.setMockInitialValues`.
- Pin locale and localization delegates when tests assert rendered copy.
- Plugin behavior tests should inject fakes; headless tests do not prove device/store behavior.
- UI changes must cover short viewports, large text, modal scroll reachability, and overflow.

## COMMANDS

```bash
flutter gen-l10n
dart format lib test integration_test
flutter analyze
flutter test
flutter test integration_test/
cd ../.. && bash scripts/flutter-ui-preflight.sh
```
