# 서버·백업 로컬 후보 v22/v12

기존 v20/v11 및 중간 v21을 보존하고, 제공자 키를 비공개 파일로 읽는 선택 경로와 환경 설정 계약을 포함한 후보를 별도 고정했다. 이 후보는 키 전달이나 운영 교체 도구가 아니다.

- 서버 매니페스트: `infra/gcp-pilot/narration-receipt-candidate-v22-manifest.json` (SHA-256 `f85b9e84de8929dd00aec7196f29a7944192b63d28f915e8040007a8e40448fb`). 이전 소스에 `src/core/config.py` 변경과 파일 마운트용 `infra/docker-compose.provider-key-files.yml`, 관련 Compose·환경 예시·스키마·배포 안내·사전 검사를 고정했다. 기본 후보 빌더의 PostgreSQL 예산 선택 경로도 v22를 참조한다.
- 빌드 결과: `docs/acceptance/privacy-final-synthetic-2026-11-03/candidate-v22-build.json` (SHA-256 `f2f4831d9314d0b9f917e7b5bf40c9a2d41239bf8d9ea46be3bc43adb7b755ed`). 로컬 격리 기반에서 API와 worker를 빌드했다. 두 이미지의 `src` 및 `alembic` 트리가 당시 체크아웃과 같았고 Alembic head는 각각 `e7b93d2a601f` 하나였다.
- 백업 후보: `docs/acceptance/2026-11-03-backup-candidate-v12/` (매니페스트 SHA-256 `f8f5333097543c575fa9c96e52de62857d8f02098154c576ac4b65ee8456b3e5`). 193개 파일의 무결성·소스 대조와 중단 없는 스케줄러 dry-run을 통과했다. 제한된 자격 문자열 패턴 검사에서 일치가 없었으나 모든 비밀정보 부재를 보증하지는 않는다. v21 이후 환경 스키마 설명 수정은 백업 후보 파일에 포함되지 않아 v12를 재대조해 보존했다.
- 제공자 키 파일 경로의 집중 검사 및 별도 격리 Docker의 합성 파일 마운트 시험을 수행했다. 일반 API 전체 검사 2,832개 통과·27개 건너뜀은 환경 스키마의 설명 문구 및 빌더 기본 경로만 후속 변경하기 전 결과다. 후보 빌더·백업·마이그레이션·트랜잭션 펜스 집중 검사 24개, 환경 계약 검사 및 `git diff --check`가 통과했다.

후보는 실제 운영 이미지와 다른 로컬 기반이며 운영 이미지·의존성 동등성을 입증하지 않는다. 실제 키 저장·전달·운영 교체, GCS 실서비스 호환성, 운영 백업·개인정보 복원, 실제 AI 및 출시 검증은 이 결과에 포함되지 않는다. 새 제공자 키 경로는 기본 비활성이며 운영 설정이나 기존 자격은 변경하지 않았다.
