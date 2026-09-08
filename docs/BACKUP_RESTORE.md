# 백업과 복구

베타 운영에는 PostgreSQL과 비공개 미디어를 같은 복구 시점으로 되돌리는 절차가 필요합니다. DB 덤프만 복원하면 책의 글은 남아도 그림·PDF가 없을 수 있습니다. 반대로 오래된 백업은 삭제된 콘텐츠나 폐기된 로그인 키를 되살릴 수 있으므로, 복구 중에는 API와 워커를 외부에 공개하지 않습니다.

## 실행 가능한 로컬 리허설

```bash
./scripts/run_backup_restore_rehearsal.sh --report-dir /tmp/storybook-restore-report
```

기존 Docker 이미지 `postgres:15-alpine`, `minio/minio:latest`와 API Python 의존성을 사용합니다. 프로젝트 `.env`, 기존 DB·볼륨, 실서비스 계정, 실제 아동 콘텐츠를 읽지 않습니다. 원격 Docker 소켓은 거절하며 이미지를 내려받지 않습니다.

1. 임시 PostgreSQL·MinIO 두 벌을 무작위 localhost 포트에 생성합니다.
2. Docker 내부 health 외에 호스트에서 PostgreSQL `SELECT 1`이 응답하는지 확인한 뒤 현재 Alembic head로 마이그레이션하고 합성 동화·동의·파기 대기 행·미디어를 넣습니다.
3. PostgreSQL custom-format 덤프와 미디어 백업을 만들고 빈 환경에 복원합니다.
4. 모든 public 테이블의 행 수와 정렬된 행 체크섬, 모든 오브젝트의 SHA-256·크기·Content-Type·메타데이터를 비교합니다.
5. 복원된 sequence, 외래 키, 중복 페이지 방지 제약, 삭제 outbox를 검증합니다. 각 오브젝트의 익명 접근은 차단되고 서명 다운로드는 성공해야 합니다.
6. 임시 DB·미디어·덤프·컨테이너를 정리합니다. 보고서에는 비밀값과 원본 콘텐츠를 남기지 않습니다. 정리 실패도 전체 실패입니다.

`result.json`의 `fixture_restore_seconds`는 작은 합성 데이터의 측정값입니다. 운영 복구시간 목표(RTO), 허용 데이터 손실시간(RPO), 대용량 처리량을 증명하지 않습니다. Redis 큐 복구와 운영 스토리지의 버전 관리·암호화·외부 지역 복제도 별도 검증 대상입니다.

CI의 API 작업에도 같은 리허설이 들어 있으며, 합성 데이터의 결과 JSON만 7일 보관합니다.

## 운영 백업 계약

운영 대상과 보관 장소가 준비되면 다음을 적용합니다.

- 제한 베타의 운영 목표는 **매일 백업, 변경 배포 직전 백업, 최대 24시간 데이터 손실, 4시간 안에 복구**입니다. 목표이며 아직 운영 데이터 크기로 측정하지 않았습니다. 계정 폐기·복구키 회전·동의 철회·콘텐츠 삭제 기록은 이 24시간 손실 허용 대상에서 제외합니다.
- API 쓰기와 워커를 멈추고 진행 중인 생성 작업이 종료·실패 처리된 상태에서 DB와 미디어의 일관된 백업을 취합니다. 무중단 백업은 DB 복구시점과 오브젝트 버전을 함께 고정할 수 있는 운영 스토리지가 준비된 뒤 적용합니다.
- DB 덤프, 해당 시점의 미디어 키·버전·체크섬 목록, 배포 이미지 digest, Alembic revision을 하나의 백업 세트로 취급합니다. API 키·`.env`·실제 bearer 키·다운로드 서명 URL은 증빙이나 코드 저장소에 복사하지 않습니다.
- 백업은 운영 서버와 분리된 암호화 저장소에 제한된 권한으로 보관합니다. 초기 운영값은 일간 백업 7개, 주간 백업 4개입니다. 삭제 정책의 법무 검토가 끝나기 전에는 이 값을 아동 데이터 보관 약속으로 대외 공지하지 않습니다.
- 현재 `deploy.sh backup`은 **DB 전용**입니다. Git에서 제외된 `backups/`(0700)에 0600 custom-format 덤프를 만들고 `pg_restore --list`가 성공한 완성 파일만 `.dump`로 공개합니다. 실패·중단 시 임시 파일은 지웁니다. 이 명령만 실행하고 미디어 백업이 끝났다고 기록하지 않습니다.

```bash
# 운영자가 대상과 백업 창을 확정한 후 해당 서버에서 실행합니다.
./scripts/deploy.sh --env-file infra/.env backup
```

미디어는 확정한 스토리지의 비공개 버전 관리/백업 기능으로 별도 저장합니다. 공급자·버킷·암호화 키·복제 대상이 아직 미정이므로, 개발용 MinIO를 운영 저장소로 간주해 자동 연결하지 않습니다.

## 복구 순서와 공개 조건

