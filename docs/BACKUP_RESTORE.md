# 백업과 복구

베타 운영에는 PostgreSQL과 비공개 미디어를 같은 복구 시점으로 되돌리는 절차가 필요합니다. DB 덤프만 복원하면 책의 글은 남아도 그림·PDF가 없을 수 있습니다. 반대로 오래된 백업은 삭제된 콘텐츠나 폐기된 로그인 키를 되살릴 수 있으므로, 복구 중에는 API와 워커를 외부에 공개하지 않습니다.

## 실행 가능한 로컬 리허설

```bash
docker build -f infra/Dockerfile.minio-test -t storybook-minio-test:2025-09-07 infra
./scripts/run_backup_restore_rehearsal.sh --report-dir /tmp/storybook-restore-report
```

로컬 Docker 이미지 `postgres:15-alpine`, `storybook-minio-test:2025-09-07`와 API Python 의존성을 사용합니다. 위 빌드는 공식 MinIO 릴리스 바이너리를 받고 아키텍처별 SHA-256을 확인하며 테스트에만 사용합니다. 리허설 자체는 프로젝트 `.env`, 기존 DB·볼륨, 실서비스 계정, 실제 아동 콘텐츠를 읽지 않습니다. 원격 Docker 소켓은 거절하며 이미지를 내려받지 않습니다.

1. 임시 PostgreSQL·MinIO 두 벌을 무작위 localhost 포트에 생성합니다.
2. Docker 내부 health 외에 호스트에서 PostgreSQL `SELECT 1`이 응답하는지 확인한 뒤 현재 Alembic head로 마이그레이션하고 합성 동화·동의·파기 대기 행·미디어를 넣습니다.
3. PostgreSQL custom-format 덤프와 미디어 백업을 만들고 빈 환경에 복원합니다.
4. 모든 public 테이블의 행 수와 정렬된 행 체크섬, 모든 오브젝트의 SHA-256·크기·Content-Type·메타데이터를 비교합니다.
5. 복원된 sequence, 외래 키, 중복 페이지 방지 제약, 삭제 outbox를 검증합니다. 각 오브젝트의 익명 접근은 차단되고 서명 다운로드는 성공해야 합니다.
6. 임시 DB·미디어·덤프·컨테이너를 정리합니다. 보고서에는 비밀값과 원본 콘텐츠를 남기지 않습니다. 정리 실패도 전체 실패입니다.

`result.json`의 `fixture_restore_seconds`는 작은 합성 데이터의 측정값입니다. 운영 복구시간 목표(RTO), 허용 데이터 손실시간(RPO), 대용량 처리량을 증명하지 않습니다. Redis 큐 복구와 운영 스토리지의 버전 관리·암호화·외부 지역 복제도 별도 검증 대상입니다.

별도 오프라인 리허설은 `python3 scripts/run_offline_restore_rehearsal.py --report-dir /tmp/storybook-offline-restore`로 실행합니다. 네트워크를 차단한 컨테이너에서 로컬 GCS 대역으로 완료 표식을 게시하고 격리 복원본의 개인정보 기록과 대조합니다. 백업 후 앱의 삭제 경로에서 생성한 책·음성 삭제 기록과 책 삭제 확인증을 재적용합니다. 마지막 기록을 뺀 전송은 미디어가 바뀌기 전에 거부되며, 정상 재적용 뒤에는 삭제된 미디어의 기존 서명 링크만 거부됩니다. [격리 검증 기록](acceptance/2026-11-08-offline-book-erasure/verification.json)

호스트의 `umask 077` 환경에서도 시험 이미지의 비특권 사용자가 합성 검증 코드를 읽을 수 있습니다. 격리 백업 반입이나 개인정보 기록 검증 작업이 결과를 보내기 전에 종료되면 도구는 실패를 기록합니다. 실제 로컬 Docker에서 두 작업을 강제 종료했을 때 해당 작업의 컨테이너만 제거됐습니다. [격리 실패 복구 검증](acceptance/2026-11-08-quarantine-worker-exit/verification.json)

CI의 API 작업에도 같은 리허설이 들어 있으며, 합성 데이터의 결과 JSON만 7일 보관합니다.

## 운영 백업 계약

