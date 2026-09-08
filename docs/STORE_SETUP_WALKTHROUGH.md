# 유료 전환 시 스토어 상품 등록 참고

> 2026-09-08 최종 범위: 디지털 동화책·디지털 결제·음성과 운영 연결 준비. 실물 제작·배송은 제공하지 않습니다. 신규 결제는 보류하며 최신 구현·외부 조건은 [디지털 서비스 현황](FEATURE_WIRING_2026-09-08.md)을 따릅니다.

> 2026-09-06: 현재 무료 제한 베타는 새 구매를 비활성화합니다. 아래 구독·크레딧팩·영수증 자격증명·샌드박스 결제 절차는 향후 유료 전환용이며 이번 베타의 선행조건이 아닙니다. 체크박스는 계정의 현재 상태를 확인한 기록이 아니라 작업용 양식입니다. 실제 미완료 항목은 [OWNER_LAUNCH_RUNBOOK.md](OWNER_LAUNCH_RUNBOOK.md)를 따릅니다.

> App Store Connect(iOS) → Google Play Console(Android) 순서. 화면을 보며 한 줄씩 따라 하세요.
> **상품 ID는 반드시 아래와 똑같이** 입력(오타 시 앱이 상품을 못 찾아 결제 전량 실패):
> 구독 `subscription_basic` `subscription_premium` · 크레딧팩 `credit_pack_1` `credit_pack_5` `credit_pack_10`
> iOS 번들 ID `com.storybook.aiStoryBook` · Android 패키지 `com.storybook.ai_story_book`

---

# 1부. iOS — App Store Connect

## 사전 1단계: 번들 ID 먼저 등록 (아직 안 했다면)
앱을 만들 때 번들 ID 드롭다운에 `com.storybook.aiStoryBook`이 안 보이면 여기서 먼저 등록합니다.

1. https://developer.apple.com/account 접속 → Apple ID 로그인
2. 왼쪽 **Certificates, IDs & Profiles** 클릭
3. 왼쪽 **Identifiers** → 오른쪽 파란 **＋** 버튼
4. **App IDs** 선택 → Continue → **App** 선택 → Continue
5. 입력:
   - Description: `AI Story Book`
   - Bundle ID: **Explicit** 선택 → `com.storybook.aiStoryBook` 입력
   - 아래 Capabilities 목록에서 **In-App Purchase** 체크
6. Continue → Register

## A. 앱 만들기
1. https://appstoreconnect.apple.com 접속 → 로그인
2. 상단 **나의 앱(Apps)** 클릭
3. 왼쪽 위 파란 **＋** → **신규 앱(New App)**
4. 팝업 입력:
   - 플랫폼: **iOS** 체크
   - 이름: `AI Story Book` (스토어에 보일 이름)
   - 기본 언어: 한국어(또는 English)
   - 번들 ID: 드롭다운에서 **com.storybook.aiStoryBook** 선택
   - SKU: 아무 고유 문자열 — 예: `aistorybook001`
   - 사용자 액세스: 전체 액세스
5. **생성** 클릭 → 앱이 만들어집니다.

현재 상품 정본은 `docs/appstore/iap-catalog.json`입니다. 실제 결제 금액은 각 스토어에서 확인하며 앱도 스토어의 현지화된 가격을 표시합니다. 아래 계정 생성·상품 등록은 공동 최종 확인 이후 진행합니다.

## B. 구독 상품 2개 만들기
1. 방금 만든 앱 클릭 → 왼쪽 메뉴 **수익화(Monetization)** → **구독(Subscriptions)**
2. **구독 그룹**이 없으면 먼저: **구독 그룹 생성(Create)** → 그룹 참조 이름 `AI Story Book 구독` → 생성
3. 그 그룹 안에서 **＋**(구독 추가):
   - 참조 이름(Reference Name): `Basic` (내부용, 사용자 안 보임)
   - **제품 ID(Product ID): `subscription_basic`** ← 정확히
   - 생성
4. 만들어진 Basic 구독 상세에서:
   - 구독 기간: **1개월**
   - **구독 가격**: 가격 추가 → ₩24,900 (월 5권, 2026-09-08 원가 재검토 기준)
   - **앱 스토어 현지화(Localization)**: 표시 이름 `베이직`, 설명 입력(한국어). 필요 시 영어/일본어도 추가
   - 리뷰 정보(스크린샷 등)는 앱 제출 단계에서 채워도 됩니다
5. 같은 그룹에 **＋** 다시 → premium 반복:
   - 참조 이름 `Premium` · **제품 ID `subscription_premium`** · ₩44,900 (월 10권)

## C. 크레딧팩 3개 만들기 (소모성 = Consumable)
1. 왼쪽 메뉴 **수익화(Monetization)** → **인앱 구입(In-App Purchases)**
2. **＋**(생성) → 유형에서 **소모품(Consumable)** 선택
   - 참조 이름: `Credit Pack 1`
   - **제품 ID: `credit_pack_1`**
   - 생성 → 가격 tier 선택 + 현지화(이름 `크레딧 1개`, 설명)
3. 같은 방식으로 2개 더:
   - **`credit_pack_5`** (크레딧 5개)
   - **`credit_pack_10`** (크레딧 10개)

