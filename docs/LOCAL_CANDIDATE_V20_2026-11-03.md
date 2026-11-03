# 서버·백업 로컬 후보 v20/v11

기존 v19/v10을 보존한 채, 개인정보 GCS 원장 객체를 읽을 때 스트리밍 크기 제한 및 압축 거부를 추가한 현재 소스를 별도 후보로 고정했다. 운영 설정·자격·데이터와 실행 중인 서비스는 변경하지 않았다.

- 서버 후보 매니페스트: `infra/gcp-pilot/narration-receipt-candidate-v20-manifest.json` (SHA-256 `d39bdadc39ccf193f541995133b1700a31b9c3a2dd53b05bca41b1ad58d6a2c0`). v19 대비 고정 소스 변경은 `src/services/privacy_journal_gcs.py` 한 파일이었고 host 산출물의 해시는 같았다.
- 빌드 결과: `docs/acceptance/privacy-final-synthetic-2026-11-03/candidate-v20-build.json` (SHA-256 `670f3eedc36c75a83da8e1f5b4e62cd7584e43ae264422ce40608c6f090c68b7`). 로컬 격리 기반에서 각각 빌드한 API·worker 양쪽의 `src` 및 `alembic` 트리가 당시 체크아웃과 같았고, 컨테이너 내부 Alembic head는 각각 `e7b93d2a601f` 하나였다.
- 백업 후보: `docs/acceptance/2026-11-03-backup-candidate-v11/` (매니페스트 SHA-256 `a43a6df2445d7c3bce17e2d414dfd2593d54b647afe0b45bfe8db3c49d896909`). 193개 고정 파일의 무결성과 당시 체크아웃을 대조했고, 후보 스케줄러를 dry-run해 서비스 중단 없이 인자를 확인했다. dry-run에서 이 후보에 생성된 바이트코드만 제거한 뒤 후보 무결성과 소스 일치 재검사를 통과했다.
- 후보 빌더·백업·마이그레이션·트랜잭션 펜스 집중 검사 24개가 통과했다. 백업 후보의 제한된 자격 문자열 패턴 검사에서는 일치가 없었지만, 이는 비밀정보 부재를 포괄적으로 보증하지 않는다.

실제 운영 이미지와 로컬 기반의 동등성, GCS 실서비스 호환성, 실제 운영 백업·복원 및 AI 공급자 연결은 이 결과에 포함되지 않는다. API/worker에 후보를 설치하지 않았으며 PostgreSQL 예산 저장소도 활성화하지 않았다. 운영 복원과 공개 출시를 승인하는 결과가 아니다.
