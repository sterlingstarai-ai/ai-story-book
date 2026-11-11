# Store Submission Checklist

## 현재 제출 후보 — 2026-11-11

아래의 과거 등록 전 검토안과 미체크 목록을 현재 완료 판정으로 사용하지 않는다. 현재 후보는 **양쪽 1.0.0(4)**이며, 운영 백엔드는 `fccab95`의 API·워커다. 기본 Flare와 검수 실패 쪽 Sunburst 교정을 유지한다. ZDR 확인은 운영자의 별도 검토 항목이다.

| 항목 | 직접 확인한 상태 | 남은 확인 |
|---|---|---|
| Android 패키지 | AAB 4의 기존 고정 SHA-256과 일치. Play Alpha의 1.0.0(4) 검토본이 있음 | 비공개 테스트 검토 제출·승인·배포는 미완료 |
| iOS 패키지 | IPA 4의 기존 고정 SHA-256과 일치. 빌드 4 처리·내부 베타 배정 기록과 심사 초안의 선택 빌드 4를 확인 | 심사 접속 정보·연락처, 개인정보 신고 게시와 최종 제출 |
| Play 데이터 보안 | 보호자 이메일 항목과 직접 삭제 요청 주소를 보완하고 5/5 미리보기에서 **임시보관함에 저장** 완료 | 실제 발송 업체·SDK·AI 처리와 공유 예외/보관 조건 대조. 초안의 '제3자 공유 없음' 표시는 확정한 사실이 아님. 최종 저장·검토 전송은 하지 않음 |
| 공개 정책·지원·삭제 주소 | 네 HTTPS 주소 모두 200이며 승인된 지원 이메일 표시 | 메일 수신·실제 요청 처리와 스토어 신고의 최종 일치 |
| 보호자 이메일 | 서버·앱·심사 슬롯 연결 및 TLS 시험 구현. 실제 발송용 비공개 인증 파일은 없음 | 발송 계정 연결, 실제 수신·명시적 동의·심사 슬롯 배정 검증 후 운영 기능 활성화 |
| 실기기 | 11월 11일 iPhone 15에 설치된 앱은 1.0.0(3). 미러링은 Mac 인증 대기. Android 연결 없음 | 빌드 4를 받은 뒤 최종 운영 구성의 첫 권·13장·마지막 낭독·삭제·네트워크 복구 확인 |
| 운영 | 최신 실행 소스·백업 연결·실제 DB 유휴 재개·기존 마지막 낭독 캐시 검증 완료 | 최신 운영 구성의 새 Flare 첫 권을 기기 흐름으로 검증. 일일 백업은 여전히 서비스 중지 구간이 있음 |