## D. 공유 암호(App-Specific Shared Secret) 발급
> 서버가 애플 영수증을 검증할 때 쓰는 비밀번호. `apps/api/.env`의 `APPLE_IAP_SHARED_SECRET`에 넣습니다.

1. 왼쪽 **수익화 → 인앱 구입(In-App Purchases)** 페이지로 이동
2. 페이지 오른쪽 위 **App 전용 공유 암호(App-Specific Shared Secret)** 링크 클릭
   (버전에 따라 "App-Specific Shared Secret" / "공유 암호 관리")
3. **생성** → 나온 **32자리 문자열 복사**
4. 그 값을 `apps/api/.env`에 붙여넣기:
   ```
   APPLE_IAP_SHARED_SECRET=여기에32자리
   ```
   ⚠ 이 값은 채팅·커밋에 붙여넣지 마세요.

## E. 샌드박스 테스터 만들기 (무료 결제 테스트용)
1. App Store Connect 첫 화면(왼쪽 위 로고 클릭) → **사용자 및 액세스(Users and Access)**
2. 상단 탭 **샌드박스(Sandbox)** → **테스터(Testers)**
3. **＋** → 실제로 안 쓰는 **새 이메일**(예: 본인이메일+sandbox@gmail.com)·비밀번호·지역(대한민국) 입력 → 생성
4. **iPhone에서**: 설정 → App Store → 맨 아래로 스크롤 → **샌드박스 계정** → 위에서 만든 테스터로 로그인
   - 이제 앱에서 결제 시 실제 청구 없이 샌드박스 결제가 됩니다.

### ✅ iOS 완료 체크
- [ ] 앱 등록됨(번들 ID 맞음)
- [ ] 구독 2개(`subscription_basic`, `subscription_premium`)
- [ ] 크레딧팩 3개(`credit_pack_1/5/10`)
- [ ] 공유 암호 32자리 → `.env`에
- [ ] 샌드박스 테스터 1개 + iPhone에 로그인

---

# 2부. Android — Google Play Console

> Play Console 가입($25, 신원확인 1~3일)이 끝난 뒤 진행. 상품 ID는 iOS와 **동일**하게.

## A. 앱 만들기
1. https://play.google.com/console 접속 → 로그인
2. **앱 만들기(Create app)**
3. 입력: 앱 이름 `AI Story Book` · 기본 언어 · 앱/게임=앱 · 무료/유료=무료(인앱결제 있음) → 만들기
4. (패키지명 `com.storybook.ai_story_book`은 첫 .aab 업로드 시 확정됩니다 — 구현자가 빌드한 .aab를 올릴 때 자동으로 잡힙니다)

## B. 구독 만들기
1. 왼쪽 메뉴 **수익 창출(Monetize) → 상품(Products) → 구독(Subscriptions)**
2. **구독 만들기** → **상품 ID `subscription_basic`** 입력(생성 후 변경 불가) → 이름·혜택·기본 요금제(1개월)·가격 설정
3. 다시 → **`subscription_premium`** 반복

## C. 크레딧팩(관리 상품 = 소모성) 만들기
1. **수익 창출 → 상품 → 인앱 상품(In-app products)**
2. **상품 만들기** → **상품 ID `credit_pack_1`** → 이름·가격 → 활성화
3. `credit_pack_5`, `credit_pack_10` 반복

## D. 서비스 계정 JSON (서버 영수증 검증용)
> 아래는 유료 전환 시 영수증 검증용 절차입니다. 현재 키 연결 상태는 [REAL_KEYS_SETUP_GUIDE.md](REAL_KEYS_SETUP_GUIDE.md)를 참조합니다.
1. https://console.cloud.google.com → IAM 및 관리자 → 서비스 계정 → 만들기(`iap-verifier`)
2. 그 계정 → 키 탭 → 키 추가 → **JSON** → 다운로드 → 리포 **밖**에 저장(예: `~/secrets/play-sa.json`)
3. Play Console → 사용자 및 권한 → 이 서비스 계정 이메일 초대(금융 데이터 보기 권한 포함)
4. `apps/api/.env`:
   ```
   GOOGLE_PLAY_PACKAGE_NAME=com.storybook.ai_story_book
   GOOGLE_PLAY_SERVICE_ACCOUNT_FILE=/Users/…/secrets/play-sa.json
   ```

## E. 라이선스 테스터 (무료 테스트)
1. Play Console 첫 화면(계정 수준) → 설정 → **라이선스 테스트** → 본인 구글 계정 이메일 추가

### ✅ Android 완료 체크
- [ ] 앱 생성
- [ ] 구독 2개 + 인앱상품 3개(iOS와 동일 ID)
- [ ] 서비스 계정 JSON → `.env`에 경로
- [ ] 라이선스 테스터 등록

---

## 향후 유료 전환 검증
유료 기능을 실제로 활성화하는 단계에서 Apple/Google 영수증 검증 설정과 테스트 계정·실기기가 준비되면 결제·환불·복원 검증을 진행합니다. 현재 무료 베타는 이 절차를 기다리는 상태가 아닙니다.

막히는 지점은 **단계 기호**(예: "1부 B-3", "2부 D-2")로 말하면 그 화면을 더 풀어 설명합니다.