운영 대상과 보관 장소가 준비되면 다음을 적용합니다.

- 제한 베타의 운영 목표는 **매일 백업, 변경 배포 직전 백업, 최대 24시간 데이터 손실, 4시간 안에 복구**입니다. 목표이며 아직 운영 데이터 크기로 측정하지 않았습니다. 계정 폐기·복구키 회전·동의 철회·콘텐츠 삭제 기록은 이 24시간 손실 허용 대상에서 제외합니다.
- API 쓰기와 워커를 멈추고 진행 중인 생성 작업이 종료·실패 처리된 상태에서 DB와 미디어의 일관된 백업을 취합니다. 무중단 백업은 DB 복구시점과 오브젝트 버전을 함께 고정할 수 있는 운영 스토리지가 준비된 뒤 적용합니다.
- 새 예약 백업 후보는 결과 로그의 `timings_ms`에 사전 대기 작업 검사, 서비스 중지·복구를 포함한 전체 보호 구간, 로컬 캡처, 원격 게시, 개인정보 체크포인트, 게시 직전 저장소 검증의 경과 시간을 기록합니다. 게시 시간에는 최종 체크포인트와 저장소 검증이 포함됩니다. 전체 보호 구간에는 중지 확인과 복구 검증도 포함되므로 실제 외부 API 중단 시간은 별도 외부 관측과 대조합니다.
- DB 덤프, 해당 시점의 미디어 키·버전·체크섬 목록, 배포 이미지 digest, Alembic revision을 하나의 백업 세트로 취급합니다. API 키·`.env`·실제 bearer 키·다운로드 서명 URL은 증빙이나 코드 저장소에 복사하지 않습니다.
- 예약 백업 후보는 DB 스냅샷 안에서 원본 미디어를 최대 두 개씩 내려받습니다. 개별 응답의 ETag·변경 시각·크기와 백업 전후 목록을 확인합니다. 읽기가 실패하면 실행 중인 다운로드를 모두 종료한 뒤 부분 파일을 정리합니다. 별도 CLI의 기본 다운로드 수는 한 개입니다.
- 최신 예약 백업 후보는 DB 덤프와 미디어 파일의 전송·원격 재검증에 두 슬롯을 함께 사용합니다. 모든 원격 파일을 검증한 뒤 manifest를 게시하고, 완료 표식 게시 직전에 개인정보 기록을 다시 확인합니다. 예약 경로에서는 DB·미디어 경계도 확인합니다. 전송 직전 표식의 크기와 SHA-256이 생성 시점과 일치해야 합니다. 앞선 확인이 실패하면 진행 중인 전송을 종료한 뒤 서비스 복구 절차로 넘어갑니다.
- 백업은 운영 서버와 분리된 암호화 저장소에 제한된 권한으로 보관합니다. 초기 운영값은 일간 백업 7개, 주간 백업 4개입니다. 삭제 정책의 법무 검토가 끝나기 전에는 이 값을 아동 데이터 보관 약속으로 대외 공지하지 않습니다.
- 현재 `deploy.sh backup`은 **DB 전용**입니다. Git에서 제외된 `backups/`(0700)에 0600 custom-format 덤프를 만들고 `pg_restore --list`가 성공한 완성 파일만 `.dump`로 공개합니다. 실패·중단 시 임시 파일은 지웁니다. 이 명령만 실행하고 미디어 백업이 끝났다고 기록하지 않습니다.

```bash
# 운영자가 대상과 백업 창을 확정한 후 해당 서버에서 실행합니다.
./scripts/deploy.sh --env-file infra/.env backup
```

미디어는 확정한 스토리지의 비공개 버전 관리/백업 기능으로 별도 저장합니다. 공급자·버킷·암호화 키·복제 대상이 아직 미정이므로, 개발용 MinIO를 운영 저장소로 간주해 자동 연결하지 않습니다.

### 제한 운영의 예약 백업 검증 저장소 연결

예약 백업 명령에서 독립 검증 저장소 인자가 빠졌을 때는 승인된 백업 후보에서 아래 계획을 먼저 생성합니다. 후보의 경로는 호스트에서 검증한 절대 경로로 지정합니다.

```bash
/opt/ai-story-book/current/apps/api/venv/bin/python \
  /path/to/verified-backup-candidate/scripts/run_scheduled_backup.py --plan-systemd-witness
```

