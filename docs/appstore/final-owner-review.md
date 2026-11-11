# AI 동화책 제한 베타 최종 확인

이름 **AI 동화책 / AI Story Book**, iOS TestFlight·Android 비공개 테스트 등록 및 업로드, 개인정보 개정 방향과 백업 보관 기준을 운영자가 승인했다. 새 첫 권 생성 및 마지막 쪽 낭독 검증 뒤 배포 서명과 업로드를 진행한다.

함께 볼 자료: [7–9세 운영 동화 본문·삽화](../acceptance/2026-11-09-operating-owner-one-book/review.html) · [Android 12쪽 재생 화면](../acceptance/2026-11-09-public-api-narration/physical/android-playing.png) · [두 실기기 결과](../RELEASE_PREPARATION.md#2026-11-09-스토어-등록-전-검토). 공개 주소에서 기존 책의 마지막 쪽 재생을 확인했다. 새 초대 계정의 생성·새 낭독 시험과는 별도다.

## 1. 스토어 등록과 iOS 배포 서명

Apple Developer 팀 `D3NF387JDZ`에 `com.storybook.aiStoryBook`을 등록했고 App Store Connect에 한국어 앱 레코드를 만들었다. 앱 전용 App Store 프로파일을 내려받아 기존 Apple Distribution 인증서, 팀과 앱 식별자, 만료일, `get-task-allow=false`를 대조했다. Xcode에서 같은 팀 계정의 접근을 확인했다. [TestFlight 앱 레코드](https://appstoreconnect.apple.com/teams/74d913eb-ccc3-4480-a49b-017f1f11ec91/apps/6832540776/testflight)

개정 방침이 포함된 새 iOS 아카이브와 서명된 Android AAB를 준비했다. 실제 첫 권 검증 뒤 iOS 서명과 TestFlight 업로드를 진행한다. Play에는 `com.storybook.ai_story_book` 등록 필드를 입력했다. 개발자 정책 및 미국 수출 규정 준수 선언은 계정 소유자의 확인이 필요하다. [Apple 배포 프로파일 안내](https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile) · [로컬 서명 내보내기 설정](ios-export-options.plist)

## 2. 개인정보처리방침 개정 검토

개정 방침을 앱 원본과 공개 페이지에 반영했다. 사진 기능 상태, 외부 처리 업체·위치, 백업 보관과 복구 범위를 명시했다. 아래는 개정의 검토 근거다. [공개 개인정보처리방침](https://ai-story-book-support.vercel.app/privacy/) · [앱 원본](../../apps/mobile/assets/legal/privacy.ko.json)

**3. 외부 처리와 국외 이전**

> 동화를 만들거나 읽어주기를 요청하면 주제, 별명, 연령대, 이야기 문장과 필요한 그림 참조를 암호화된 연결로 OpenAI에 전달합니다. OpenAI는 글·그림 생성과 검수, 음성 합성에 이 정보를 처리합니다. 사진 업로드는 이번 제한 베타에서 제공하지 않습니다. 운영과 장애 복구에는 Google Cloud의 미국 서버와 비공개 저장소를, 서재와 계정 운영에는 Neon의 데이터베이스를 사용합니다.
>
> 동화 만들기와 새 낭독을 요청하지 않으면 해당 요청의 AI 처리는 시작되지 않습니다. 계정·서재 제공에 필요한 외부 서버 처리의 중단을 원하시면 설정에서 계정 삭제를 요청하거나 개인정보 문의처에 연락해 주세요. 처리를 중단하면 계정과 서재를 이용할 수 없습니다.

| 받는 곳 | 이전되는 정보와 목적 | 위치·시점·문의 |
|---|---|---|
| OpenAI API | 가상 인물 또는 이용자 입력, 연령대, 생성 글과 이미지 참조, 낭독할 문장과 음성 설정. 글·그림 생성, 검수, 음성 합성 | 기능 요청 시 HTTPS/WSS. AI Story Book Beta 프로젝트 화면에 `Global`이 표시됐다. 특정 국가 한 곳에 한정해 처리한다고 기재하지 않는다. 계약상 법인 및 실제 보유 조건은 계정에 적용된 범위로 확정한다. [처리 계약](https://openai.com/policies/data-processing-addendum/) · [처리 위치](https://openai.com/policies/sub-processor-list/) · [보유 설정](https://developers.openai.com/api/docs/guides/your-data) |
| Google Cloud | 앱 요청, 운영에 필요한 처리 정보, 비공개 미디어, 복구 백업과 삭제 복구 기록 | 요청·저장·백업 시, 미국 `us-central1`에서 운영. 계약 법인 및 문의처는 [Google Cloud 처리 조건](https://cloud.google.com/privacy/gdpr)과 운영 계정 기준으로 대조 |
| Neon | 계정 식별자, 보호자 동의, 프로필, 서재·독서 기록, 작업 메타데이터. 관계형 DB 운영 | 앱에서 해당 정보를 기록하거나 조회할 때 암호화 연결. 현재 운영 연결의 싱가포르 리전을 확인했다. `privacy@neon.tech`. [처리 계약](https://neon.com/pdf/DPA.pdf) |

**4. 보관과 삭제**

> 계정과 서재에 필요한 동화, 그림, 낭독과 독서 기록은 서비스를 이용하는 동안 보관합니다. 계정 삭제나 동의 철회로 처리 근거가 없어지면 대상 정보를 서비스에서 제거하고 파일 파기를 재시도합니다. 다른 사람이 공유 링크로 이미 저장한 사본은 회수할 수 없습니다.
>
> 장애 복구용 백업은 서비스 원본과 분리합니다. 백업을 복원할 때는 최신 삭제·동의 철회·인증 폐기 기록을 적용해 삭제된 내용이나 폐기된 인증을 다시 사용할 수 없게 합니다. 이전 계정 인증의 재사용을 막기 위한 최소 폐기 기록은 동화·사진·프로필과 분리해 보관합니다.

**백업 적용 결과.** 정기 원격 백업의 30일 만료와 삭제 후 7일 복구 설정을 읽어 확인했다. 가상 파일을 삭제하고 같은 내용으로 복구했다. VM의 정기 정리 타이머도 활성화했고 최초 실행을 확인했다. 오래된 사본의 삭제는 새 백업이 원격에서 검증된 경우에만 실행한다. [백업 운영 절차](../BACKUP_RESTORE.md#정기-백업-보관-기간)

## 테스트 트랙을 열기 전 운영 확인

- 운영 VM의 별도 프로세스에서 초대된 가상 계정은 무료 첫 권 이용권 1개를 받았고 미초대 계정은 무료 첫 권이 표시되지 않았다. 순차 생성 재현은 9·10·11쪽 인물 판정 이후 보완 전에 시간을 소진했다. 동시 생성 2개 시험은 473.28초 안에 보완과 재검수를 수행했지만 재검수에서 9·12쪽 행동 불일치가 새로 발견됐다. 프롬프트의 줄 순서를 일치시키고 구형 순서에서도 인물 정보를 읽도록 보완했다. [시간 초과 진단](../acceptance/2026-11-09-store-first-book-diagnostic/result.json) · [동시 생성 진단](../acceptance/2026-11-09-store-first-book-concurrent/result.json)
- 공개 API의 무료 첫 권과 초대 안내는 꺼져 있다. 개인정보 개정 공개와 최종 검토 뒤, 기존 `invite_only`를 유지하면서 API와 워커 양쪽에 동일한 설정을 적용한다. 신규 구매·사진은 비활성화하고 초대 계정만 허용한다. 일일 운영 생성 한도 1은 이번 시험을 위해 높이지 않았다.
- 첫 권 12쪽을 그날 새로 생성하고 전부 읽어 주려면 공유 한도에서 캐릭터 1회·책 1회·낭독 12회가 필요하다. 사전 검사 최소값은 14이고, 합성 재시도는 추가로 계산된다. 초기에는 초대 계정 수를 제한하고 승인된 비용 범위에 맞춰 운영 생성 한도를 적용한다.
- 전환 뒤 공개 HTTPS 준비 상태와 워커 응답, 초대·미초대 계정에서 생성 가능 여부를 확인한다. 검사가 실패하면 이전 환경을 복구한다. 테스트 트랙 업로드와 외부 테스터 초대는 이 확인 뒤 진행한다.
