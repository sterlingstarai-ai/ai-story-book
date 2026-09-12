# 출시 후보 — 2026-09-12

현재 결정: **공개 출시 보류, 운영 활성화 전 기술 준비 진행**. 사용자 요청에 따라 구현·검증·배포본 정리는 수행하고, 기존에 보류한 신규 호스팅 결제·공개 정책 확정·공동 최종 검토·스토어 제출을 마지막 단계에 남긴다. 자동 검사 결과를 실제 운영 승인으로 바꾸지 않는다.

## 구현

- 9월 10일 서재 커서·모바일 응답 경합·성장 통계 최적화를 포함한다.
- 새 AI 작업의 서버 접근 모드는 `open`, `invite_only`, `paused`다. 운영 Compose·Render 템플릿은 `invite_only`, 개발·테스트는 `open`을 기본으로 한다.
- 초대 목록은 안정된 계정 소유 키의 도메인 분리 SHA-256만 보관한다. 원문 인증정보를 YAML·로그·코드에 기록하지 않는다. 빈 목록·잘못된 목록은 초대 전용 모드에서 전부 차단한다. 복구된 기기 키는 먼저 원래 계정으로 해석되므로 기존 초대 권한을 유지한다.
- 차단된 계정은 새 책·재생성·인페인트·시리즈·리텔·오늘의 동화·캐릭터 AI 생성·새 음성 합성/STT를 시작할 수 없다. 이미 저장된 책·음성·복구·삭제 경로는 이 제어로 막지 않는다. 실행 중인 작업을 취소하는 제어는 아니다.
- 익명 계정 반복 생성으로 초대 권한을 얻을 수 없다. 정식 공개 서비스의 기기 인증/계정 남용 방지를 완전히 구현했다는 뜻은 아니다. 일일 전역 예산과 사용자별 제한을 함께 유지한다.
- 인증된 `/health/detailed`에 일일 생성 요청 예산의 읽기 전용 상태를 추가했다. 조회가 카운터를 증가시키지 않는다. 공개 readiness에는 계정 목록·해시를 노출하지 않는다.
- `scripts/check_operations.py`는 상세 상태를 읽고 멈춘 작업·최근 실패·예산 80% 사용·상태 조회 불가에서 종료 코드 1과 정제된 JSON을 낸다. 비용은 달러가 아니라 기존 생성 요청 카운터다. 공급자 청구서 상한을 뜻하지 않는다. 자동 외부 알림 전송·정기 실행은 아직 연결하지 않았다.
- 오래된 HTTP 시험 도구를 실제 앱 순서인 동의→프로필로 수정하고, 동의 전 프로필 생성의 403 차단을 별도 검사한다. 생년월 시험값도 실행 연도 기준 7세로 생성한다.

## 검증 결과

- 전체 phase gate 통과: API 2,083개 통과·25개 건너뜀, Flutter 596개 통과, UI 사전 검사 10개 통과, 정적 분석 및 Android debug APK·iOS 서명 없는 빌드 통과.
- 실제 PostgreSQL·Redis·Celery·MinIO 격리 실행 통과: 회귀 21개, 비공개 미디어 19개, 사진 캐릭터 경로 26개 및 HTTP 사용자 여정 통과. AI 공급자는 mock이며 실제 아동 사진이나 유료 API를 사용하지 않았다.
- 별도 PostgreSQL·미디어 백업 복원 9개 검사 통과, 임시 자원 정리 완료.
- 운영 환경 사전 검사는 기존 비공개 설정으로 여전히 BLOCKED다. 운영 주소·공급자·정책 승인 등 마지막 활성화 조건이 남아 있다.
- 이전 원격 CI의 존재하지 않는 `flutter-tester` 디바이스 지정을 Android 에뮬레이터 실행으로 교체했다. API 검사는 15분 제한과 120초 정지 시 스택 덤프를 추가해 6시간 무응답 실패를 진단할 수 있게 했다. 10MB 업로드 입력 전체가 verbose 테스트 이름으로 출력되는 문제도 짧은 명시적 ID로 수정했다. 업로드 한도와 검사 내용은 유지한다. 원격 재검증 결과는 후속 기록한다.

Git 제외 원본 근거: `docs/acceptance/2026-09-12-launch-preparation/`.

첫 runtime 시도의 실제 PG·미디어·캐릭터 검사는 통과했지만 HTTP 여정이 동의 전 프로필 생성에서 2건 실패했다. 서버 보호 경계를 완화하지 않고 시험 도구를 수정했으며 최초 실패 로그도 보존했다. 새 운영 계량에 필요한 Redis GET을 시험용 Redis에 추가한 뒤 focused 99개, 추가 계정 복구/미초대 HTTP 생성 검사까지 12개 admission 검사가 통과했다. 이 집중 검사 수를 전체 검사 수와 합산하지 않는다.

추가 검증의 실패 이력도 보존한다. 커버리지 포함 첫 로컬 실행은 새 CI 설정의 pipefail 표기 검사 1건이 실패했고, 표기를 수정한 뒤 해당 CI·이미지 입력 검사 26개가 통과했다. 별도 기존 Linux/Python 3.11 이미지에서는 2,081개 통과·25개 건너뜀·2개 실패였으며, 두 실패는 이미지에 `appstoreserverlibrary`가 없는 환경 차이였다. 현재 `requirements.txt`는 `app-store-server-library==3.1.2`를 이미 포함한다. 해당 구형 이미지 결과를 최종 통과 증거로 사용하지 않는다.

