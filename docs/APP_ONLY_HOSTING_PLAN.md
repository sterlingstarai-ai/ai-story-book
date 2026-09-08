# 앱 전용 출시를 위한 호스팅 구성

> 2026-09-08 최종 범위: 디지털 동화책·디지털 결제·음성과 운영 연결 준비. 실물 제작·배송은 제공하지 않습니다. 신규 결제는 보류하며 최신 구현·외부 조건은 [디지털 서비스 현황](FEATURE_WIRING_2026-09-08.md)을 따릅니다.

기준일: 2026-09-06

**현재 상태: 앱 최종 디자인과 E2E 검증을 마무리한 뒤 공동 검토 대기.** 아래는 현재 구현을 가장 적게 바꾸는 구성안이며, 운영 연결이나 배포가 끝났다는 뜻이 아닙니다.

- 사용자는 기존 **Vercel·Supabase 계정**을 보유하고 있습니다. 이후 실제 계정의 요금제·잔여 슬롯을 확인했으며 최신 결과는 [호스팅 계정 검토](HOSTING_ACCOUNT_REVIEW_2026-09-06.md)에 기록했습니다.
- AI Story Book 전용 프로젝트의 생성·연결은 아직 확인하지 않았습니다. 저장소에서도 Vercel·Supabase 프로젝트 연결 설정을 찾지 못했습니다.
- 초기 검토에서는 새 프로젝트·계정·서비스 생성이나 배포를 하지 않았습니다. 이후 외부 DB TLS·S3 어댑터와 별도 상주 실행 구성을 준비했습니다. 실행 가능한 절차와 남은 실제 조건은 [외부 호스팅 배포 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)를 따릅니다.

## 최소 구성안

| 역할 | 사용할 구성 | 남은 결정·조건 |
| --- | --- | --- |
| 사용자 앱 | 기존 Flutter iOS·Android 앱 | 웹 제품을 별도로 만들 필요 없음 |
| DB·동화 이미지·PDF | 기존 계정 안의 **전용 Supabase 프로젝트**, PostgreSQL + **비공개 Storage 버킷** | 프로젝트 연결, 리전·용량·백업 설정 확인 |
| API·생성 작업·제한 카운터 | **추가 상주 컨테이너 실행 환경**에서 FastAPI API 1개 + Celery 워커 1개 + Redis 1개 | 실행 환경 선정, 지속 실행·영속 디스크·HTTPS 확인 |
| 공개 안내 문서 | 필요하면 기존 Vercel 계정으로 개인정보처리방침·약관·지원 페이지 제공 | 공개할 파일만 별도로 배포; 저장소나 내부 검토 문서 전체를 공개하지 않음 |

Redis는 현재 Celery 큐·결과, 요청 제한, 하루 생성 예산 등에 쓰입니다. 영속 저장과 `appendonly yes`, `noeviction`을 유지합니다. API 내부의 작업 감시·정기 크레딧 처리도 지속 실행을 전제로 합니다. 위 서비스 수는 초기 구성안이지 처리 용량을 측정한 결과가 아닙니다.

