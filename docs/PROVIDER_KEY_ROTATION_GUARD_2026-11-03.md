# 제공자 키 교체의 복구 격리 후보

이 코드는 **운영 키 전환 명령이 아니다.** 운영 경로의 marker 생성은 코드에서 명시적으로 차단된다. 실제 VM에 설치·활성화·실행하지 않았고, 기존 운영 구성과 노출된 키는 건드리지 않았다.

- `provider_rotation_quarantine.py`는 지정된 기존·후보 API/worker의 이미지가 각각 동일하고 네 컨테이너의 자동 재시작이 모두 `no`인 경우에만 테스트 경로의 marker를 영속화한다. 백업의 동일한 잠금을 잡고 다른 복구 marker를 먼저 확인한다.
- marker가 있다면 확인된 네 컨테이너를 중지하고 자동 재시작을 끈다. 다른 컨테이너는 건드리지 않고 marker는 보존한다. 키·환경은 읽거나 변경하지 않고, 옛 컨테이너나 새 컨테이너를 시작하지 않는다.
- 백업 복구와 이전 개인정보 배포 롤백이 사용하는 공통 guard, 낭독 배포 arm 및 systemd ExecCondition이 provider rotation marker도 확인하도록 보완했다. 심볼릭 링크나 손상 marker도 차단한다.
- `asb-provider-rotation-quarantine.service`는 설치되지 않은 유닛 후보이며, 다른 복구 유닛보다 먼저 격리하도록 기술한다. 이 텍스트나 ExecCondition 자체는 공유 잠금이나 실제 부팅 순서를 증명하지 않는다.
- [소유한 격리 Docker 시험](../scripts/run_provider_rotation_quarantine_fixture.py)은 단일 로컬 이미지와 network=none 컨테이너 네 개를 사용해 marker 기록 직후·옛 컨테이너 중지 후·후보 시작 후 프로세스 강제 종료와 재호출 시 격리를 검증한다. 실제 systemd 부팅, 프록시 요청 배수, 키 전달·실제 교체·제공자 응답 및 운영 DB 일관성은 시험하지 않았다.

운영 적용 전에는 기존 유닛과 guard가 실제 호스트에 안전하게 배포됐는지, Docker daemon의 자동 재시작이 systemd보다 앞설 수 있는 조건에서 네 컨테이너가 모두 `restart=no`인지, ingress와 worker가 완전히 비워졌는지, 다른 관리 경로/백업 복구가 공유 잠금과 marker를 지키는지를 독립적으로 검증해야 한다. 재부팅·단절·실패 주입 시험과 검증된 새 자격으로의 전환/검사/복구 경로가 완성되기 전까지 production arm 차단을 제거하지 않는다. 이전에 노출된 키를 롤백에 사용하지 않는다.