## 마지막 개입에서 확정할 사항

1. **운영 호스팅 활성화**: 기존 Render API·worker·Key Value 및 전용 Supabase 구성. 기존 다른 프로젝트는 변경하지 않는다. 기존 월 $67은 9월 6일의 기본 추정이며 결제 화면의 최신 합계·세금·초과 사용·별도 백업 비용을 대조한 뒤 승인한다. [구성](RENDER_DEPLOYMENT_PACKAGE.md).
2. **실제 아동 데이터 처리 조건과 공개 정책**: 제공자 적용 증거, 실제 처리 업체·국가·보관/삭제/백업 기간·시행일 확정. 정책 문서를 승인된 것으로 바꾸지 않았다. 9월 12일 재확인한 [OpenAI 미성년자 지침](https://developers.openai.com/api/docs/guides/safety-checks/under-18-api-guidance)은 13세 미만 등의 개인정보 처리 전 ZDR 적용을 요구한다. 키 호출 성공이나 초대 제한이 이 조건을 대신하지 않는다. 지원 상담은 사용자 담당으로 유지한다.
3. **초기 초대 계정과 공동 최종 앱 확인**: 공개 서버를 연결한 빌드로 생성·읽기·실패복구·삭제를 함께 확인한다. 음성/결제를 켜는 경우 전체 낭독 및 스토어 샌드박스 구매·환불·복원도 통과해야 한다. 그 뒤 앱 등록·배포 서명·스토어 제출을 진행한다.

## 운영자 실행 절차

루트에서 다음 명령으로 현재 설정과 기술 검사를 재현한다. 실제 비밀값은 기존 비공개 환경 파일/호스팅 비밀 저장소에서 공급하며 명령행 인자로 적지 않는다.

```bash
./scripts/check-env.sh --mode ci
./scripts/phase-gate.sh --with-mobile-build --with-ios-build
./scripts/run_runtime_e2e.sh --report-dir docs/acceptance/release-runtime
./scripts/run_backup_restore_rehearsal.sh --report-dir docs/acceptance/release-restore
./scripts/final-external-preflight.sh --env-file infra/.env --json
```

초대 해시는 원래 계정 소유 키에서 만든다. 복구 후 발급된 `asb_device_…` 값 자체의 해시를 등록하지 않는다. 아래 입력은 터미널에 표시되지 않는다. 결과 해시도 공개 저장소에 기록하지 말고 운영의 `GENERATION_ALLOWED_USER_HASHES`에 넣는다.

```bash
./apps/api/venv/bin/python - <<'PY'
import getpass, hashlib
key = getpass.getpass('Stable invited account key: ')
if not key:
    raise SystemExit('Empty account key refused')
print(hashlib.sha256(('asb:generation-access:v1\0' + key).encode()).hexdigest())
PY
```

서버 연결 후 `PROD_API_URL`과 `ADMIN_API_KEY`를 운영 비밀 환경에 공급하고 아래 명령을 실행한다. 출력은 작업 수·예산·알림 코드만 포함한다. 외부 관측 시스템에는 5분 간격 실행 및 비정상 종료 알림을 연결하고, 연결 완료 후 실제 알림 수신까지 검증한다.

```bash
./apps/api/venv/bin/python scripts/check_operations.py
```

문제가 생기면 API·worker의 `GENERATION_ACCESS_MODE=paused`로 신규 AI 접수를 멈추고 기존 작업이 종료되는지 확인한다. 이는 배포된 프로세스의 설정 재적용이 필요한 방식이다. 진행 중인 긴 작업을 강제 종료하지 않는다. 이전 검증된 SHA 이미지로 되돌리는 절차는 [DEPLOYMENT.md](DEPLOYMENT.md)와 [Render 실행 순서](RENDER_DEPLOYMENT_PACKAGE.md)를 따른다.

운영 API가 없는 상태에서 mock 주소나 가짜 정책 승인을 채워 사전 검사를 통과시키지 않는다. 공개 배포·실제 AI 호출·결제·스토어 작업은 이번 기술 준비와 구분한다.

검증용 MinIO 이미지는 공식 Quay의 `RELEASE.2025-09-07T16-13-09Z`와 다중 아키텍처 digest `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`로 고정한다. 원격 Docker Hub pull이 거부되어 출처를 변경했으며, 9월 12일 로컬 실행에서 검증한 이미지와 digest가 동일함을 확인했다. 실제 운영의 외부 저장소 선택이나 활성화를 변경하지 않는다.

원격 Android 첫 실행은 33개 통과·3개 건너뜀과 DDS 시작 실패 1건이었다. 실제 오디오·보안 저장소 및 복구·접근성 검사는 통과했다. CI에 Flutter 3.38.7이 제공하는 `--no-dds`를 적용해 보조 디버그 서비스 연결을 제거하며, 테스트 선택·assertion·서비스 인증은 변경하지 않는다.