이 계획은 현재 로드된 예약 명령의 실행 경로와 인자를 보존하고, 검증 저장소 인자만 넣은 systemd drop-in을 출력합니다. 현재 systemd의 로딩 상태, 고정 스크립트의 해시와 인자 지원, 백업 설정 파일, API·worker의 DB·미디어·개인정보 기록 연결을 읽기 전용으로 확인합니다. `SCHEDULER_WITNESS_PLAN_CHECKED`가 표시되면 `loaded_exec_start_sha256`, `proposed_exec_start_sha256`, `pinned_runner_sha256`, `scheduler_bindings_sha256`을 검토 기록에 보관합니다. 마지막 값은 확정된 인자의 해시이며 버킷 이름을 출력하지 않습니다. `already_bound=true`이면 추가 파일을 만들 필요가 없습니다. [systemd 서비스 설정](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)

계획 도구는 `backup-config.env`의 예약 실행용 버킷 변수 세 개만 허용합니다. 이 파일에서 실행 경로나 자격 증명을 덮어쓰면 사전 검사와 예약 실행 조건이 달라질 수 있으므로 계획을 거부합니다.

1. 승인된 작업 창에서 위 명령에 `--verify-prerequisites`를 추가합니다. `--expected-loaded-exec-start-sha256`, `--expected-pinned-runner-sha256`, `--expected-scheduler-bindings-sha256`에는 검토 기록의 해당 해시를 지정합니다. 도구가 계획의 인자로 원본과 개인정보 기록을 읽은 뒤 예약 명령·버킷 설정·고정 스크립트를 다시 대조합니다. 도구가 `prerequisites_checked=true`와 함께 출력한 계획을 사용합니다. 예약 백업이 실행 중이거나 복구 마커가 있으면 관련 복구 절차를 먼저 따릅니다.
2. 기존 서비스 파일과 설정 파일을 보존한 채, 계획에서 나온 drop-in만 새 파일 `/etc/systemd/system/asb-backup.service.d/90-journal-witness.conf`에 적용합니다. 같은 이름의 파일이 있으면 현재 상태를 대조합니다. `systemd-analyze verify` 통과 후 `systemctl daemon-reload`를 실행합니다. 이번에는 `proposed_exec_start_sha256`을 `--expected-loaded-exec-start-sha256`에 지정하고 같은 고정 스크립트 해시를 함께 대조합니다. `prerequisites_checked=true`와 `already_bound=true`를 확인합니다.
3. 설정을 되돌릴 때는 이번에 추가한 drop-in만 unit 검색 경로 밖으로 옮기고 `systemctl daemon-reload`를 실행합니다. 최초 검토 기록의 `loaded_exec_start_sha256`과 `pinned_runner_sha256`으로 되돌아왔는지 확인합니다. 실행 중인 백업의 복구 마커는 이 과정에서 제거하지 않습니다.
4. 예약이 활성 상태인지와 다음 실행 시각을 확인합니다. 그 실행에서 서비스 종료 성공, 새 원격 검증 표식, 정상 모니터링 신호를 각각 확인합니다. 새 백업은 별도 DB·미디어에 복원한 뒤 최신 삭제·동의 철회·인증 폐기 기록의 재적용과 비공개 미디어 접근 제어까지 확인합니다.