**독립 도메인을 구매할 필요는 없습니다.** Vercel은 `*.vercel.app` 주소를 자동 제공합니다. 공개 약관 링크에는 안정적인 운영 주소를 사용합니다. API도 선택한 실행 환경이 제공하는 유효한 기본 HTTPS 주소를 사용할 수 있으므로, 실행 환경 선정 때 그 지원 여부를 확인합니다. [Vercel 생성 URL 문서](https://vercel.com/docs/deployments/generated-urls)

초기 운영 방침은 무료 제한 베타를 유지합니다. 새 구매·오디오·POD는 비활성화하며, 전체 하루 생성 시도 제한은 20회입니다. 이 횟수 제한은 금액 기준의 지출 상한을 보장하지 않습니다.

## Supabase 연결 준비와 남은 실제 검증

1. **외부 DB 연결과 배포 절차.** 기존 운영 Compose는 내부 `postgres` 경로로 유지합니다. 별도 `docker-compose.external.yml`과 API·워커·Alembic의 공통 TLS 설정을 준비했으며, 실제 외부 주소에서 인증서 검증과 마이그레이션을 확인해야 합니다. 상주 환경은 가능한 경우 직접 연결을, IPv4만 지원하면 세션 풀러를 검토합니다. 준비된 구문 제약이 있는 트랜잭션 풀러를 그대로 적용하지 않습니다. [Supabase PostgreSQL 연결 문서](https://supabase.com/docs/guides/database/connecting-to-postgres)

2. **기존 API 인증 경계 유지.** 앱은 FastAPI의 사용자·프로필 소유권 검사를 사용하며 Supabase Data API를 필요로 하지 않습니다. 전용 프로젝트에서 Data API를 비활성화하고 앱 테이블에 대한 우회 접근이 차단되는지 확인합니다. Supabase Auth로 바꾸는 작업은 이번 구성안에 포함하지 않습니다. [Supabase API 보안 문서](https://supabase.com/docs/guides/api/securing-your-api)

3. **S3 설정의 누락 보완.** 일반 업로드 클라이언트와 서명 다운로드 클라이언트 모두 Supabase 프로젝트 리전과 경로 방식 주소를 명시하도록 맞춰야 합니다. `S3_REGION`과 `S3_ADDRESSING_STYLE`을 애플리케이션 설정·양쪽 클라이언트에 연결했습니다. 실제 프로젝트 지역과 private bucket의 접근 제어는 연결 후 확인합니다. 비공개 버킷을 유지하며, 기존 미디어 주소와 소유자별 삭제 경로도 보존합니다. Supabase S3 관리 키는 RLS를 우회하므로 서버에만 저장합니다. [Supabase S3 인증·설정 문서](https://supabase.com/docs/guides/storage/s3/authentication)

4. **원격 백업·복원 절차.** 현재 `deploy.sh backup`은 내부 PostgreSQL 컨테이너에 의존하는 DB 전용 백업입니다. 외부 구성은 별도 `backup_external.py`로 DB·미디어를 함께 백업하도록 준비했습니다. 기본값은 원격 호출 없는 dry-run이며 실제 백업·격리 복원은 승인된 운영 창에서 검증해야 합니다. Supabase S3 호환 API는 필요한 객체 업로드·조회·목록·삭제·서명 URL을 지원하지만 S3 버전 관리는 지원하지 않으므로 별도 미디어 복구 수단이 필요합니다. DB 백업만으로 그림이 복원된다고 가정하지 않습니다. [S3 호환 범위](https://supabase.com/docs/guides/storage/s3/compatibility), [프로젝트 백업·복구 계약](BACKUP_RESTORE.md)

## 연결 후 통과해야 할 검증

- 운영 이미지로 최신 Alembic 마이그레이션, TLS DB 연결, `/health/ready`가 성공할 것.
- 앱 테이블의 직접 익명 접근이 차단되고, 기존 계정·프로필 소유권과 복구·폐기 경계가 유지될 것.
- 비공개 미디어의 익명 접근은 실패하고, 기한 내 서명 다운로드·만료·공유 철회·사진 및 책 삭제가 예상대로 동작할 것.
- 실제 Celery 작업 생성·재시작·재시도에서 중복 생성과 중복 차감이 없고, Redis 장애 때 생성 제한이 우회되지 않을 것.
- 선택한 HTTPS 주소에서 실제 iOS·Android의 생성 → 읽기 → 이어 읽기 → 명시적 완독 → 삭제 흐름을 확인할 것. 실제 AI 품질 검증은 유효한 공급자 설정으로 별도 수행할 것.
- DB·미디어를 격리 환경에 함께 복원하고, 백업 이후 삭제·동의 철회·인증 폐기 기록을 재적용할 것.

기존 로컬 통합 검증은 Supabase 실서비스 연결, 실 AI 품질, 운영 복구 시간의 증거를 대신하지 않습니다. 연결 이후의 결과를 기록하기 전까지 운영 준비 완료로 표시하지 않습니다.

## Vercel에 API·워커까지 두는 대안

Vercel은 FastAPI와 Celery 구성을 지원합니다. 다만 공식 Celery 예제는 Vercel Queues용 `vercel://` 브로커와 Runtime Cache를 사용합니다. 현재 검증된 Redis 기반 Celery와 API 내부 주기 작업을 그대로 옮기는 배포 방식은 아닙니다. 별도 큐·결과 저장·스케줄링 전환과 재검증이 필요합니다. [Vercel FastAPI 지원](https://vercel.com/docs/frameworks/backend/fastapi), [공식 Celery 예제](https://vercel.com/templates/python/python-celery-starter)

또한 Vercel Functions의 요청·응답 본문 한도는 4.5MB인데, 현재 앱의 사진 업로드 API는 최대 10MB를 받습니다. API를 그곳에 두려면 동의·소유권 검사를 보존하면서 업로드 경로도 바꿔야 합니다. 따라서 **이번 최소 변경안은 추가 상주 실행 환경을 사용**하며, Vercel 중심 전환은 별도 작업으로 검토합니다. [Vercel Functions 제한](https://vercel.com/docs/functions/limitations)
