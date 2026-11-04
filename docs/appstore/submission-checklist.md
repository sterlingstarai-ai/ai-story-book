# Store Submission Checklist

무료 제한 베타에서는 신규 구매와 실물 주문을 끈다. 낭독은 실제 베타 서버에서 합성과 기기 재생이 검증된 범위로 안내한다. 발음 평가와 가족 음성은 별도 기능으로 취급한다. 공동 최종 앱 검토 전에는 앱 레코드/식별자 생성, 업로드, 등록, 심사 제출을 실행하지 않는다. 아래 체크는 작업 목록이며 완료 표시는 실제 증거가 있을 때만 한다.

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
- [ ] Invite-only generation allows an invited account and refuses an uninvited account before paid provider calls
- [ ] One complete fictional story on each target device, including cover, every illustration, and narration through the last page
- [ ] New purchase entry points remain disabled; existing restore behavior matches the beta description
- [ ] Data deletion flow
- [ ] Offline and network recovery flow

## 제한 베타 심사 메모 초안

신규 구독·크레딧 구매와 실물 주문을 비활성화한 초대 전용 무료 베타입니다. 새 동화 생성은 지정된 시험 계정에 허용되며, 무료 신규 낭독은 3–5세 동화에서 확인할 수 있습니다. 사진 업로드 없이 가상 캐릭터와 한국어 12쪽 동화를 시험합니다.

1. 보호자 동의와 첫 안내를 마친 새 초대 계정에서 생성 화면을 엽니다. 같은 장면의 세 연령별 본문 예시를 비교합니다. 가상 캐릭터, 3–5세, 한국어, 기본 12쪽을 선택해 무료 동화 한 권을 만듭니다.
2. 표지와 본문 그림 12장을 엽니다. 본문을 눌러 낭독을 시작·일시정지합니다. 설정에서 이야기 성우·구연동화·잠자리 세 가지 미리듣기를 확인한 뒤, 리더의 수면 모드에서 처음부터 마지막 쪽까지 순서대로 재생합니다.
3. 크레딧 잔액이 0이고, 두 번째 생성 요청에 무료 이용 한도가 표시되며, 첫 책은 서재에서 계속 열리는지 확인합니다.
4. 설정에서 서재 복구와 데이터 삭제 경로를 확인합니다. 실제 삭제 요청은 생성·낭독 검증을 마친 별도 합성 계정으로 시험합니다.

제출 담당자는 베타 서버에 연결된 초대 시험 계정과 비초대 대조 계정을 별도로 확인합니다. 심사자 접속 절차와 검증한 지원·삭제 주소를 제출 직전에 채웁니다. 기기 인증 키, 복구 코드, 공급자 키는 공개 설명이나 검토 메모에 기록하지 않습니다.

## Paid-release follow-up only

- [ ] Stable billing account identifier and real sandbox purchase/restore/refund tests
- [ ] Store products, receipt verification and server notifications verified before enabling new purchases

## Official requirements checked 2026-09-06

- [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/): 6.9/6.5 alternatives and iPad 13 support requirements.
- [Apple platform information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/): support URL must lead to actual contact information.
- [Apple app privacy](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/): required policy URL and accurate app/partner data disclosures.
- [Google account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en): apps offering account creation must support in-app and external deletion requests. This product has server accounts and recovery across devices, so prepare that pathway rather than assume an anonymous-entry exemption.
- [Google personal account testing](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en): personal accounts created after 2023-11-13 require at least 12 opted-in testers continuously for 14 days before applying for production access. This account's applicability is not yet verified; automated E2E does not substitute for that test.
