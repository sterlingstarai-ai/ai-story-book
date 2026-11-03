# 백업 코드 로컬 후보

`scripts/build_backup_candidate.py`는 백업 코드·서비스 파일, API Python 소스, migration, 고정 requirements를 별도 디렉터리에 복사하고 SHA-256 매니페스트를 생성한다. 환경 파일, 자격, 데이터베이스·미디어, 백업, 가상환경은 포함하지 않는다. 기존 디렉터리는 덮어쓰지 않는다.

```sh
./apps/api/venv/bin/python scripts/build_backup_candidate.py build --output /absolute/private/existing-parent/new-candidate
./apps/api/venv/bin/python scripts/build_backup_candidate.py verify --output /absolute/private/existing-parent/new-candidate --manifest-sha256 <independent-manifest-sha256> --compare-source
```

두 번째 명령은 지정한 매니페스트 해시와 각 파일을 대조하고 누락, 변경, 추가 파일과 symlink를 거부한다. `--compare-source`는 현재 체크아웃과도 비교하지만 비교 이후의 변경을 막지는 않는다. 매니페스트 해시는 후보와 별도로 신뢰 가능한 곳에 보존해야 한다. 실패한 빌드의 미완성 디렉터리는 자동 삭제하지 않는다.

이 후보는 설치 도구가 아니며 운영 `/opt/ai-story-book/current`를 수정하지 않는다. 실제 반영 전 운영의 기존 번들과 의존성·Python·PostgreSQL 도구·서비스 설정을 비교하고, 변경 중인 백업과 복구 마커가 없음을 확인해야 한다. 충돌이나 증거 부족 시 운영은 그대로 유지한다. 유휴 사전 검사는 사용 중일 때 불필요한 서비스 중단을 피하지만, 정상적인 백업 수행 중에는 기존대로 API·worker를 중지한다.

## 로컬 후보 검증 기록

