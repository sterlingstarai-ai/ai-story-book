# 기존 운영 백업 가드와 제공자 키 교체 경합

운영에서 읽기 전용으로 확인한 기존 `backup_service_guard.py` SHA-256은
`9de56dad4e7535116124f3f2fe89136c3e9c604679e86a4f350ab8117d504e86`다.
이 버전의 `run()`에는 별도의 `_run_unlocked()`가 없고, 복구 경로는 provider
rotation marker를 확인하지 않는다. 최신 로컬 가드가 운영에 이미 설치된 것으로
가정하지 않는다.

`scripts/provider_legacy_backup_guard.py`는 정확한 위 SHA와 소스 구조에만 적용되는
별도 overlay를 생성한다. 원본은 수정하거나 설치하지 않는다. 생성된 소스는
`run()`이 `backup.lock`을 확보한 뒤 작업 시작 전에 provider marker를 검사하고,
기존 `_recover_unlocked()`도 재시작 전에 검사한다. 새 코드와의 호환을 위해
`NARRATION_RECOVERY_MARKER`와 `assert_no_narration_recovery()`도 제공하고 narration
marker 및 전환 전 `docker-mutation.json` 의도도 같은 잠금 아래 확인한다. marker의 존재, 끊어진
심볼릭 링크, 상위 경로의 심볼릭 링크 또는 확인 오류는 모두 차단이다. 동일한
`backup.lock`을 실제 rotation 작성자도 끝까지 준수한다는 전제가 필요하다.

현재 확보한 실제 운영 소스와 fake runtime을 사용한 별도 임시 디렉터리 검사
9개가 통과했다. 정상 백업 순서 보존, 대기 marker의 백업 시작 및 구 컨테이너
재시작 차단, 기존 백업 복구 marker 보존, 심볼릭 링크 거부, 잠금 경합, 원본
SHA 불일치 거부 및 새 프로세스의 복구 진입을 포함한다. 새 프로세스 실행은
실제 Linux systemd 부팅·Docker 자동 재시작 시험이 아니다. 생성한 overlay의
SHA-256은 `d5a8f2b2e5ce6f4b0524429300186eed8068ecaf35535f1b8c30e41df36b7ba8`다.
실제 운영 소스의 0600 임시 사본은 실험이 끝난 뒤 소유권·해시를 확인해 삭제했다.
테스트는 `ASB_LEGACY_BACKUP_SOURCE`로 SHA가 일치하는 별도 비공개 사본이 제공되지
않으면 건너뛰므로, 보통의 테스트 실행만으로 이 9개가 재실행됐다고 판단하지 않는다.

실제 설치를 검토할 때는 현재 운영 파일의 소유권·SHA를 다시 확인하고, 백업과
복구 프로세스를 공유 `backup.lock`으로 차단한 상태에서 기존 파일을 보존하며
루트 소유 파일의 원자적 교체·디렉터리 fsync와 서비스의 import 경로를 검증해야
한다. lock 획득 이전에 구 모듈을 읽은 프로세스와 systemd가 부팅 중 구 파일을
읽는 경우도 격리 테스트가 필요하다. 독립적인 privacy recovery의 구 컨테이너
재시작, Docker `unless-stopped`, 요청 배수 및 provider quarantine 부팅 순서는
이 패치가 해결하지 않는다. 따라서 이 문서는 운영 변경·키 교체 또는 503 해결
증거가 아니다.