1. 트래픽을 차단하고 API·Celery 워커를 정지합니다. 장애 원본을 덮어쓰지 말고 새 DB와 비공개 버킷을 준비합니다.
2. 백업 체크섬을 확인하고 `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`로 빈 DB에 복원합니다. 원래 미디어 키·오브젝트 버전·메타데이터를 복원하고 행·미디어 체크섬을 비교합니다.
3. **백업 이후 삭제·동의 철회·계정 키 폐기/회전 기록을 반드시 다시 적용합니다.** `storage_purge_tasks`의 대기·실패 지시를 처리하고, 이미 삭제된 계정/책/사진이 다시 보이지 않는지 확인합니다. 오래된 DB의 `account_identities`는 폐기된 기기키·복구코드를 다시 유효하게 만들 수 있습니다. 최신 인증 상태를 안전하게 보존·재적용할 수 없으면 해당 복구 환경을 공개하지 않습니다. 운영자가 본인 확인 없이 복구코드를 임의 발급해서 해결하지 않습니다. 자세한 인증 복구 제약은 [ACCOUNT_RECOVERY.md](ACCOUNT_RECOVERY.md)를 참조합니다.
4. Redis를 이전 큐 스냅샷으로 무조건 되돌리지 않습니다. 외부 AI 생성이 중복 청구될 수 있습니다. DB의 queued/running 작업을 먼저 대조하고, 불확실한 실행 중 작업은 SLA 실패·환불 정책으로 정리한 뒤 승인된 대기 작업만 재개합니다. Korea-local 비용 카운터를 보수적으로 복원하기 전에는 새 생성을 열지 않습니다.
5. 복원에 맞는 이미지 digest와 Alembic revision을 확인합니다. API 내부 읽기 검증 → 부모 계정 소유권 → 실제 미디어 서명 다운로드/익명 차단 → 공유 철회 → 삭제 검증 → `/health/ready`와 TLS를 확인합니다.
6. 문제가 없을 때 트래픽과 워커를 열고 완료 시간·복구 시점·손실 범위·미완료 파기를 기록합니다. 월 1회와 DB/스토리지 변경 때마다 격리 환경에서 다시 리허설합니다.

운영 배포 대상과 별도 백업 저장소, 최신 삭제·인증 폐기 기록의 재적용 수단이 확보되기 전까지 운영 재해 복구 완료로 표시하지 않습니다.

## 외부 PostgreSQL·비공개 S3 백업 도구

`scripts/backup_external.py`는 명시한 env 파일만 읽고 기본적으로 원격 요청·파일 생성 없이 설정을 점검합니다. 자격증명이 들어간 URL을 프로세스 인수로 넘기거나 출력하지 않습니다. `--output-dir`은 확정한 암호화 백업 저장소의 0700 디렉터리입니다.

```bash
# 아래 명령은 구성만 확인합니다. DB·버킷에 접속하지 않습니다.
./apps/api/venv/bin/python scripts/backup_external.py \
  --env-file infra/.env.external --output-dir /approved-encrypted-backups/storybook
```

실제 백업은 운영자가 대상·백업 창·암호화 장소를 확정한 뒤 `--execute --quiesced --destination-encrypted --ca-file /path/on/backup-host/provider-ca.crt`를 추가합니다. 이 세 확인은 운영자의 사실 확인이며 도구가 호스트 암호화나 API 중지를 자동으로 증명하지 않습니다. `pg_dump`, `pg_restore`, `psql`과 API Python 의존성이 백업 호스트에 있어야 합니다. PostgreSQL 클라이언트는 대상 서버 major 버전과 호환되는 버전을 사용합니다.

- 작업은 외부 DB와 S3에 **읽기만** 수행합니다. API 쓰기·워커가 중지되어 있어야 하고 DB에 queued/running 작업이 남아 있으면 차단합니다. 자동 배포·중지·복구·백업 삭제는 하지 않습니다.
- `public` 앱 스키마의 custom-format 덤프를 생성해 `pg_restore --list`를 검사합니다. Supabase가 관리하는 `auth`·`storage` 스키마를 앱 DB로 덮어쓰기 위한 덤프를 만들지 않습니다.
- 전용 버킷의 오브젝트를 ETag 조건으로 읽고, 전후 목록이 같으며 크기가 맞을 때만 새 완성 세트를 등록합니다. 원래 key는 비공개 manifest에 저장하고 로컬 파일 이름은 SHA-256을 사용해 경로 이탈을 막습니다.
- 0700 세트에 0600 덤프·오브젝트·manifest를 저장합니다. manifest에는 SHA-256·크기·Content-Type·메타데이터·이미지 SHA/digest·Alembic revision이 들어갑니다. 실패·중단 시 이번 임시 세트만 삭제하고 이전 백업을 보존합니다.
- `BACKUP_CREATED_NOT_RESTORE_VERIFIED`는 백업 파일 생성만 뜻합니다. 결과 JSON에는 콘텐츠나 원래 오브젝트 key가 나오지 않지만, 백업 자체에는 개인정보가 있으므로 공개 산출물로 옮기지 않습니다. 그 이후의 삭제·동의 철회·인증폐기 기록을 재적용하지 않은 복원본은 공개하면 안 됩니다.

`deploy.sh backup`은 내부 PostgreSQL 서비스가 없는 외부 Compose를 명시 거절합니다. 외부 백업 도구의 mock 회귀는 실제 Supabase 덤프·미디어 복원·운영 RTO/RPO나 백업 장소의 암호화를 검증하지 않습니다.

## 복구 전 오프라인 무결성 확인

```bash
./apps/api/venv/bin/python scripts/verify_backup_set.py --backup-set /approved-private-backup/external-set
```

이 명령은 선택한 로컬 세트만 읽고 DB 덤프와 모든 미디어의 SHA-256·크기, 누락·추가·중복 항목, 경로 이탈·심볼릭 링크를 검사합니다. 외부 서비스에 접속하거나 복원·삭제하지 않습니다. 결과에는 원본 미디어 키·본문·파일 경로가 나오지 않습니다. `CHECKSUMS_VERIFIED_NOT_RESTORED`는 파일 무결성 검사이며, 덤프와 manifest를 함께 바꿀 권한을 가진 공격자에 대한 진위 보증은 아닙니다. 최신 삭제·인증 폐기 기록 적용과 격리 복구 리허설은 그대로 필요합니다.
