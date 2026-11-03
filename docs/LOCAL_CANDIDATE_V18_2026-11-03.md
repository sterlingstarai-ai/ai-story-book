# 서버·백업 로컬 후보 v18/v9

기존 서버 v17과 백업 v8을 보존하고 별도 후보를 생성했다. 운영 배포, 백업 설치와 복원을 수행하지 않았다.

- 서버 v18: `infra/gcp-pilot/narration-receipt-candidate-v18-manifest.json` (SHA-256 `7d25385603cf58ed2bb5323c49c538e926ff1896cd81a9b884c542974e084ebb`). 분기 권한 및 비용 예산 코드를 명시적 허용 목록에 추가하고 GCS 저널 읽기와 공유 OpenAPI 스냅샷을 갱신했다. 기존 host 파일 외에 시험 전용 systemd fixture는 포함하지 않는다.
- 빌드 결과: `docs/acceptance/privacy-final-synthetic-2026-11-03/candidate-v18-build.json` (SHA-256 `4fb98932bffb8bbfb3351c2cb4d0967176c7a9d056cdb82852a75857e28b718c`). API 및 worker 이미지의 허용 파일을 검사했고 API 소스는 빌드 시점의 체크아웃과 같았다. API 후보에서 Alembic head `4c2d8f71b906` 하나를 확인했다. 빌드 중 외부 제공자를 호출하지 않았다.
- 백업 v9: `docs/acceptance/2026-11-03-backup-candidate-v9/`, 매니페스트 SHA-256 `0dd9de4297a8dce2feca4b11dbd54a5f5eff3cd53614779fcbcf794bada8e329`. 190개 파일의 무결성과 생성 시점 소스를 대조했고 후보 스케줄러 dry-run은 서비스 중단 없이 종료됐다. 자세한 범위는 `docs/BACKUP_CANDIDATE_2026-11-03.md`에 기록했다.
- 두 후보 빌더의 집중 테스트 15개 통과. 서버 후보가 고정한 116개 소스·host 파일의 제한된 자격 패턴 검색에서는 `env.schema.json`의 localhost 예시 URL만 확인했다. 이 검색은 모든 비밀정보가 없다는 보장이 아니다.

서버 후보는 운영 이미지 ID가 아닌 로컬 리허설 이미지를 기반으로 했다. 운영 이미지와 의존성 동등성, 실제 제공자 호출, 실 DB migration, 실제 백업·복원 및 배포 가능성은 이 결과로 입증되지 않는다.