예약 실행은 `source_preflight`에서 PostgreSQL 접속과 백업 도구 버전을 확인하고 원본 S3 목록의 모든 페이지에서 미디어 크기를 합산합니다. `local_destination_preflight`는 서비스 중지 전에 대상 디스크에 미디어 합계와 추가 여유 공간 1GiB가 있는지 확인합니다. 백업 중 변경과 DB 덤프 크기는 별도로 영향을 줄 수 있습니다. `destination_preflight`에서는 예약 실행의 인증 정보로 전용 GCS 백업 버킷에 객체 생성·읽기 권한이 있는지 조회합니다. 어느 단계든 실패하면 API와 worker는 실행을 계속합니다. 사전 점검은 버킷에 파일을 쓰지 않습니다. 실제 게시와 전송 무결성은 백업 때 다시 확인합니다. [Cloud Storage 권한 확인 API](https://docs.cloud.google.com/storage/docs/json_api/v1/buckets/testIamPermissions)

실제 예약 실행도 API·worker 연결을 확인한 뒤 개인정보 기록을 `journal_preflight` 단계에서 DB outbox와 대조합니다. 대조에 실패하면 첫 실패 후 1초, 두 번째 실패 후 2초를 기다려 전체 대조를 다시 수행합니다. 세 번째 대조에서도 기록이 빠지거나 서로 다르면 서비스 중단과 백업 생성을 시작하기 전에 실패합니다. 쓰기를 막은 뒤 캡처 전과 완료 표식 게시 직전의 대조는 한 번만 수행하며, 실패하면 즉시 진행을 중단합니다.

서비스를 중단하지 않고 보완된 예약 설정을 확인하려면 검증한 후보의 `run_scheduled_backup.py`에 예약과 동일한 파일·버킷·디렉터리 인자를 전달하고 `--execute` 대신 `--check-prerequisites`를 지정합니다. API와 worker의 연결, 원본 접속과 도구 버전, 전용 백업 버킷 권한, 미디어를 포함한 로컬 디스크 여유 공간을 확인하고 암호화된 개인정보 기록을 DB outbox와 대조합니다. 실패 시 해당 단계와 오류 유형을 출력합니다. 점검 중 쓰기가 일어나면 기록 대조가 실패할 수 있으므로 실제 백업에서는 쓰기를 멈춘 뒤 다시 대조합니다.

백업 감시 후보는 현재 부팅의 마지막 `asb-backup.service` 실행과 일치하는 구조화된 실패 로그에서 `failure_stage`를 출력합니다. 기존 `backup_health` 신호를 먼저 보내고, 장애일 때 `backup_failure_stage`에 진단 코드 하나를 보냅니다. 복구 대기·예약·디스크 문제를 우선하고, 해당 항목이 없으면 확인된 실행 단계나 아래 대체 코드를 사용합니다. 상세 로그와 예외 메시지는 외부 신호에 포함되지 않습니다. 보조 전송이 실패하면 `stage_signal_sent=false`가 남습니다.

| 코드 | 예약 백업 단계 |
| --- | --- |
| 1 | `configuration` |
| 2 | `backup_source` |
| 3 | `writer_bindings` |
| 4 | `initialization` |
| 5 | `source_preflight` |
| 6 | `journal_preflight` |
| 7 | `guarded_backup` |
| 8 | 백업 복구 대기 |
| 9 | 제공자 전환 복구 대기 |
| 10 | 예약 타이머 비활성, 부팅 자동 시작 미등록 또는 상태 확인 불가 |
| 11 | 백업 또는 상태 디스크 여유 공간 부족 |
| 12 | 완료 시각이 미래로 기록됨 |
| 13 | 최근 검증 백업이 48시간을 넘김 |
| 14 | 완료 기록을 읽거나 검증할 수 없음 |
| 15 | 서비스 실패, 상세 실행 단계 미확인 |
| 16 | 서비스 실행 시간 초과 |
| 17 | 서비스가 신호 또는 메모리 부족으로 종료됨 |
| 18 | 감시 검사 실패 또는 출력 형식 오류 |
| 19 | 백업 서비스 결과를 읽을 수 없음 |
| 20 | `destination_preflight`에서 대상 버킷 권한 확인 실패 |
| 21 | `local_destination_preflight`에서 백업 디스크 접근 또는 미디어 포함 여유 공간 확인 실패 |

운영 호스트 접근이 가능해지면 `systemctl show asb-backup.service -p Result -p ExecMainStatus`로 결과를 확인하고, 검토한 `check_backup_status.py`로 현재 부팅의 마지막 실행 기록을 읽습니다. 구형 실행기에 단계명이 없어도 등록된 예외 종류와 파일명·줄 번호를 확인할 수 있습니다. 로그 본문은 결과에 포함되지 않습니다. 복구 대기 코드 8·9는 해당 복구 절차를 먼저 따릅니다. 코드 15–19는 실행 단계가 확인되지 않은 상태입니다. [systemd 서비스 종료 결과](https://manpages.debian.org/bookworm/systemd/systemd.exec.5.en.html)

코드 10은 `systemctl show asb-backup.timer -p ActiveState -p UnitFileState`로 확인합니다. 정상 예약은 `ActiveState=active`와 `UnitFileState=enabled`를 모두 만족해야 합니다. 실행 중인 타이머라도 `enabled-runtime` 또는 `disabled`이면 재부팅 후 자동 시작을 보장할 수 없습니다.

예약 명령이 실패로 종료하면 상태 디렉터리의 `last-scheduled-failure.json`에 실패 시각과 허용된 단계만 보관합니다. 부팅 후 systemd가 이전 실패를 표시하지 않아도 새 검증 백업이 기록되기 전까지 이 단계로 경보를 유지합니다. 현재 실행의 시간 초과·강제 종료 결과가 있으면 그 결과를 우선합니다. 사전 확인 명령은 이 기록을 바꾸지 않습니다.

예약 백업 후보는 API를 멈추기 전과 멈춘 직후에 DB의 미완료 작업을 확인하고, Celery의 실행 중·예약됨·실행 예정 작업을 동시에 조회합니다. 각 조회에 지정 워커 한 대만 빈 목록으로 응답해야 다음 단계로 넘어갑니다. API를 멈춘 뒤 확인에 실패하면 복구 절차로 넘어갑니다. 스냅샷은 워커를 멈춘 뒤에 생성합니다.

복구 후보는 `restart-required.json`을 지우기 전에 nginx 컨테이너에서 API의 `/health/live`를 확인하고 지정된 Celery 워커의 `pong`을 확인합니다. nginx를 재로딩한 뒤 이전 워커가 종료되고 새 워커가 시작됐는지 확인합니다. 이어서 같은 VM의 nginx에 운영 인증서를 검증하는 HTTPS 요청을 보내 `/health/live`의 HTTP 200과 `alive` 응답을 확인합니다. 어느 확인이든 실패하면 기록을 유지합니다. 외부 접근과 AI 제공자·DB·미디어를 포함한 전체 준비 상태는 외부에서 `/health/ready`를 호출해 별도로 확인합니다.

백업 감시는 최근 성공 기록이 있어도 `restart-required.json`이 남아 있거나 해당 경로를 검사할 수 없으면 `backup_recovery_pending`으로 보고합니다. 외부 백업 상태에는 실패 신호를 보내고 복구 표식의 내용은 공개하지 않습니다.

부팅과 백업 종료 시 호출하는 복구 명령은 잠금 경합이나 서비스 응답 실패가 일시적이면 5초, 5초, 15초, 25초, 30초 간격으로 최대 여섯 번 시도합니다. Docker 명령, 응답 확인과 대기를 모두 합쳐 150초 한도를 적용합니다. 다음 시도 전에 배포·키 교체 기록을 다시 확인합니다. 주 복구 기록이 없어도 `docker-mutation.json`이 남아 있으면 백업과 자동 재시작을 중단합니다. 복구를 확인할 수 없으면 기록을 보존합니다.

격리 Docker에서 API와 Celery worker를 정지하고 새 복구 프로세스로 시험했습니다. nginx HTTPS가 처음 세 번 503을 반환하는 동안 복구 기록이 남았고, 네 번째 시도에서 유효한 인증서와 200·`alive` 응답을 확인한 뒤 제거됐습니다. 같은 후보의 합성 PostgreSQL·비공개 S3 복원 검사는 31개를 통과했습니다. 운영 호스트 재부팅과 실제 운영 백업 복원은 별도입니다. [복구 재현 결과](acceptance/2026-11-08-https-recovery-rehearsal/result.json)

## 복구 순서와 공개 조건

1. 트래픽을 차단하고 API·Celery 워커를 정지합니다. 장애 원본을 덮어쓰지 말고 새 DB와 비공개 버킷을 준비합니다.
2. 백업 체크섬을 확인하고 `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`로 빈 DB에 복원합니다. 일부 Neon 덤프는 `public` 스키마 생성문을 포함하므로, **새로 만든 격리 대상 DB에서만** 기본 빈 `public` 스키마를 먼저 제거해야 충돌하지 않습니다. 기존 DB의 스키마를 제거해서는 안 됩니다. 원래 미디어 키·오브젝트 버전·메타데이터를 복원하고 행·미디어 체크섬을 비교합니다.
3. **백업 이후 삭제·동의 철회·계정 키 폐기/회전 기록을 반드시 다시 적용합니다.** `storage_purge_tasks`의 대기·실패 지시를 처리하고, 이미 삭제된 계정/책/사진이 다시 보이지 않는지 확인합니다. 오래된 DB의 `account_identities`는 폐기된 기기키·복구코드를 다시 유효하게 만들 수 있습니다. 최신 인증 상태를 안전하게 보존·재적용할 수 없으면 해당 복구 환경을 공개하지 않습니다. 운영자가 본인 확인 없이 복구코드를 임의 발급해서 해결하지 않습니다. 자세한 인증 복구 제약은 [ACCOUNT_RECOVERY.md](ACCOUNT_RECOVERY.md)를 참조합니다.
4. Redis를 이전 큐 스냅샷으로 무조건 되돌리지 않습니다. 외부 AI 생성이 중복 청구될 수 있습니다. DB의 queued/running 작업을 먼저 대조하고, 불확실한 실행 중 작업은 SLA 실패·환불 정책으로 정리한 뒤 승인된 대기 작업만 재개합니다. Korea-local 비용 카운터를 보수적으로 복원하기 전에는 새 생성을 열지 않습니다.
5. 복원에 맞는 이미지 digest와 Alembic revision을 확인합니다. API 내부 읽기 검증 → 부모 계정 소유권 → 실제 미디어 서명 다운로드/익명 차단 → 공유 철회 → 삭제 검증 → `/health/ready`와 TLS를 확인합니다.
6. 문제가 없을 때 트래픽과 워커를 열고 완료 시간·복구 시점·손실 범위·미완료 파기를 기록합니다. 월 1회와 DB/스토리지 변경 때마다 격리 환경에서 다시 리허설합니다.

네트워크가 차단된 복원 도구는 덤프를 단일 트랜잭션으로 복원합니다. 미디어 목록의 범위·항목 수·페이지 종료 표지가 응답 내용과 맞는지 확인합니다. 각 미디어의 체크섬·메타데이터와 익명 GET의 `403 AccessDenied`를 모두 확인한 뒤 격리 복원 결과를 기록합니다. 오프라인 리허설에서는 서명 URL로 합성 음원을 내려받고, 후속 삭제 기록을 적용하면 기존 서명 URL도 `404`를 반환하는지 확인합니다.

개인정보 기록 대조와 재적용에는 운영자가 지정한 하나의 제한 시간을 사용합니다. Docker 격리 상태를 조회하는 짧은 시간 제한은 DB·미디어 검증에 적용하지 않습니다. 전체 시간이 지나면 다음 검사를 시작하지 않고 해당 격리 환경을 정리합니다.

운영 배포 대상과 별도 백업 저장소, 최신 삭제·인증 폐기 기록의 재적용 수단이 확보되기 전까지 운영 재해 복구 완료로 표시하지 않습니다.

## 외부 PostgreSQL·비공개 S3 백업 도구

`scripts/backup_external.py`는 명시한 env 파일만 읽고 기본적으로 원격 요청·파일 생성 없이 설정을 점검합니다. 자격증명이 들어간 URL을 프로세스 인수로 넘기거나 출력하지 않습니다. `--output-dir`은 확정한 암호화 백업 저장소의 0700 디렉터리입니다.

```bash
# 아래 명령은 구성만 확인합니다. DB·버킷에 접속하지 않습니다.
./apps/api/venv/bin/python scripts/backup_external.py \
  --env-file infra/.env.external --output-dir /approved-encrypted-backups/storybook
```

실제 백업은 운영자가 대상·백업 창·암호화 장소를 확정한 뒤 `--execute --quiesced --destination-encrypted --ca-file /path/on/backup-host/provider-ca.crt`를 추가합니다. 이 세 확인은 운영자의 사실 확인이며 도구가 호스트 암호화나 API 중지를 자동으로 증명하지 않습니다. `pg_dump`, `pg_restore`, `psql`과 API Python 의존성이 백업 호스트에 있어야 합니다. 실행 시 서버 버전과 `pg_dump`·`pg_restore`의 major 버전이 모두 같은지 확인하고 다르면 백업 전에 중단합니다. URL에 `channel_binding=require`가 있으면 libpq 자식 프로세스에도 동일하게 강제합니다.

- 작업은 외부 DB와 S3에 **읽기만** 수행합니다. API 쓰기·워커가 중지되어 있어야 하고, 백업 시작과 끝에 queued/running 작업, 완료·취소되지 않은 저장소 파기 지시 또는 외부에 게시되지 않은 개인정보 변경 기록이 있으면 차단합니다. 개인정보 기록 테이블이 없는 구형 DB에서도 안전하게 실패합니다. 이 점검은 실제 쓰기 중지를 증명하거나 백업 이후 발생한 삭제를 복구 시 재적용하지 않습니다. 자동 배포·중지·복구·백업 삭제는 하지 않습니다.
- 백업 앞뒤의 PostgreSQL 트랜잭션 스냅샷이 다르면 완료 세트를 폐기한다. 이는 작업·삭제가 백업 중 빠르게 완료돼 대기열에서 사라진 경우를 일부 감지하지만, 실제 쓰기 중지를 입증하지 않고 백업 완료 이후 삭제를 재적용하지 않는다. 무관한 쓰기나 DB 내부 변화로도 안전하게 실패할 수 있다.
- `public` 앱 스키마의 custom-format 덤프를 생성해 `pg_restore --list`를 검사합니다. Supabase가 관리하는 `auth`·`storage` 스키마를 앱 DB로 덮어쓰기 위한 덤프를 만들지 않습니다.
- 전용 버킷의 오브젝트를 ETag 조건으로 읽고, 전후 목록이 같으며 크기가 맞을 때만 새 완성 세트를 등록합니다. 원래 key는 비공개 manifest에 저장하고 로컬 파일 이름은 SHA-256을 사용해 경로 이탈을 막습니다.
- 0700 세트에 0600 덤프·오브젝트·manifest를 저장합니다. manifest에는 SHA-256·크기·Content-Type·메타데이터·이미지 SHA/digest·Alembic revision이 들어갑니다. 실패·중단 시 이번 임시 세트만 삭제하고 이전 백업을 보존합니다.
- `BACKUP_CREATED_NOT_RESTORE_VERIFIED`는 백업 파일 생성만 뜻합니다. 결과 JSON에는 콘텐츠나 원래 오브젝트 key가 나오지 않지만, 백업 자체에는 개인정보가 있으므로 공개 산출물로 옮기지 않습니다. 그 이후의 삭제·동의 철회·인증폐기 기록을 재적용하지 않은 복원본은 공개하면 안 됩니다.

`deploy.sh backup`은 내부 PostgreSQL 서비스가 없는 외부 Compose를 명시 거절합니다. 외부 백업 도구의 mock 회귀는 실제 Supabase 덤프·미디어 복원·운영 RTO/RPO나 백업 장소의 암호화를 검증하지 않습니다.

격리 재적용기의 완료된 파기 검증은 목록 페이지의 버킷·접두사·KeyCount와 중복 항목, 예기치 않은 CommonPrefixes 및 마지막 이어가기 토큰을 확인합니다. 한 파기 대상의 목록은 10,000페이지와 100,000키를 넘으면 검증 불가로 처리해 격리를 유지합니다. 실제 운영 버킷 호환성이나 복원 후 최신 삭제 기록의 완전성을 입증하는 검사는 아닙니다.

## 복구 전 오프라인 무결성 확인

```bash
./apps/api/venv/bin/python scripts/verify_backup_set.py --backup-set /approved-private-backup/external-set
```

이 명령은 선택한 로컬 세트만 읽고 DB 덤프와 모든 미디어의 SHA-256·크기, 누락·추가·중복 항목, 경로 이탈·심볼릭 링크를 검사합니다. 외부 서비스에 접속하거나 복원·삭제하지 않습니다. 결과에는 원본 미디어 키·본문·파일 경로가 나오지 않습니다. `CHECKSUMS_VERIFIED_NOT_RESTORED`는 파일 무결성 검사이며, 덤프와 manifest를 함께 바꿀 권한을 가진 공격자에 대한 진위 보증은 아닙니다. 최신 삭제·인증 폐기 기록 적용과 격리 복구 리허설은 그대로 필요합니다.
