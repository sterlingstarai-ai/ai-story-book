# 운영 가드 설치기 검증 및 인계 — 2026-11-03

고정 bundle은 `/private/tmp/asb-guard-installer-kkccdmah`, manifest SHA-256은 `2b7b105bfbf2a59f85a55d4b7e837ad4a0164511d71d29d2fc9de7b96a76fbfa`다. 파일별 SHA-256:

- `provider_activate_production.py`: `01ffbc255e93505258d23abe37eb10e54825dfd2a38f55756e5555144f547f34`
- `provider_activate_guard.py`: `9d364260b72bc4ee3f91cd75e8276c73a9cc7e842561a82378899bb9d16a384f`
- `provider_activate_systemd.py`: `ac219fff53c7484e86f0184d4ec77c7cb9394fe1f2fb57c50a3b8c5406fff188`
- `provider_install_stage.py`: `d92dd512d99cb961209176ef4402f1d43c4a747ff1a8bf2d0e2631386d41fb8a`

운영에 이미 불활성 staging된 release는 `/opt/ai-story-book/provider-releases/provider-release-8772f79b26f945a799c343d5a916d712`이며 READY SHA는 `fa65511e18d7f4b66f74a581e324b53a068c7a47faaa8b86154254aa366aec7d`다. 설치기는 READY와 v4 guard manifest, 16개 runtime manifest 및 모든 파일 내용을 재검증한다. 원격 설치기 4개는 기존 파일을 덮지 않는 별도의 root 0700 경로에 전달하고 파일별 hash를 대조해야 한다. Python의 `PYTHONPATH`는 그 별도 설치기 경로와 위 release의 `cutover` 경로를 포함한다.

읽기 전용 `--preflight`는 `--staging-release`와 `--ready-sha256`을 명시하여 GCE 인스턴스, 현재 release symlink, 기존 원본 hash, 기존 공유 lock, systemd 257 우선순위·unit·timer·대기 job 및 다른 복구 표식 부재를 확인한다. preflight 이후 실행을 별도로 수행할 때도 같은 입력으로 모두 재검사한다. 실행은 기존 enable 링크를 보존하고 marker와 원본 snapshot을 먼저 남긴 뒤 backup timer를 중지하고 system.control에 소유한 네 mask를 기록한다. mask 로드·inactive·대기 job 부재를 확인하기 전에는 원본 가드를 교체하지 않는다. 새 가드 검증 후 소유 mask만 제거하고 systemd·timer 상태를 복원한다.

중간 실패 후 `activation.json`이 남고 `systemd-op.json`이 없을 때에만 동일 고정 설치기의 `--recover`로 원본 복원 또는 이미 검증된 새 설치 완료를 시도한다. `systemd-op.json`이 남으면 systemctl 작업이 뒤늦게 완료될 수 있어 자동 reload·unmask·복원을 하지 않는다. mask symlink의 소유 inode 기록이 없거나 일치하지 않아도 자동 삭제하지 않는다. 이 상태는 원격에서 읽기 전용으로 원인과 실제 unit/job을 조사해야 한다.

고정 bytes를 사용한 Linux root 격리 파일시스템 시험 15건에서 정상 경로, 7개 파일의 각 중단 경계, SIGKILL, mask 부분 생성/제거, 원본 보존 및 읽기 전용 preflight를 확인했다. 이 15건의 systemd는 대역이다. 별도의 Debian 13 systemd 257 실제 PID 1 컨테이너 시험에서는 네 mask의 daemon-reload·start 거부·컨테이너 재시작 후 유지·정확한 링크 제거와 enable 복원을 확인했다. 두 시험은 실제 GCE VM 전체 설치/재부팅 증거가 아니다. 공개 API 또는 worker의 교체, 실제 제공자 생성, 운영 복원 역시 이 설치기의 성공과 별개다.