- 최신 후보: `docs/acceptance/2026-11-03-backup-candidate-v12/`. 매니페스트 SHA-256 `f8f5333097543c575fa9c96e52de62857d8f02098154c576ac4b65ee8456b3e5`, 193개 파일. GCS 원장 읽기 제한과 선택적 제공자 키 파일 설정을 포함한다. 후보 무결성·생성 시점 소스 대조 및 서비스 중단 없는 스케줄러 dry-run을 통과했고 제한된 자격 문자열 패턴 검사에서 일치가 없었다. 이는 포괄적 비밀정보 보증이나 운영 설치·실제 백업·복원 증거가 아니다. [서버·백업 v22/v12 기록](LOCAL_CANDIDATE_V22_2026-11-03.md).
- 이전 v10: `docs/acceptance/2026-11-03-backup-candidate-v10/`. 매니페스트 SHA-256 `42d3da1b42b16b1fec208c5bbaff2e37024833879fbe54cb1be0001ec6a23a67`, 193개 파일. PostgreSQL 생성 예산 모델, migration 및 수동 활성화 스크립트를 추가 고정했다. 후보 무결성·생성 시점 소스 대조 및 서비스 중단 없는 스케줄러 dry-run을 통과했고 제한된 자격 문자열 패턴 검사에서 발견된 항목은 없었다. 이 검사는 포괄적 비밀정보 보증이 아니다. 운영 설치·실제 백업·복원·예산 저장소 전환 증거가 아니다.
- 이전 v9: `docs/acceptance/2026-11-03-backup-candidate-v9/`. 매니페스트 SHA-256 `0dd9de4297a8dce2feca4b11dbd54a5f5eff3cd53614779fcbcf794bada8e329`, 190개 파일. 분기 권한, 비용 예산 원자적 처리, GCS 저널 읽기 변경을 포함한다. 후보 무결성과 생성 시점 소스 대조를 통과했고 지정된 자격 문자열 패턴 검사에서 발견된 항목은 없었다. 이는 제한된 패턴 검사이며 비밀정보가 없다는 포괄적 보증은 아니다. 시험 전용 systemd fixture는 포함하지 않았다. 운영 설치·실제 백업·복원 증거가 아니다.
- 이전 v8: `docs/acceptance/2026-11-03-backup-candidate-v8/`. 매니페스트 SHA-256 `dac703943de73a2c4c3022af80365407f391d602b41b8cc904775b30cce0d439`, 190개 파일. 스토리지 목록 검증 및 키 교체 marker 가드를 포함하며, 이전 후보에서 빠졌던 복구 unit의 `narration_marker_exec_condition.py`와 provider quarantine 스크립트·의존 모듈·서비스를 함께 고정했다. 매니페스트 무결성·생성 당시 소스 대조 및 스케줄러 dry-run 통과. quarantine 서비스는 설치·활성화하지 않았고 생산 arm은 계속 차단된다. 실제 증인 연결·백업·운영 설치 승인 증거가 아니다.
- 이전 v7: `docs/acceptance/2026-11-03-backup-candidate-v7/`. 매니페스트 SHA-256 `c74bb539c16a0e5d30c302936fb150a9a6a0f297c3c28fab9c7f9f143230b085`, 186개 파일. 음성 공급자 준비상태 변경 후 생성했으며 보존했다.
- 이전 v6: `docs/acceptance/2026-11-03-backup-candidate-v6/`. 매니페스트 SHA-256 `0c0f9e97c567196fcda4d6b68530e3f240b0e91af5d22d2665cd376631ce5ea5`, 186개 파일. 백업의 GCS+S3 증인 설정 결선을 포함하며 보존했다.
- 이전 v5: `docs/acceptance/2026-11-03-backup-candidate-v5/`. 매니페스트 SHA-256 `67feb155f961b2f01066434cc440e72c176ed9b68b5fcf8b5e972678c76c2ee2`, 186개 파일. Neon S3 기록 목록의 무한 페이지 차단을 포함하며 보존했다.
- 이전 v4: `docs/acceptance/2026-11-03-backup-candidate-v4/`. 매니페스트 SHA-256 `0cec6fd3b5a861bb8fd7e0093be71b97a9f0fd2c7fc5e2ae7637bdbd728b9180`, 186개 파일. 저장소 파기 목록 검사 및 삭제 후 빈 목록 재확인을 포함하며 보존했다.
- 이전 v3: `docs/acceptance/2026-11-03-backup-candidate-v3/`. 매니페스트 SHA-256 `9bec8b46e0f614686a8ace3e5f6db5aad87d90d2fd1aa3d0b26f9d58e80e6d32`, 186개 파일. GCS 기록 목록 검사와 백업 pagination 한도 보완 후 생성했고 보존했다.
- 이전 v2: `docs/acceptance/2026-11-03-backup-candidate-v2/`. 매니페스트 SHA-256 `cca3b65a3ccbbaed57fbcf47cb907ce96b5dd55125422aa3f8c708bc26ecc087`, 186개 파일. 개인정보 기록 readback 수정 후 생성했고 보존했다.
- 아래 첫 후보는 보존된 이전 스냅샷이며 최신 소스가 아니다.
- 후보: `docs/acceptance/2026-11-03-backup-candidate/`, 186개 파일. 이 디렉터리는 acceptance 산출물이며 운영에 설치되지 않았다.
- 독립 매니페스트 SHA-256: `dc481762d046143f2859b401f7073a0d98ee08c9d3615b38e59bc1c3f0c99ed1`.
- 후보 무결성과 생성 당시 체크아웃의 소스를 비교했고, 후보에 포함된 스케줄러를 기존 로컬 가상환경으로 dry-run하여 서비스 중단 없이 실행됨을 확인했다. 신규 migration `4c2d8f71b906`도 스냅샷에 포함된다.
- 이는 운영 파일이나 설정과의 일치, 새 migration의 운영 적용, 백업 완료, 복원 성공, 무중단 운영의 증거가 아니다. 후보 자체에 가상환경이나 PostgreSQL 도구는 포함되지 않는다.

## 읽기 전용 백업 합성 실험

일회용 PostgreSQL·MinIO에서 시험 전용 HTTP 앱으로 DB 공유 잠금 중 GET 응답과 DELETE 503을 확인하고, 별도 DB 연결의 INSERT·DELETE가 차단된 뒤 잠금 해제 시 재개되는 것을 확인했다. 같은 잠금 중 독립 MinIO 객체 생성·삭제는 가능했다. [합성 리허설](acceptance/2026-11-03-backup-readonly-prototype/result.json). 시험 HTTP 앱은 실제 제품 API가 아니고 실제 앱의 GET이 부작용 없이 동작하는지도 확인하지 않았다.

따라서 PostgreSQL 스냅샷·테이블 잠금만으로 저장소 변경, 이미 진행 중인 업로드·삭제 및 외부 작성자를 막을 수 없으며, 개인정보 삭제 동시성·복원 기준점의 안전성도 입증되지 않는다. 운영에서 API를 켠 채 백업하는 설정은 도입하지 않았고 기존 서비스 중단 방식을 유지한다. 실제 전환에는 전 요청/worker의 드레인과 저장소 전체 작성자·진행 중 작업에 대한 검증 가능한 펜스, 실패 시 복구 및 부하 검증이 필요하다.
