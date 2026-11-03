# 제공자 후보 파일과 격리 probe — 2026-11-03

후보 생성 Docker 명령은 고정된 로컬 `/var/run/docker.sock`을 사용하고 `DOCKER_*` 환경변수를 제거한다. 시작 전 config와 key 파일의 inode, 메타데이터와 내용을 확인해 증거를 메모리에만 보관하고, 후보 프로세스가 시작되면 Linux 호스트의 `/proc/<pid>/root`에서 실제 bind 파일을 비교한다. 컨테이너 프로세스 재시작이나 파일 변경이 있으면 검증을 거부한다. 키 또는 그 해시는 로그나 결과에 출력하지 않는다. 검증 이후 파일 수정을 배제하는 운영 권한 및 단일 writer 보장은 별도 조건이다.

실제 Linux Docker와 host PID namespace를 사용한 소유 fixture에서 후보 bind 검증, 합성 정상 전환과 SIGKILL 복구, 소유 자원 정리가 통과했다. 운영 서버의 `/proc` 권한이나 실제 배포된 후보가 통과했다는 증거는 아니다.

서버나 호스트 포트가 없는 probe 후보는 정지 상태로 만들고, 원래 API 후보와 이미지·환경·네트워크·bind 및 보안 설정을 대조한다. `PortBindings`와 `PublishAllPorts`를 모두 검사한다. probe 생성과 삭제의 daemon 미결은 `docker-mutation.json`을 유지하며, 생성 ID는 journal 해제 전에 별도 `probe-owner.json`에 fsync한다. 검증된 소유 ID와 완료된 삭제만 소유 기록을 해제할 수 있다. probe의 start부터 provider 실행·stop·remove까지 동일 mutation journal로 보호하는 production orchestrator 연결과 Linux probe 통합 시험은 별도 진행 중이다.

합성 단위 검사는 현재 17건 통과했다. candidate-create journal이 활성인 동안 정확한 transaction과 old API ID만 허용하고, 이후 `candidate-owner.json`은 네 container ID가 정확히 일치하는 경우만 허용한다. owner 기록을 journal 해제 전에 fsync하는 실제 실행 진입점 연결은 별도 진행 중이다. 이 결과는 실제 AI 제공자, API readiness, 외부 접근 차단, 운영 배포 또는 운영상 무중단을 의미하지 않는다.

별도의 portless probe를 포함한 실제 Linux Docker 합성 통합 시험에서 정상 전환, SIGKILL 후 격리, 실행 중 bind inode 확인, 소유 자원 정리가 통과했다. 첫 실행에서 probe의 Python PID 1이 SIGTERM을 무시하는 문제가 발견돼 명시적 SIGTERM handler를 추가한 뒤 다시 시험했다. 이 fixture의 provider, ingress, queue는 대역이며, 이후 추가한 candidate-owner 연결을 포함하는 재시험은 별도다.

candidate-create journal과 네 ID candidate-owner를 포함한 최신 코드도 Linux Docker에서 정상 전환 및 SIGKILL 격리, 실행 중 bind inode 검증을 다시 통과했다. 실행 토큰 `64ddf17001cf42b4ac685ed936b2456e`의 소유 컨테이너, 네트워크, 볼륨, 시험 이미지가 모두 삭제된 것을 별도 조회로 확인했다. provider·nginx·queue는 여전히 대역이며 운영 서버 시험은 아니다.

후속 검토에서 운영 상태를 바꿀 수 있는 `WorkingDir`, `User`, `StopSignal`, `StopTimeout`, `Healthcheck` 등 config도 기존·신규 후보 사이에 비교하고, 설치 미완료 marker를 차단하도록 보완했다. 이 후속 버전은 단위 검사 18건을 통과했으며, 위 Linux 통합 검증 이후의 변경이므로 실제 Linux Docker 재검증은 별도다.
