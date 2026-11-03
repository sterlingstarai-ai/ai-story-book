# 서버·백업 로컬 후보 v19/v10

이전 v18/v9를 보존하고 생성 예산의 PostgreSQL 선택 경로를 포함한 별도 로컬 후보를 만들었다. 운영 설정 변경이나 예산 저장소 활성화는 수행하지 않았다.

- 서버 후보 매니페스트: `infra/gcp-pilot/narration-receipt-candidate-v19-manifest.json` (SHA-256 `483b64b94edd9260d309b702b8347451fd508154ec525f7ae29f5d1cfe49b9d3`). 예산 모델·migration·수동 활성화 스크립트 및 운영 가이드를 추가 고정했다. 빌드 당시 고정 파일은 소스 62개와 host 산출물 60개다.
- 빌드 결과: `docs/acceptance/privacy-final-synthetic-2026-11-03/candidate-v19-build.json` (SHA-256 `39bf3684afedbdabb3b6ee8d11268777fd4bbfa07c5ff956f951669c8e3a9292`). API와 worker 이미지를 별도로 만들었고 API의 소스 트리와 체크아웃 차이는 없었다. 이미지 내부 Alembic head는 `e7b93d2a601f` 하나였다. 수동 활성화 도구의 도움말을 격리된 합성 환경에서 확인했고 활성화 명령은 실행하지 않았다.
- 기존 배포 부품의 목표 revision 및 트랜잭션 migration 체인을 새 head로 맞췄다. 격리된 합성 PostgreSQL에서 펜스 안의 백업·복원 시험과 migration, migration 도중 강제 종료 후 롤백 시험이 통과했다. 외부 미디어와 개인정보 재생, 실제 운영 복원은 시험하지 않았다.
- 백업 v10은 `docs/acceptance/2026-11-03-backup-candidate-v10/`에 있으며 매니페스트 SHA-256은 `42d3da1b42b16b1fec208c5bbaff2e37024833879fbe54cb1be0001ec6a23a67`이다. 무결성·소스 대조·스케줄러 dry-run이 통과했다.
- 예산 저장소 설정은 Redis 기본값과 PostgreSQL 선택지를 스키마·설정·API/worker Compose·예시에서 대조했고 잘못된 설정값을 거부했다. 후보 및 배포 부품 집중 테스트 24개가 통과했다. 서버 후보 고정 파일의 제한된 자격 패턴 검사에서는 환경 스키마의 localhost 예시 URL 1건만 나왔다. 이는 모든 비밀정보가 없다는 보장은 아니다.

서버 후보는 운영 이미지와 다른 로컬 리허설 이미지를 기반으로 하므로 운영 이미지와 의존성 동등성을 입증하지 않는다. PostgreSQL 예산 전환은 모든 기존 작성자 차단과 전환일 생성 중단이 필요하며, 과거 DB 백업을 복원하면 카운터가 되돌아갈 수 있어 재개 전 별도의 안전 조치가 필요하다. 실제 전환·운영 백업·복원·제공자 검증 및 출시 가능성은 이 기록으로 입증되지 않는다.
