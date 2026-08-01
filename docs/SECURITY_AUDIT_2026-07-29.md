# CTO 전용 보안 감사 — 출시 전 (2026-07-29)

> **범위**: 코드베이스 전체(변경분 아님), 방어보안 6렌즈(authz·시크릿/fail-open·웹표면·PII/아동데이터·레이트리밋/IAP·의존성/인프라) → 3렌즈 반증 + 머더보드. 20 에이전트.
> **판정**: ✅ **Critical/High 0.** 확정 11건(중간 4·낮음 7) + 기각 2건. 대규모 기능 하드닝 뒤라 인증·CORS·IAP 리플레이·계정삭제 등 핵심 표면은 견고. 아래 4개 중간 건은 출시 전 정리 권고(대부분 저렴).

## OWASP 커버리지 (깨보고 안전 확인한 것 — 강한 지점)
- **A01 접근제어**: 17개 라우터 object-level authz를 negative 테스트 — books/characters/pod/library/growth 등 소유권 필터 확인. (예외 2건은 §refuted)
- **A02 암호화/PII**: 계정 전체 삭제가 27개 테이블 + 스토리지(파이프라인 이미지 역산·characters·voice-samples) 파기 확인.
- **A05 보안설정**: `debug=False` 기본, CORS 정확 origin 화이트리스트(suffix/prefix 아님), prod 미설정 시 와일드카드 폴백 없음.
- **A07 인증/IAP**: 영수증 리플레이 방어 견고 — `(platform, store_transaction_id)` UniqueConstraint. 웹훅 시크릿.
- **시크릿**: `infra/.env` gitignore로 미추적(커밋된 시크릿 0), Dockerfile non-root(appuser).

## 확정 11건


### 🟡 MEDIUM

**1. 음성 프로필 단건 삭제 시 S3 오디오 샘플이 파기되지 않음 (가족 음성 잔존)**
- `apps/api/src/routers/voice_profiles.py:303` · A02 Cryptographic Failures (민감 데이터 보존·파기)
- 취약: delete_voice_profile은 DB 행만 db.delete(profile)로 지우고, sample_audio_url(voice-samples/{user_key}/...에 업로드된 실제 오디오)에 대한 storage 삭제를 전혀 호출하지 않는다. 형제인 캐릭터 단건 삭제(characters.py:504)와 계정 삭제(users.py:127 voice-samples/{user_key}/ 프리픽스 파기)는 스토리지를 지우지만, 음성 프로필 단건 삭제만 스토리지 정리가 누락됐다.
- 공격경로: 사용자가 앱에서 '가족 목소리' 프로필을 삭제(DELETE /v1/voice-profiles/{id})하면 목록에서 사라져 지워졌다고 인지하지만, 녹음된 오디오 객체는 공개 버킷에 그대로 남는다. sample_audio_url은 만료 없는 안정 URL이라 링크가 유출·캐시되면 계속 접근 가능.
- 영향: 보호자/아동 등 가족의 음성(biometric-adjacent PII)이 사용자 명시 삭제 후에도 스토리지에 영구 잔존 → PIPA/GDPR 파기 의무 위반. 계정 전체 삭제로는 회수되지만 단건 삭제 경로는 조용히 새는 잔존 데이터.
- 수정: delete 커밋 전 profile.sample_audio_url을 key_from_public_url로 역산해 delete_keys([key])(또는 delete_prefix) 호출, 실패키를 로깅/표면화. 계정 삭제·캐릭터 삭제의 실패-표면화 계약과 동일하게 처리.

**2. python-multipart 0.0.12 (CVE-2024-53981 DoS) 고정 — 도달 가능한 3개 업로드 엔드포인트, CI가 HIGH를 차단 안 함**
- `apps/api/requirements.txt:3` · A06 Vulnerable and Outdated Components
- 취약: python-multipart==0.0.12로 핀. 이 버전은 CVE-2024-53981(GHSA-59g5-xgcq-4qw3, <0.0.18 영향)에 취약 — 악의적 multipart/form-data 경계(boundary)를 파싱할 때 파서가 과도한 CPU를 소모해 async 이벤트루프를 블록. FastAPI가 이 라이브러리로 폼/파일을 파싱한다.
- 공격경로: X-User-Key는 클라이언트가 자체 발급하는 UUID라 사실상 미인증. 공격자가 /v1/pronunciation(audio_file, routers/pronunciation.py:127), /v1/voice-profiles(sample, voice_profiles.py:110), /v1/books 인페인트(mask, books.py:887)로 변형된 multipart 바디를 보내 워커 이벤트루프를 스톨. nginx 10r/s + 앱 rate limit이 볼륨은 줄이나 요청당 CPU 소모형 DoS는 한도 내에서도 성립. CI Trivy fs 스캔은 severity를 CRITICAL로만 blocking(ci.yml:353)해 HIGH(7.5)인 이 CVE는 통과.
- 영향: 미인증에 가까운 요청으로 API/워커 replica의 async 루프를 점유 → 서비스 저하/거부(출시 임박 아동 앱).
- 수정: python-multipart를 >=0.0.18로 올림. 겸해 Trivy fs 게이트에 HIGH를 blocking으로 포함하거나 safety 게이트가 실제로 이 GHSA를 잡는지 확인.

