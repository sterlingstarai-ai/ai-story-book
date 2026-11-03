# 외부 PostgreSQL·비공개 S3 배포 준비

2026-09-06 코드 준비 상태입니다. 이 문서와 설정 검사는 계정 구매·전용 프로젝트 생성·연결·운영 배포를 실행하지 않습니다. 계정별 실제 요금·승인 상태는 [호스팅 계정 검토](HOSTING_ACCOUNT_REVIEW_2026-09-06.md)를 따릅니다.

Render를 선택할 경우 구체 요금제·Blueprint 생성·계정 단계는 [Render 실행 준비 패키지](RENDER_DEPLOYMENT_PACKAGE.md)를 따릅니다.

## 실행 구성

`infra/docker-compose.external.yml`은 상주 API·Celery 워커·Redis만 만듭니다. 내부 PostgreSQL·MinIO와 기존 운영 Compose는 그대로 유지합니다. API 포트는 호스트 loopback에만 바인딩하므로 운영 HTTPS ingress/reverse proxy를 별도로 연결해야 합니다. 관리형 플랫폼에 각각 배치할 때도 동일한 런타임 값을 사용하며, 플랫폼의 Redis 내부 주소·인증정보로 `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`를 함께 설정합니다. Compose의 내부 `redis` 호스트를 관리형 플랫폼에 그대로 복사하지 않습니다.

Supabase에는 전용 PostgreSQL 프로젝트와 비공개 Storage 버킷이 필요합니다. 기존 다른 프로젝트와 섞지 않습니다. FastAPI가 소유권·동의·인증을 계속 검사하며 앱은 Supabase Data API를 직접 호출하지 않습니다. 전용 프로젝트의 Data API를 비활성화하고 앱 테이블의 우회 접근이 차단되는지 실제로 확인해야 합니다.

## 연결 설정

| 설정 | 외부 구성 값과 근거 |
| --- | --- |
| `DATABASE_URL` | IPv6 가능한 상주 호스트는 직접 연결, IPv4 호스트는 Supavisor **session** 주소의 5432 포트. `postgres://`, `postgresql://`, `postgresql+asyncpg://` 모두 지원. 사용자명·암호의 특수문자는 URI 인코딩. |
| `DATABASE_SSL_MODE` | `verify-full`. API·워커의 asyncpg와 Alembic의 동기 드라이버에 같은 TLS 정책 적용. URL의 `sslmode`가 별도 설정과 충돌하면 시작 실패. |
| `DATABASE_SSL_ROOT_CERT` | 컨테이너에서 읽을 수 있는 공급자 CA 파일. 예: `/run/storybook-certs/supabase-ca.crt`. Supabase에서 받은 CA를 `infra/certs/`에 두면 두 서비스에 읽기 전용 마운트. 파일 누락/인증 실패를 비암호화 연결로 대체하지 않음. |
| `DATABASE_MIGRATION_URL` | 선택값. 마이그레이션에 별도 직접 주소를 사용하면 입력. 비어 있으면 런타임 주소 사용. 동일한 TLS 정책 적용. |
| `S3_ENDPOINT`, `S3_DOWNLOAD_ENDPOINT` | 대시보드의 정확한 S3 endpoint. 보통 `https://PROJECT_REF.storage.supabase.co/storage/v1/s3`. 다운로드 서명 대상은 앱에서 접근 가능한 HTTPS S3 API여야 함. |
| `S3_REGION` | 대시보드의 프로젝트 region 그대로. 업로드와 서명 모두 적용. |
| `S3_ADDRESSING_STYLE` | 외부 Compose는 `path` 고정. SDK 일반 설정은 `path`/`virtual`/`auto` 지원. |
| `S3_AUTO_CREATE_BUCKET` | 외부 Compose는 `false` 고정. 운영자가 먼저 만든 비공개 버킷을 확인하고 사용. 권한 거부를 버킷 미존재로 간주해 새 버킷을 만들지 않음. |
| `S3_PUBLIC_URL` | DB에 저장하는 안정적인 미디어 주소의 base. 예: S3 endpoint 뒤에 `/ai-story-book`. 이름의 `PUBLIC`은 익명 공개를 허용한다는 뜻이 아님. 응답 시 소유권 검사 후 서명. 주소 이전 시 `S3_LEGACY_PUBLIC_URLS` 유지. |
| `API_IMAGE`, `WORKER_IMAGE` | CI가 만든 40자리 commit SHA 태그 또는 SHA256 digest. `latest`/`stable` 거부. |

