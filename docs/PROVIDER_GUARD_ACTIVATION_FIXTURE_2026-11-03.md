# 제공자 가드 설치·복원 격리 구현 — 2026-11-03

`scripts/provider_activate_guard.py`는 7개 가드의 예상 기존 파일 hash·권한·소유자와 새 파일 hash를 확인하고, 원본을 별도 snapshot에 보관한 뒤 내구성 있는 설치 marker를 기록한다. 각 파일을 같은 디렉터리의 임시 파일로 쓰고 fsync한 다음 교체한다. 일치하지 않는 외부 변경이나 기존 recovery/mutation 표식이 있으면 진행하지 않는다. 정상 설치 검증 뒤에도 이전 snapshot과 `new-verified` 기록을 보존한다.

중간 실패에서는 모든 대상과 snapshot을 먼저 대조한 뒤에만 원래 내용·권한과 원래 없던 파일 상태를 복원한다. daemon reload 또는 복원 검증이 실패하면 marker를 보존한다. 새 키 전환 관련 표식이 없는 합성 상태에서는 정상 설치 후 원본을 복원하는 경로도 구현했다. 기록은 임시 파일 fsync와 원자적 rename으로 게시하며, 같은 트랜잭션의 확인 가능한 미완료 임시 파일만 재사용한다.

18개 합성 검사가 7개 파일 각각의 중단 지점과 실제 자식 프로세스 SIGKILL, 새 파일 hardlink 직후, 복원 임시 파일 작성 직후, 완료 기록 직후, 잘린 완료 기록 재개, marker 게시 전 중단 후 정확한 snapshot 재사용, 외부 수정 및 다른 mutation 표식 차단을 확인했다. 별도 systemd helper의 4개 대역 검사는 reload 실패, 새 가드 검증 및 기존 unit 속성 대조를 확인했다. Linux ACL/확장속성을 보존하지 못하는 경우를 피하기 위해 Linux에서 해당 속성이 있거나 검사할 수 없으면 차단한다. 이 Mac의 Python은 속성 조회 API가 없어 여기서의 검사는 합성 증거다.

**운영 설치는 아직 실행하거나 준비 완료로 판정하지 않았다.** 현재 엔진은 합성 private 디렉터리 구조와 합성 lock을 사용한다. 실제 `/opt`와 `/etc/systemd`의 별도 경로, 기존 7개 파일의 정확한 존재 여부·hash·권한, 운영 backup/install lock, 실제 recovery 표식 위치, 원본 unit baseline, enable/daemon-reload 및 실패 복원, 재부팅 중 부분 설치 상태는 운영 환경에 연결해 검증해야 한다. systemd helper의 실제 실행 경로도 설치 엔진과 아직 연결하지 않았다. 다른 비협조 privileged writer에 대한 배제 역시 자동 증명하지 않는다. 불완전하거나 일치하지 않는 기존 snapshot은 삭제하지 않고 차단한다.

설치 단계가 끝나기 전 새 키 전환이 일어나지 않도록 candidate staging과 key receiver, production entry/adapter에 `/var/lib/ai-story-book/provider-install/activation.json` 차단을 추가했다. 이 역시 해당 코드가 운영에 배포돼 작동했다는 뜻은 아니다. 설치 중 장애는 검증된 새 키 전환 이후의 복원과 구분해야 한다.
