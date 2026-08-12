# 실키 발급·주입 가이드 (창업자용, 2026-08-11)

> 최종 E2E와 출시에 필요한 외부 자격증명을 **처음 하는 사람 기준**으로 정리.
> ⚠️ **절대 규칙**: 발급받은 키는 `apps/api/.env` 파일에만 넣는다.
> 채팅·보고서·커밋·스크린샷에 키 원문을 붙여넣지 않는다. (구현자/CTO에게는 "넣어놨다"고만 알리면 됨)

---

## 0. 키를 넣는 방법 (공통 — 5분)

1. 터미널을 열고:
   ```bash
   cd ~/Desktop/ai-story-book/apps/api
   ls -la .env
   ```
   - `.env`가 **없다고 나오면**: `cp .env.example .env` 로 생성.
   - 있으면 그대로 다음 단계로.
2. 편집기로 연다: `open -e .env` (텍스트 편집기가 열림)
3. 아래 각 섹션에서 발급받은 값을 해당 줄에 붙여넣고 저장. 예:
   ```
   LLM_API_KEY=          ←  이 줄을
   LLM_API_KEY=sk-proj-abc123...   ←  이렇게 (따옴표·공백 없이)
   ```
4. 절대 커밋되지 않는지 확인(한 번만):
   ```bash
   cd ~/Desktop/ai-story-book && git check-ignore apps/api/.env && echo "안전: git이 무시함"
   ```
5. 키를 바꾼 뒤에는 **API 서버·워커를 재시작**해야 반영된다.
   (구현자가 스택을 띄우니, 최종 E2E 때는 "키 넣어놨다"고만 전달하면 됨)

---

## 1. 지금 필수 — 최종 E2E용

### 1-1. OpenAI 키 (스토리 생성 + 발음 평가 STT — 키 1개로 2역)

**어디서**: https://platform.openai.com
1. 회원가입/로그인 (구글 계정 연동 가능)
2. 좌측 상단 톱니바퀴(Settings) → **Billing** → *Add payment method* 로 카드 등록
   → *Add to credit balance* 로 **$10 충전** (최종 E2E 10권 기준 충분)
3. 좌측 메뉴 **API keys** → **+ Create new secret key** → 이름 `ai-story-book` → Create
4. `sk-proj-...` 로 시작하는 키가 **한 번만** 표시됨 → 즉시 복사
5. `.env`에 기입:
   ```
   LLM_PROVIDER=openai
   LLM_API_KEY=sk-proj-여기에붙여넣기
   LLM_MODEL=gpt-4o-mini
   STT_PROVIDER=openai
   STT_API_KEY=sk-proj-여기에붙여넣기      ← LLM과 같은 키
   ```

### 1-2. Google Gemini 키 (이미지 생성 — 아이 얼굴 보존, 권장 프로바이더)

**어디서**: https://aistudio.google.com
1. 구글 계정으로 로그인 → 좌측 **Get API key** → **Create API key**
2. 프로젝트 선택(없으면 자동 생성) → 키 복사 (`AIza...` 형태)
3. 이미지 생성은 유료라 **결제 연결 필요**: 키 생성 화면에서 *Set up billing* 안내를
   따라 Google Cloud 결제 계정에 카드 등록 (단가 ~$0.039/장, 1권 9장 ≈ $0.35)
4. `.env`에 기입:
   ```
   IMAGE_PROVIDER=gemini
   IMAGE_API_KEY=AIza여기에붙여넣기
   IMAGE_MODEL=gemini-3-pro-image-preview
   ```
> 참고: Gemini에서는 **인페인트(부분 재생성)가 지원되지 않아 앱이 해당 버튼을 자동으로
> 숨긴다** — 이건 설계된 동작(409 INPAINT_UNSUPPORTED). 인페인트까지 라이브로 보려면
> 아래 2-1 fal 키로 프로바이더를 잠시 바꿔 별도 테스트한다.

### 1-3. Apple IAP 샌드박스 (iOS 결제 테스트 — 위조 영수증 커버리지의 유일한 해소 경로)

**선행**: Apple Developer Program 가입 — https://developer.apple.com/programs/
- Apple ID로 로그인 → Enroll → 개인(Individual) 선택 → **연 $99** 결제 → 승인까지 1~2일