Supabase의 6543 transaction pooler는 이 애플리케이션에서 지원하지 않습니다. prepared statement 캐시만 끄면 모든 트랜잭션 풀러와 호환된다고 가정하지 않습니다. [연결 방식](https://supabase.com/docs/guides/database/connecting-to-postgres), [asyncpg SSL 옵션](https://magicstack.github.io/asyncpg/current/api/index.html#asyncpg.connection.connect)

S3 관리 키는 RLS를 우회하는 서버 전용 자격증명입니다. 앱·로그·저장소·공개 문서에 넣지 않습니다. [S3 인증과 path 설정](https://supabase.com/docs/guides/storage/s3/authentication)

## 안전한 사전 점검

`infra/.env.external.example`을 Git에서 제외되는 `infra/.env.external`로 복사해 확정한 값으로 채웁니다. 기존 `.env`는 덮어쓰지 않습니다. CA 파일에는 비밀키가 필요하지 않습니다. 아래 점검은 DB/S3/AI에 접속하지 않습니다. `docker compose config`는 `--quiet` 없이 실행하면 자격증명을 표시할 수 있으므로 그대로 터미널·증빙에 남기지 않습니다.

```bash
./scripts/check-env.sh --mode external --env-file infra/.env.external
docker compose --env-file infra/.env.external -f infra/docker-compose.external.yml config --quiet
```

환경 검사는 사진 처리 승인, 실제 결제, 정책 URL 접근, 사설 버킷 접근통제를 증명하지 않습니다. 사진 처리 승인이 확인되기 전에는 `PHOTO_PROCESSING_ENABLED=false`를 유지합니다. 기존 구매·POD·오디오 비활성/엄격 검증 설정도 그대로 따릅니다.

## 운영 대상이 확정된 뒤 실행할 순서

Google e2-micro처럼 메모리가 작은 전용 시험 VM은 기본 worker 동시성 2를 바로 적용하지 않는다. 선택 오버라이드 `infra/docker-compose.small-vm.yml`을 외부 Compose 뒤에 지정하면 prefork worker 동시성을 1로 제한한다. 이는 `/health/ready`, 실제 Neon/S3·AI, 동시 작업, 속도, Redis 한도·재시작, 백업 또는 보안 검증을 대신하지 않는다. 스왑은 이 파일이 만들지 않으며 민감정보가 들어갈 수 있으므로 운영에서 암호화·보존 정책을 먼저 확정한다. 실제 운영 배포 전 [VM 시험 결과](FREE_HOSTING_2026-11-02.md)를 확인한다.

1. 전용 프로젝트/버킷/지역과 상주 호스트·Redis를 확정하고 자격증명과 CA 파일을 비공개로 공급합니다. 관리형 Redis는 영속성·`noeviction`·사설 접근을 실제 설정합니다.
2. 해당 checkout의 CI 이미지로 마이그레이션을 먼저 실행하고 API와 워커를 올립니다. `deploy.sh --compose-file infra/docker-compose.external.yml --env-file infra/.env.external --image-tag COMMIT_SHA deploy` 경로를 사용할 수 있으나, 이는 원격 쓰기이며 실제 배포 창에서만 실행합니다. HTTPS ingress가 먼저 준비되어야 최종 readiness가 성공합니다.
3. `/health/ready`, 실제 DB TLS 검증, 연속 두 책의 Celery 실행, 서명 다운로드·익명 거부·삭제/동의 철회 후 제거를 실제 호스트에서 확인합니다. 무료 테스트로 만든 합성 오브젝트로 시작합니다.
4. [백업·복구 계약](BACKUP_RESTORE.md)에 맞춰 DB와 미디어를 함께 백업하고 격리 복원합니다. 새 외부 백업 도구는 기본 dry-run입니다. `deploy.sh backup`은 외부 구성을 거절하며 내부 PostgreSQL용 기능으로 유지됩니다.
5. 실제 iOS/Android의 생성→읽기→이어읽기→완독→삭제를 확인하고, 콘텐츠 품질·정책·공동 최종 검토까지 끝난 뒤 출시 여부를 판단합니다.

Supabase S3는 객체 버전 관리를 지원하지 않으므로 DB 백업만으로 삭제된 그림이 복구되지 않습니다. [S3 호환 범위](https://supabase.com/docs/guides/storage/s3/compatibility)

## 코드만으로 완료할 수 없는 조건

전용 프로젝트·월 과금 승인, 데이터 보관 지역, CA/DB/Storage 자격증명, private bucket/Data API 차단, 공급자 아동 데이터 처리 조건, HTTPS 운영 주소, 외부 암호화 백업 장소와 최신 삭제·인증폐기 기록 보존은 실제 계정·운영 증거가 필요합니다. 새 코드의 단위/구성 검사 통과를 운영 연결이나 복구 검증 완료로 표시하지 않습니다.
