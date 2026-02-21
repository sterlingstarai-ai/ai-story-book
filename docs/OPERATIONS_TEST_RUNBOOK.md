# AI Story Book - 테스트/실구동 단일 운영 가이드

이 문서는 사람이 최소 개입으로 프로젝트를 검증하고 실제 구동까지 올리는 기준 문서다.

## 1) 목표

- 코드 품질 검증: API + Mobile 테스트를 CI 기준으로 로컬 재현
- 실제 구동 검증: API 서버 기동 + 스모크 테스트
- 운영 배포: GitHub Actions 기반 자동화 경로 사용

## 2) 원칙 (중요)

- API 테스트는 반드시 `apps/api/venv`의 파이썬으로 실행한다.
- 시스템 파이썬으로 실행하면 `greenlet` 누락으로 대량 실패할 수 있다.
- 실구동 스모크는 마이그레이션 적용 후 실행한다.
- 도커 경로가 가능하면 도커를 우선 사용한다. (PostgreSQL/Redis/MinIO 포함)

## 3) 원클릭에 가까운 로컬 품질 게이트

프로젝트 루트에서 아래 블록을 그대로 실행:

```bash
set -euo pipefail
cd /Users/jmac/Desktop/ai-story-book

chmod +x scripts/check-env.sh scripts/smoke.sh scripts/deploy.sh

# 1) 환경 파일 구조 점검
./scripts/check-env.sh --ci

# 2) API 품질 게이트 (CI와 동일한 핵심 경로)
cd apps/api
./venv/bin/python -m ruff check src/ tests/
./venv/bin/python -m pytest tests/ -v --cov=src --cov-report=xml
cd ../..

# 3) Mobile 품질 게이트
cd apps/mobile
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test --coverage
cd ../..
```

성공 기준:

- API: `278 passed` (신규 기능/테스트 추가에 따라 증가 가능)
- Mobile: `No issues found!`, `All tests passed!`

## 4) 실제 구동 (도커 권장)

### 4-1. 사전 준비

```bash
cd /Users/jmac/Desktop/ai-story-book
cp -n infra/.env.example infra/.env
```

`infra/.env`에서 최소 항목 수정:

- `DB_PASSWORD`
- `LLM_PROVIDER` / `LLM_API_KEY` (로컬 검증만이면 `mock` 권장)
- `IMAGE_PROVIDER` / `IMAGE_API_KEY` (로컬 검증만이면 `mock` 권장)

### 4-2. 서비스 기동 + 마이그레이션 + 스모크

```bash
set -euo pipefail
cd /Users/jmac/Desktop/ai-story-book

if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  DC="docker compose"
fi

$DC --env-file infra/.env -f infra/docker-compose.yml up -d postgres redis minio api worker
$DC --env-file infra/.env -f infra/docker-compose.yml exec -T api alembic upgrade head

curl -sf http://127.0.0.1:8000/health
./scripts/smoke.sh http://127.0.0.1:8000
```

정상 기준:

- `/health`가 200
- `scripts/smoke.sh` 요약에서 `Failed: 0`

## 5) Mobile 앱 실제 연결 실행

디버그 기본값:

- Android emulator: `http://10.0.2.2:8000`
- iOS simulator: `http://localhost:8000`

실기기/원격 서버 연결 시:

```bash
cd /Users/jmac/Desktop/ai-story-book/apps/mobile
flutter run --dart-define=API_BASE_URL=http://<API_HOST>:8000
```

## 6) 운영 배포 (최소 개입 경로)

- PR 생성 → GitHub Actions `CI` 성공 확인
- `main` 머지 시:
  - `Build Docker Images` 자동 실행
  - `DEPLOY_ENABLED=true` + 배포 시크릿 설정 시 `Deploy to Production` 자동 실행

필수 설정:

- Repository Variables: `DEPLOY_ENABLED=true`
- Repository Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`

## 7) 장애 패턴과 즉시 조치

### A. `ValueError: the greenlet library is required`

원인:

- 시스템 파이썬으로 API 테스트 실행

조치:

- `apps/api/venv` 사용
- 실행 명령을 `./venv/bin/python -m pytest ...`로 고정

### B. `Cannot connect to the Docker daemon`

원인:

- Docker Desktop 미기동

조치:

- Docker Desktop 시작 후 4-2 절 재실행

### C. 스모크 500 + `no such column`/`no such table`

원인:

- DB 스키마 미적용 또는 오래된 스키마

조치:

- `alembic upgrade head` 재실행
- 필요 시 DB 볼륨 정리 후 재기동

## 8) 권장 운영 루틴

1. 로컬 품질 게이트(3절) 통과
2. 도커 실구동 + 스모크(4절) 통과
3. PR 올리고 CI 확인
4. main 머지 후 자동 배포 확인