가입 승인 후 **App Store Connect** (https://appstoreconnect.apple.com):
1. **앱 등록**: 나의 앱 → `+` → 신규 앱 → 번들 ID 선택(Xcode 프로젝트의 번들 ID와 동일해야 함)
2. **구독 상품 생성**: 앱 → 수익화 → 구독 → 구독 그룹 만들기 → 상품 추가
   (상품 ID는 모바일 코드가 참조하는 ID와 일치 필요 — 구현자에게 상품 ID 목록 요청)
3. **공유 암호(Shared Secret) 발급**: 앱 → 일반 → **앱 정보** → *App 전용 공유 암호(App-Specific
   Shared Secret)* → 관리 → 생성 → 32자리 문자열 복사
4. `.env`에 기입:
   ```
   APPLE_IAP_SHARED_SECRET=여기에붙여넣기
   ```
5. **샌드박스 테스터 만들기**: App Store Connect → **사용자 및 액세스** → **Sandbox** 탭 →
   테스터 `+` → **실계정과 다른 새 이메일**로 생성 (예: `mytest+sandbox@gmail.com`)
6. **실기기(iPhone)에서**: 설정 → App Store → 맨 아래 **샌드박스 계정** → 위 테스터로 로그인
   → 이후 앱에서 결제 시 실제 청구 없이 샌드박스 결제가 일어남

### 1-4. Google Play (Android 결제 테스트)

**선행**: Play Console 가입 — https://play.google.com/console
- 구글 계정 → 개발자 계정 만들기(개인) → **$25 1회** 결제 → 신원 확인(1~3일)

가입 후:
1. **앱 만들기** → 앱 이름 `AI Story Book`, 패키지명은 모바일 프로젝트의
   `applicationId`와 동일(구현자에게 확인)
2. **서비스 계정 만들기** (서버가 영수증을 검증할 때 쓰는 로봇 계정):
   a. https://console.cloud.google.com → 프로젝트 선택 → **IAM 및 관리자** → **서비스 계정**
      → 만들기 → 이름 `iap-verifier` → 완료
   b. 만든 계정 클릭 → **키** 탭 → 키 추가 → **JSON** → 파일이 다운로드됨
   c. 그 JSON 파일을 안전한 곳에 두고(예: `~/secrets/play-sa.json` — **리포 폴더 밖!**):
      ```
      GOOGLE_PLAY_PACKAGE_NAME=앱패키지명
      GOOGLE_PLAY_SERVICE_ACCOUNT_FILE=/Users/jmac/secrets/play-sa.json
      ```
   d. Play Console → **사용자 및 권한** → 사용자 초대 → 서비스 계정 이메일
      (`iap-verifier@...iam.gserviceaccount.com`) 입력 → 권한에서 **금융 데이터 보기** 포함 → 초대
3. **구독 상품 생성**: Play Console → 앱 → 수익 창출 → 구독 → 만들기 (상품 ID는 iOS와 동일 체계)
4. **라이선스 테스터**: Play Console 첫 화면(계정 수준) → 설정 → **라이선스 테스트** →
   본인 구글 계정 이메일 추가 → 이 계정으로 기기에서 테스트하면 실청구 없음

---

## 2. 선택 — 있으면 최종 E2E 커버리지가 늘어나는 것

### 2-1. fal.ai 키 (인페인트 부분 재생성 라이브 테스트용)

https://fal.ai → GitHub/구글로 로그인 → 우상단 프로필 → **Keys** → *Add key* → 복사
→ 잔액 충전($5면 충분). 인페인트 테스트할 때만:
```
IMAGE_PROVIDER=fal
IMAGE_API_KEY=fal키
```
(테스트 후 다시 `gemini`로 되돌리기)

### 2-2. ElevenLabs 키 (오디오 낭독 TTS)

> 현재 제품 결정(G9)은 **GA에서 오디오 비활성 출시**. 이 키는 "오디오 워커 디스패치
> 라이브 증거"(이번 웨이브에서 유일하게 못 만든 증거)를 만들고 싶을 때만 필요.

https://elevenlabs.io → 가입 → 우하단 프로필 → **API Keys** → 생성 → 복사:
```
AUDIO_FEATURE_ENABLED=true      ← 테스트 동안만
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=여기에
```

### 2-3. Printful 키 (실물 인쇄 POD — 출시 후여도 무방)

https://www.printful.com → 가입 → **Stores** → *Choose platform* → **API** 스토어 생성
→ Settings → API → **Private token 생성** → 복사:
```
PRINTFUL_API_KEY=여기에
```
Store ID는 대시보드 URL의 숫자. 상품(sync variant) 연결은 구현자와 함께 진행 권장.

---

## 3. 나중에 — 운영 서버 배포 시 (지금 아님)

서버를 마련한 뒤 배포 단계에서 함께 설정(그때 CTO가 다시 안내):
- `DATABASE_URL` 운영 비밀번호 / `S3_*` 운영 스토리지(R2 등) 키
- `ADMIN_API_KEY`·`IAP_WEBHOOK_SECRET` — 터미널에서 `openssl rand -hex 32` 로 생성한 랜덤 문자열
- `CORS_ORIGINS`·`SHARE_BASE_URL` — 실 도메인(aistorybook.com)
- GitHub 저장소의 `DEPLOY_*` 시크릿 + `DEPLOY_ENABLED=true`
- 배포 직후 `scripts/check-bucket-exposure.sh` 1회 실행(아동 사진/음성 버킷 공개 여부 — GA 전 필수)

---

## 4. 다 넣었는지 셀프 체크

```bash
cd ~/Desktop/ai-story-book/apps/api
grep -c "CHANGE_ME\|=$" .env    # 숫자가 줄어들수록 채워진 것 (0일 필요는 없음 — 선택 항목 존재)
```
필수 4종 체크리스트:
- [ ] `LLM_API_KEY` (OpenAI)
- [ ] `IMAGE_API_KEY` + `IMAGE_PROVIDER=gemini`
- [ ] `APPLE_IAP_SHARED_SECRET` + 샌드박스 테스터 계정 1개
- [ ] `GOOGLE_PLAY_SERVICE_ACCOUNT_FILE` + 패키지명 (Android까지 할 경우)

완료되면 구현자에게: **"실키 4종(.env) + IAP 샌드박스 테스터 준비됨, 최종 E2E 시작"** 만 전달.
(키 원문은 절대 전달하지 않는다 — 구현자는 .env를 읽어서 쓰면 된다)
