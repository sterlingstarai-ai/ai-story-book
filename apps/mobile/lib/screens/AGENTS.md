# SCREEN RULES

## SCOPE

- Routed Flutter UI in this directory.
- `viewer_screen.dart` is the main lifecycle hotspot.
- `credits_screen.dart`, `characters_screen.dart`, and profile/report screens cross safety boundaries.
- Keep transport and reusable state in `services/` and `providers/`; screens orchestrate presentation.

## ASYNC UI

- After every `await`, check `mounted` or `context.mounted` before `setState`, navigation, dialogs, or snackbars.
- Capture locale, localized text, and `RenderBox` share origin before an async gap when later context access is avoidable.
- Mark intentional background work with `unawaited`; do not leave bare futures in callbacks.
- Dispose every controller, timer, stream subscription, player, and animation/confetti controller owned by the screen.
- Guard repeated submissions, polling, pagination, and navigation with explicit in-flight/idempotence flags.
- Noncritical analytics, review prompts, progress writes, and learning metrics must not block reading.

## RIVERPOD

- Use `ref.watch` only for state that drives `build`; use `ref.read` for commands and event handlers.
- Render provider-backed remote state with `AsyncValue.when`/`maybeWhen`; preserve useful cached data during recoverable failures.
- Call notifier methods for mutations; do not duplicate provider state in a screen unless it is transient UI state.
- Profile changes require invalidating `apiClientProvider` before new scoped requests.
- Then invalidate every profile-scoped view: library, browse, streak, growth, peer comparison, and weekly trend.
- Tests must inject provider overrides; never add singleton or direct network escape hatches for test convenience.

## ROUTES

- Navigation uses the names and argument shapes declared by `buildAppRoute` in `main.dart`.
- Keep `/credits` and `/reading-growth` route settings intact: their parental gates inspect `ModalRoute.settings.name`.
- New route arguments need validation and malformed-input coverage in `test/app_route_test.dart`.
- Use `AppShell` only for primary tab destinations; preserve its tab indexes and replacement navigation.
- Prevent completion/loading flows from navigating twice.

## CHILD SAFETY

- Keep parental verification before purchases, growth/ranking views, public share-link creation, and destructive account actions.
- Public sharing uses server-issued revocable token URLs; never expose a raw book ID as a public URL.
- Photo/drawing upload requires just-in-time consent immediately before use.
- On declined consent, delete the selected temporary child image and stop the flow.
- Do not expose peer ranking unless the server explicitly returns `show_ranking == true`.
- Safety, consent, purchase, and privacy failures fail closed; optional reading enhancements may fail open.

## FEATURE INVARIANTS

- Viewer page `0` is the cover; story pages and API page numbers are one-based.
- Cover audio stays disabled; stop or restart audio when changing pages.
- A viewer session records exactly one terminal reading result: completed or abandoned, never both.
- Clear persisted reading progress on completion; keep the versioned per-book key for resumable exits.
- Deduplicate quiz/vocabulary submissions per session; remove the marker after a failed write so retry remains possible.
- Hidden viewer controls must use `IgnorePointer` as well as opacity so invisible layers do not capture taps.
- Credits purchase updates must deduplicate transaction IDs, verify receipts/tokens server-side, refresh state, and call `completePurchase` on every terminal path.
- Library pagination must prevent overlapping `loadMore`; offline errors retain loaded books and show the offline banner.
- Payment-required Dio failures wrap `ApiError` in `DioException.error`; preserve that extraction path and the upgrade/credit modal.
- Share/export filenames must be sanitized; use platform storage directories and a nonempty share origin.

## UI AND ACCESSIBILITY

- Use existing design tokens and shared widgets; avoid screen-local substitutes for standard buttons, cards, and sheets.
- Interactive targets remain at least 64 px for the child-facing experience.
- Add tooltips or semantics for icon-only and custom gesture controls.
- Long sheets use `AdaptiveModalSheet` or a scrollable `DraggableScrollableSheet`.
- Validate complex sheets at 320x480 and approximately 1.4x text scale; the final action must remain reachable.
- In overlay stacks, verify warning banners, sleep mode, controls, dialogs, snackbars, and the global screen-time lock do not conflict.

## TESTS

- Add widget tests for loading, data, empty, error, disabled, and retry states touched by the change.
- Extend `test/ui_preflight_test.dart` for new long sheets, overlays, large-text behavior, or tap interception.
- Extend integration tests for startup, consent/onboarding, parental gates, named navigation, or cross-screen provider flows.
- Run focused tests first, then `flutter analyze`, `flutter test --coverage`, and `flutter test integration_test/` from `apps/mobile`.
- Device plugins and store flows still need real-device verification; passing mocks do not prove IAP, audio, sharing, notifications, or image picking.