**3. CI 서드파티 액션이 가변 태그로 고정 — 프로덕션 배포 시크릿 취급 액션 포함(SHA 핀 아님)**
- `.github/workflows/ci.yml:467` · A08 Software and Data Integrity Failures
- 취약: appleboy/ssh-action@v1.2.5, codecov/codecov-action@v5, gitleaks/gitleaks-action@v2, subosito/flutter-action@v2, docker/*-action@v3/@v6 모두 가변 태그(major/version 태그) 참조 — 커밋 SHA 핀이 아님. deploy 잡의 appleboy/ssh-action은 secrets.DEPLOY_HOST/DEPLOY_USER/DEPLOY_KEY(프로덕션 SSH 개인키)를 주입받는다.
- 공격경로: 액션 메인테이너 계정 탈취/악성 리태그 시 해당 태그가 악성 커밋을 가리키게 되고, 다음 CI 실행에서 임의 코드가 러너에서 실행 — deploy 잡은 프로덕션 SSH 키·GITHUB_TOKEN(packages:write)에 접근. codecov는 2021년 공급망 침해 이력이 있는 액션.
- 영향: CI 공급망 침해 시 프로덕션 서버 SSH 키·컨테이너 레지스트리 쓰기 권한 탈취 → 배포 파이프라인 장악.
- 수정: 신뢰 경계를 넘는 서드파티 액션(특히 appleboy/ssh-action, codecov, gitleaks, subosito)을 전체 커밋 SHA로 핀하고 dependabot/renovate로 업데이트 관리. GitHub 공식 액션도 SHA 핀 권장.

**4. 클라이언트 임의 X-User-Key 로테이션으로 신규가입 3크레딧 무한 발급 → 무제한 무료 AI 생성 비용** · **[수용 리스크]**
- `apps/api/src/services/credits.py:62` · A04 Insecure Design (anti-automation / unrestricted resource consumption)
- 취약: get_or_create_credits는 처음 보는 user_key에 무조건 3크레딧('신규 가입 보너스')을 지급한다. user_key는 core/dependencies.py에서 UUID 형식만 검증할 뿐 클라이언트가 임의로 정하는 값이고, 레이트리밋(rate_limit.py, per user_key 10/분)·일일 생성한도(books.py check_guardrails, per user_key 20/일)·무료플랜 월 2권 제한(_enforce_free_plan_create_limits)·IAP까지 모든 남용 통제가 동일한 로테이션 가능한 식별자에 묶여 있다. IP·디바이스·attestation 기반 스로틀이 코드 어디에도 없다.
- 공격경로: 공격자가 매 요청마다 새 UUID를 X-User-Key로 생성 → 각 키가 3크레딧을 받아 POST /v1/books로 책 2~3권 무료 생성(각 ~$0.32 LLM+이미지 비용) → 키 폐기·재생성 반복. 스크립트로 무한 반복 가능.
- 영향: 이미지/LLM API 비용의 무제한 소진(비용 기반 DoS·무료티어 Sybil 남용). 모든 rate-limit·daily-limit·free-plan 통제가 우회된다. 출시 시 청구서 폭증 리스크.
- 수정: 익명 키에 대한 anti-automation 계층 추가: (1) 크레딧 지급/생성 요청을 IP·디바이스 지문 기준으로도 스로틀, (2) 신규가입 보너스를 지연·검증(예: 최초 IAP 또는 디바이스 attestation 전에는 0~1로 축소), (3) 비용 유발 엔드포인트를 서버측 전역 예산 가드레일(production-ops 비용 가드)로 상한. 최소한 신규 user_key 생성률을 IP 단위로 제한.


### ⚪ LOW

**5. 예외 핸들러가 /share/{token} 경로를 미마스킹 로깅 — _redact_path 우회**
- `apps/api/src/main.py:344` · A09 Security Logging and Monitoring Failures
- 취약: AccessLogMiddleware는 _redact_path로 공유 토큰을 /share/{token}으로 가리지만, storybook_error_handler(322행)와 global_exception_handler(344행)는 path=request.url.path를 그대로 로깅한다. _redact_path의 명시 목적('공유 토큰을 로그에서 가린다 — 로그 유출 시 무인증 재생 방지')이 에러 경로에서만 무력화된다.
- 공격경로: /share/{token} 또는 /share/{token}/img/... 요청 처리 중 도메인 예외/미처리 예외가 발생하면(예: 공개 렌더의 DB 조회 실패) 원문 공유 토큰이 error/warning 로그에 그대로 기록된다.
- 영향: 공유 토큰(아동 동화 표지·본문 일러스트에 대한 무인증 capability)이 중앙 로그에 평문 잔존 → 로그 접근자가 링크를 재생. 코드가 이 토큰을 민감 자산으로 명시 취급했는데 에러 경로에서 방어가 깨진다.
- 수정: 두 예외 핸들러의 path= 인자를 _redact_path(request.url.path)로 교체(미들웨어와 동일 헬퍼 재사용).

**6. LLM JSON 파싱 실패 시 스토리 원문(아동 이름 포함)을 error 로그에 기록**
- `apps/api/src/services/llm.py:404` · A09 Security Logging and Monitoring Failures
- 취약: parse_json_response는 JSONDecodeError 시 logger.error(..., text=text[:500])로 LLM 원문 출력 500자를 기록한다. 이 함수는 스토리 생성·캐릭터 시트 파싱에 쓰이며, 스토리 텍스트는 주인공=아동 이름으로 개인화된 콘텐츠다. raw_output=text[:500]도 LLMError.details에 실린다.
- 공격경로: LLM이 스토리 생성 단계에서 마크다운/불완전 JSON을 반환(실환경에서 드물지 않음)하면 아동 이름이 포함된 스토리 본문이 error 레벨로 로그에 남는다.
- 영향: 아동 이름+개인화 스토리 콘텐츠가 중앙 로그에 무마스킹 기록 → 규제 민감 아동앱에서 A09 PII 로깅. 파싱 실패 경로라 빈도는 낮음.
- 수정: text 로깅을 길이/해시 또는 error 메시지만으로 축소하거나, 아동 이름 등 PII를 마스킹한 요약만 남긴다. raw_output은 클라이언트 응답으로 새지 않는지도 함께 확인.

**7. retell·character 생성이 크레딧 미과금 + 일일한도 미적용 — 10/분 rate-limit만으로 게이트되는 LLM/이미지 비용**
- `apps/api/src/routers/books.py:1118` · A04 Insecure Design (unmetered expensive operation)
- 취약: retell_book은 동기 LLM 호출(call_story_retext)을 수행하지만 use_credit도 check_guardrails(일일한도)도 호출하지 않는다('크레딧 미소모' 주석). retell 결과는 새 Book이므로 그 책을 다시 retell할 수 있어(retell-of-retell), 최초 1크레딧으로 만든 책 하나로 무한 무료 LLM 재생성이 가능하다. 마찬가지로 characters 라우터의 from-photo/from-drawing/from-text·character sheet 생성도 이미지/LLM 비용을 유발하나 크레딧 미과금(10/분 rate-limit·consent만 게이트).
- 공격경로: 자기 소유 책 1권 생성 후 /retell을 반복(또는 retell 결과를 재-retell), 혹은 /characters/from-photo|from-drawing를 반복 호출. 키당 10/분, 키 로테이션 시 그 이상.
- 영향: 크레딧 경제를 우회한 LLM·이미지 API 비용 소진. 키 로테이션 finding(credits.py:62)과 결합 시 증폭.
- 수정: retell과 이미지/LLM을 유발하는 character 생성 경로에도 use_credit(또는 별도 저비용 크레딧)과 check_guardrails 일일한도를 적용. 최소한 이들 경로를 create_book과 동일한 일일 생성 예산에 포함.

**8. 레이트리미터가 Redis 오류 시 fail-open — 서브크레딧 스로틀이 무음으로 비활성** · **[수용 리스크]**
- `apps/api/src/core/rate_limit.py:119` · A04 Insecure Design (fail-open control)
- 취약: check_rate_limit은 redis.RedisError를 잡아 경고만 로깅하고 요청을 통과시킨다(주석에 'fail open for availability' 명시). Redis 장애·연결 고갈·타임아웃 시 전 라우터의 10/분 스로틀이 사라진다. 크레딧을 소모하지 않는 비싼 경로(retell·character-from-photo/drawing/text·읽기 폭주·공유 토큰 추측)는 이때 완전 무제한이 된다.
- 공격경로: Redis 다운/포화 상태를 유발하거나 그 시점에 맞춰(또는 대량 트래픽으로 Redis를 밀어) 비싼·미과금 엔드포인트를 폭주시킨다.
- 영향: 장애 창에서 유일한 서브크레딧 단위 남용 방어가 사라져 LLM/이미지 비용 폭주·리소스 고갈. 신용카드 통제가 아닌 rate-limit에만 의존하는 엔드포인트가 무방비.
- 수정: 비용/보안 민감 엔드포인트는 fail-closed(Redis 불가 시 429 또는 대체 로컬 토큰버킷)로 전환하거나, 최소한 fail-open을 짧은 회로차단 창으로 한정. 크레딧 미과금 비싼 엔드포인트(retell·character 생성)에는 DB 기반 백업 카운터를 둔다.

**9. 예기치 못한 예외의 원문(str(e))이 잡 소유자에게 error_message로 노출** · **[수용 리스크]**
- `apps/api/src/services/orchestrator.py:484` · A05 Security Misconfiguration / A01 (self-scoped)
- 취약: 도메인 에러(StoryBookError)가 아닌 임의 예외 발생 시 `mark_job_failed(job_id, ErrorCode.UNKNOWN, str(e))`로 예외 원문을 그대로 job.error_message에 저장하고(orchestrator.py:484, 211), GET 잡 상태 조회가 이를 ErrorInfo.message로 클라이언트에 반환한다(books.py:672 `message=job.error_message`). regen 경로도 동일(books.py:425 `str(getattr(e,'message',e))[:300]`).
- 공격경로: 공격자가 자기 X-User-Key로 잡을 생성해 비도메인 예외(DB/드라이버/업스트림 httpx 오류 등)를 유발한 뒤, 소유자로서 GET /v1/books/{job_id} 상태를 폴링하면 300자 이내의 내부 예외 문자열을 읽는다. 소유권 체크는 통과(자기 잡).
- 영향: 자기 잡에 한정된 정보노출 — 내부 예외 메시지(SQLAlchemy 오류의 테이블/컬럼명, httpx가 담은 내부 URL, 업스트림 프로바이더 오류 본문 등)가 클라이언트로 새어 스택·인프라 정찰 단서를 준다. 타 사용자 데이터 유출은 아니며 전역 예외 핸들러(main.py:346, debug 게이트)와 달리 이 경로는 prod에서도 원문이 나간다. 시크릿 유출 가능성은 낮음(httpx 예외는 auth 헤더 미포함).
- 수정: orchestrator.py:484와 books.py:425/842의 비도메인 예외는 사용자향 error_message를 고정 문구(예: '생성 중 오류가 발생했습니다')로 두고 원문 str(e)는 logger로만 남긴다. 도메인 StoryBookError만 .message를 노출(이미 코드값·메시지가 통제됨).

**10. 운영에서 Swagger UI/OpenAPI 스키마가 무인증 공개 (앱·nginx 엣지 양쪽)** · **[수용 리스크]**
- `apps/api/src/main.py:198` · A05 Security Misconfiguration
- 취약: FastAPI(...) 생성 시 docs_url/redoc_url/openapi_url을 None으로 비활성화하지 않아 기본값(/docs, /redoc, /openapi.json)이 인증 없이 노출된다(main.py:198). 나아가 nginx도 location /docs 와 /openapi.json 블록을 인증·limit_req 없이 api_servers로 프록시한다(infra/nginx/nginx.conf:153, 다른 /v1/·/share/ 블록은 limit_req/limit_conn 적용). 전체 27개 라우터 표면, X-Admin-Key/X-Webhook-Token 등 보안 헤더 존재, IAP·POD·consent·users(데이터 삭제) 엔드포인트가 스키마로 완전 공개되고 엣지에서 rate limit도 없어 반복 조회 가능하다.
- 공격경로: 누구나 GET https://host/docs, GET https://host/openapi.json 을 무인증으로 호출해 전체 엔드포인트·스키마·파라미터·admin 인증 헤더 이름을 열람.
- 영향: 취약점 자체는 아니나 아동 PII·결제(IAP)·관리자 헤더를 다루는 출시 임박 공개 API에서 전체 공격 표면·admin 인증 헤더 이름을 정찰용으로 그대로 제공. 앱·엣지 두 계층 모두에서 노출돼 하드닝 관점의 표면 축소 대상.
- 수정: 운영(settings.debug=False)에서 `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` 또는 조건부 비활성화하고, nginx에서도 /docs·/openapi.json을 내부망 전용 deny 하거나 최소 limit_req 존 적용. 내부 문서가 필요하면 admin 인증 뒤로 게이트(/health/detailed와 동일 패턴). 계약 배포는 packages/shared/schema로 대체.

**11. 워크플로 레벨 permissions가 PR 테스트 잡에도 packages:write 부여 — 최소권한 위반** · **[수용 리스크]**
- `.github/workflows/ci.yml:19` · A05 Security Misconfiguration
- 취약: permissions: contents:read, packages:write, security-events:write가 워크플로 전역으로 선언돼 api-test·flutter-test·phase-gate·security-scan 모든 잡에 상속된다. 이 잡들은 pull_request에서도 실행되며 브랜치의 임의 테스트 코드를 구동하지만 packages:write가 필요 없다(레지스트리 푸시는 build 잡 전용).
- 공격경로: 동일 저장소 브랜치 PR(협업자/침해된 브랜치)은 GITHUB_TOKEN이 packages:write를 그대로 가짐. PR에서 도는 pytest가 임의 코드이므로 토큰으로 ghcr에 악성 이미지 푸시 가능(포크 PR은 read-only로 강등되어 해당 없음).
- 영향: 내부 협업자/침해 브랜치가 CI 토큰으로 컨테이너 레지스트리에 무단 푸시. 폭발 반경은 제한적이나 불필요 권한 노출.
- 수정: 전역 permissions를 contents:read로 낮추고 packages:write는 build 잡, security-events:write는 security-scan/build 잡에 job-level로만 부여.

---
## CTO 판단 — 자동 판정에 덧붙이는 것 (수용 근거의 적대 검증)

1. **#1 크레딧 cost-DoS를 '수용 리스크'로 묻지 말 것.** X-User-Key(클라 임의 UUID) 로테이션으로 신규 3크레딧을 무한 발급 → LLM/이미지 실비용 무제한 소진. 완전한 해법(디바이스 attestation)은 제품 결정이라 미루더라도, **출시 전 최소 조건 = 전역 일일 비용 예산 가드레일 + 알림**(production-ops)과 익명 가입 보너스 축소/지연. 가드레일 0으로 GA하면 청구서 폭증에 무방비.
2. **기각된 '아동 사진 공개 URL'은 접근제어 버그로는 기각이 맞다**(소유자 전용 반환·32bit 랜덤 키·익명 표면 미노출). 그러나 **그 밑의 자세 문제 = 아동 사진·가족 음성을 만료 없는 안정 공개 URL로 저장**은 확정 #2(음성 삭제 누락)와 같은 약점이다. `put_object`에 `ACL='public-read'`는 없으니 **실제 공개 여부는 프로덕션 버킷 정책(실환경)** — **GA 전 반드시 확인**: 민감 미디어 버킷이 public-read면 서명 URL/인증 프록시로 전환. 코드 버그는 아니나 규제(아동 biometric-adjacent) 자세 항목.

## 기각 2건 (오탐 — 쫓지 말 것, 단 참고)
- **발음 평가 엔드포인트가 book_id 소유권을 검증하지 않음 (형제 엔드포인트와 불일치)** — Code·trigger 생존, impact 반증으로 전 렌즈 생존 미충족 → REFUTED. Code: pronunciation.py:97-99(evaluate)·163-165(evaluate-audio)가 소유권검증 없이 PronunciationLog(book_id=request.book_id) 저장, 형제 streak.py:286은 assert_book
- **아동 원본 사진(source_image_url)이 만료·프록시 없는 공개 버킷 URL로 저장** — CODE 생존: characters.py:636-640이 원본 아동 사진을 characters/{id}/photo{ext}로 upload_bytes하고 storage.py:347이 {s3_public_url}/{key} 평문 공개 URL을 반환해 source_image_url(656)에 저장 — 서명·만료·인증 없음. TRIGGER 반증(결정적): 애플리케

## 권고 (출시 전 vs 이후)
- **출시 전(저렴·명확)**: #2 음성 프로필 단건삭제 스토리지 파기(규제, N1과 동일 클래스) · #3 `python-multipart>=0.0.18`(CVE, 1줄) · #4 deploy용 appleboy/ssh-action SHA 핀 · #1 전역 비용 가드레일/알림 · 민감 미디어 버킷 ACL 확인(위 §2).
- **출시 후/수용**: #5~#8 낮음(레이트리밋 fail-open·에러 원문 노출·Swagger 공개·CI 권한) · #9~#11(로그 마스킹·미과금 경로) — 로드맵 이관.
- **최적화/성능**: 이번 범위 밖. 출시 후 실부하·비용 데이터로 production-ops 모니터링에서 근거 확보 후.