근거: [패키지 해시와 공개 주소](../acceptance/2026-11-11-submission-draft-refresh/artifact-and-public-pages.json), [Play 저장 초안](../acceptance/2026-11-11-submission-draft-refresh/play-saved-draft.png), [Apple 선택 빌드·빈 심사 연락처](../acceptance/2026-11-11-submission-draft-refresh/apple-build4-review-contact.png), [내부 베타 배정](../acceptance/2026-11-11-ios-build4/internal-assignment.json), [운영 전환·검증 범위](../RELEASE_PREPARATION.md#2026-11-11-유휴-db-점검-운영-전환).

가족 정책 준수 표시를 추가하는 선택 배지는 활성화하지 않았다. 이 표시 선택은 아동 대상 앱의 정책 의무를 면제하거나 준수 검증을 완료하는 조치가 아니다. 미확인 조건을 체크해 제출 오류만 없애지 않는다. [Play 신고 정의·초안 저장 안내](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en)

## 과거 등록 전 검토 기록

무료 제한 베타에서는 신규 구매와 실물 주문을 끈다. 낭독은 실제 베타 서버에서 합성과 기기 재생이 검증된 범위로 안내한다. 발음 평가와 가족 음성은 별도 기능으로 취급한다. 공동 최종 앱 검토 전에는 앱 레코드/식별자 생성, 업로드, 등록, 심사 제출을 실행하지 않는다. 아래 체크는 작업 목록이며 완료 표시는 실제 증거가 있을 때만 한다.

## 2026-11-09 등록 전 검토안

첫 배포 범위는 한국어 무료 제한 베타로 제안한다. iOS는 TestFlight, Android는 Play 비공개 테스트를 사용한다. Google Play에서 개인 개발자 계정과 기존 앱 목록을 확인했다. AI Story Book은 해당 목록에 없으며, 새 앱의 프로덕션 액세스 요건은 앱 레코드 생성 후 대시보드에서 확인한다. 적용 대상인 신규 개인 계정은 최소 12명의 테스터가 14일 연속 참여해야 한다. App Store Connect는 로그인 후 기존 앱 레코드와 정확한 번들 ID 등록 여부를 확인한다. [TestFlight 개요](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/) · [Google 개인 계정 테스트 요건](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en)

| 입력 항목 | 검토안 |
|---|---|
| 앱 이름 / 기본 언어 | AI 동화책 / 한국어. 영어 이름은 AI Story Book. 실제 이름 사용 가능 여부는 콘솔에서 확인 |
| iOS | `com.storybook.aiStoryBook`, 버전 1.0.0, 빌드 1. 기존 빌드가 있으면 다음 번호 사용 |
| Android | `com.storybook.ai_story_book`, 버전 1.0.0, 버전 코드 1. 기존 빌드가 있으면 다음 번호 사용 |
| 짧은 소개 | 그림 동화를 만들고 한국어로 들어요 |
| 사용 대상 | 보호자가 설정·동의를 관리하고 3–9세 아동이 함께 읽는 사용 흐름. 양쪽 스토어 설문에 실제 대상 연령과 기능을 반영 |
| 공개 정책·지원·삭제 | [개인정보처리방침](https://ai-story-book-support.vercel.app/privacy/) · [이용약관](https://ai-story-book-support.vercel.app/terms/) · [고객지원](https://ai-story-book-support.vercel.app/support/) · [계정 삭제 안내](https://ai-story-book-support.vercel.app/delete-account/) |

**실기기 증거.** iPhone과 Android에서 공개 서버의 동일한 기존 책을 열어 마지막 쪽 음원의 자연 종료를 확인했다. 이 시험은 12쪽의 기존 음원 재생을 검증한다. 최종 출시 빌드의 첫 실행, 전체 읽기, 새 초대 계정의 무료 첫 권, 신고·삭제·오프라인 흐름은 별도 확인한다. [기기 결과와 빌드 검사](../RELEASE_PREPARATION.md#2026-11-09-스토어-등록-전-검토)

**제출 전 제품 설정.** 2026-11-11 공개 API에서 `free_first_book_trial`과 `generation_invitation_supported`가 활성화됐고, iPhone TestFlight 빌드 3의 초대 계정에 무료 첫 권 버튼이 표시됐다. 심사자 접근은 제출할 구성에서 새 설치로 검증한다. 제출 캡처는 해당 빌드의 가상 동화 화면에서 확보한다. Android의 이전 16 KB 가상 기기 검증은 디버그 빌드에 해당한다. 이번 출시 AAB의 패키징·라이브러리 정렬과 별도로 출시 빌드에서 기동을 확인한다. [Apple 스크린샷 규격](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/) · [Android 16 KB 규격](https://developer.android.com/guide/practices/page-sizes)

**개인정보·연령 설문 초안.** 서비스 식별자·보호자 동의·아이 프로필·독서 기록, 동화 입력과 생성 콘텐츠, 문의·오류 기록을 항목별로 대조한다. 사진은 실제 출시 플래그와 전송 경로를 확인하고, 외부 AI·스토리지·SDK가 다루는 데이터의 목적, 이용자 연결 여부, 수집·공유 여부는 출시 구성과 계약을 기준으로 확정한다. 공개 방침의 외부 처리·국외 이전과 보존 항목에 남은 문구를 확정한 뒤 앱 내 문서 및 공개본을 함께 대조한다. Google의 AI 생성 신고 항목은 리더의 콘텐츠 신고 화면과 연결한다. Apple Kids 카테고리는 아동용 앱의 제3자 전송과 보호자 게이트 요건을 검토한 뒤 결정한다. [Apple 심사 지침](https://developer.apple.com/app-store/review/guidelines/) · [Google Data safety](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en) · [Google AI 생성 콘텐츠 정책](https://support.google.com/googleplay/android-developer/answer/13985936?hl=en)

빌드 3과 4의 배포 패키지는 iPhone과 iPad를 모두 지원한다. App Store Connect는 Dynamic Island 중형 iPhone과 iPad 13인치 스크린샷을 요구한다. 실제로 생성한 가상 동화를 앱 화면에 표시해 두 규격으로 배치했으며 Apple 처리 완료를 확인한다. 내장 Kakao SDK의 개인정보 매니페스트에는 계정과 연결되는 기타 데이터가 앱 기능 목적으로 기재돼 있다. 앱 서버의 수집 항목과 보호자 이메일 발송 업체의 처리·보관을 별도로 대조한 뒤 Apple 신고를 확정한다. [Apple 스크린샷 규격](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/) · [Apple 앱 개인정보 항목](https://developer.apple.com/app-store/app-privacy-details/)

**계정 소유자 확인.** 앱 이름, 비공개 테스트 등록과 업로드, 개인정보 개정과 백업 보관 기준을 운영자가 승인했다. Apple 앱과 배포 프로파일을 등록했고, Play 앱 만들기 화면에는 승인된 앱 정보를 입력했다. Play 새 앱 등록에 필요한 개발자 정책·미국 수출 규정 준수 선언은 계정 소유자가 직접 확인한다. 판매자 상태 선언 기한은 2027-02-01이다. [현재 진행 기록](final-owner-review.md) · [Google 판매자 상태 안내](https://support.google.com/googleplay/android-developer/answer/17594752?hl=en)

## Common
- [ ] App name and bundle identifiers are final
- [ ] Privacy Policy and Terms URLs are production links
- [ ] Support URL opens without login and provides an actual operating contact
- [ ] Account/data deletion can be requested outside the app through a working public resource
- [ ] Build number/version are release-ready
- [ ] Crash-free smoke test passed on real devices

## iOS App Store Connect
- [ ] Apple has processed the screenshots placed in the Dynamic Island medium iPhone and 13-inch iPad slots
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

신규 구독·크레딧 구매와 실물 주문을 비활성화한 초대 전용 무료 베타입니다. 새 동화 생성은 지정된 시험 계정에 허용되며, 무료 첫 권의 한국어 낭독은 지원하는 세 연령대 모두에서 확인할 수 있습니다. 사진 업로드 없이 가상 캐릭터와 한국어 12쪽 동화를 시험합니다.

1. 보호자 동의와 첫 안내를 마친 새 초대 계정에서 생성 화면을 엽니다. 같은 장면의 세 연령별 본문 예시를 비교합니다. 가상 캐릭터, 7–9세, 한국어, 기본 12쪽을 선택해 무료 동화 한 권을 만듭니다.
2. 표지와 본문 그림 12장을 엽니다. 본문을 눌러 낭독을 시작·일시정지합니다. 설정에서 이야기 성우·구연동화·잠자리 세 가지 미리듣기를 확인한 뒤, 리더의 수면 모드에서 처음부터 마지막 쪽까지 순서대로 재생합니다.
3. 크레딧 잔액이 0이고, 두 번째 생성 요청에 무료 이용 한도가 표시되며, 첫 책은 서재에서 계속 열리는지 확인합니다.
4. 설정에서 서재 복구와 데이터 삭제 경로를 확인합니다. 실제 삭제 요청은 생성·낭독 검증을 마친 별도 합성 계정으로 시험합니다.

제출 담당자는 베타 서버에 연결된 초대 시험 계정과 비초대 대조 계정을 별도로 확인합니다. 심사자 접속 절차와 검증한 지원·삭제 주소를 제출 직전에 채웁니다. 기기 인증 키, 복구 코드, 공급자 키는 공개 설명이나 검토 메모에 기록하지 않습니다.

### App Store Connect 비공개 심사 안내 메모

Apple은 메모 저장 시에도 심사 담당자의 이름, 성, 이메일, 국제 형식 전화번호를 모두 요구한다. 해당 연락처와 보호자 이메일 조건에서 검증한 Apple 전용 심사 계정이 준비되면 아래 메모를 저장한다. 전용 패스는 심사 전용 비밀번호 입력란에만 넣는다.

> AI Story Book is an invitation-only free beta. New purchases, physical book orders, and photo upload are unavailable. Use fictional sample content for review.
>
> To use the dedicated review access code, tap “기존 계정 복구하기” (Recover an existing account) on the welcome screen. Enter the code in “복구 코드” and tap “계정 복구”. Follow the on-screen confirmation for the newly displayed recovery code.
>
> Create a fictional Korean watercolor story for ages 7–9, select 12 pages, and tap “무료 첫 동화 만들기”. Story and illustration generation can take about ten minutes. “서재를 둘러보며 기다리기” returns to the library while generation continues. Open the completed book, navigate to page 12, and tap Play to check the Korean narration. Narrator and style settings are available in Settings.
>
> Support: https://ai-story-book-support.vercel.app/support/
>
> Account and data deletion: https://ai-story-book-support.vercel.app/delete-account/

## Paid-release follow-up only

- [ ] Stable billing account identifier and real sandbox purchase/restore/refund tests
- [ ] Store products, receipt verification and server notifications verified before enabling new purchases

## Official requirements checked 2026-09-06

- [Apple screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/): Dynamic Island medium iPhone and 13-inch iPad requirements verified on 2026-11-11.
- [Apple platform information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/): support URL must lead to actual contact information.
- [Apple app privacy](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/): required policy URL and accurate app/partner data disclosures.
- [Google account deletion](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en): apps offering account creation must support in-app and external deletion requests. This product has server accounts and recovery across devices, so prepare that pathway rather than assume an anonymous-entry exemption.
- [Google personal account testing](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en): personal accounts created after 2023-11-13 require at least 12 opted-in testers continuously for 14 days before applying for production access. This account's applicability is not yet verified; automated E2E does not substitute for that test.
