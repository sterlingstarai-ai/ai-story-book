# Store Submission Checklist

2026-09-06 기준: 무료 제한 베타, 신규 구매·오디오·실물 주문 비활성. 공동 최종 앱 검토 전에는 앱 레코드/식별자 생성, 업로드, 등록, 심사 제출을 실행하지 않는다. 아래 체크는 작업 목록이며 완료 표시는 실제 증거가 있을 때만 한다.

## Common
- [ ] App name and bundle identifiers are final
- [ ] Privacy Policy and Terms URLs are production links
- [ ] Support URL opens without login and provides an actual operating contact
- [ ] Account/data deletion can be requested outside the app through a working public resource
- [ ] Build number/version are release-ready
- [ ] Crash-free smoke test passed on real devices

## iOS App Store Connect
- [ ] Actual-build iPhone 6.9 screenshots, or the accepted 6.5 set if no 6.9 set is supplied
- [ ] Actual-build iPad 13 screenshots (the current app supports iPad)
- [ ] Korean and English descriptions uploaded
- [ ] Keywords and support URLs updated
- [ ] Free-beta review notes accurately state that new purchases are disabled
- [ ] Distribution profile, signed archive/export, and embedded privacy manifests verified
- [ ] Age rating questionnaire completed

## Google Play Console
- [ ] Phone screenshots uploaded (minimum required count)
- [ ] Feature graphic/icon uploaded
- [ ] Data safety form completed
- [ ] Content rating questionnaire completed
- [ ] Closed-test/production-access requirement checked for this personal account
- [ ] Upload certificate verified against the app's Play App Signing setup

## Final QA Before Submit
- [ ] First-run flow: consent -> onboarding -> home
- [ ] Story creation and viewer flow
- [ ] New purchase entry points remain disabled; existing restore behavior matches the beta description
- [ ] Data deletion flow
- [ ] Offline and network recovery flow

## Paid-release follow-up only

- [ ] Stable billing account identifier and real sandbox purchase/restore/refund tests
- [ ] Store products, receipt verification and server notifications verified before enabling new purchases

## Official requirements checked 2026-09-06

- [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/): 6.9/6.5 alternatives and iPad 13 support requirements.
- [Apple platform information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/): support URL must lead to actual contact information.
- [Apple app privacy](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/): required policy URL and accurate app/partner data disclosures.
- [Google account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en): apps offering account creation must support in-app and external deletion requests. This product has server accounts and recovery across devices, so prepare that pathway rather than assume an anonymous-entry exemption.
- [Google personal account testing](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en): personal accounts created after 2023-11-13 require at least 12 opted-in testers continuously for 14 days before applying for production access. This account's applicability is not yet verified; automated E2E does not substitute for that test.
