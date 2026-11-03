# 제공자 키 전환 Docker 어댑터 — 격리 시험

`scripts/provider_cutover_docker_runtime.py`는 고정된 컨테이너 ID·이미지·전후 이름과
소유 label이 일치하는 **시험용 컨테이너만** 다룬다. 기본 네트워크는 `none`이며,
선택적으로 정확한 네트워크 ID·소유 label·`Internal=true`와 단일 attachment를
검증한 내부 전용 fixture 네트워크를 사용할 수 있다. 현재
실제 운영 VM의 컨테이너에는 사용할 수 없다. ingress, worker 배수, 제공자 호출,
systemd 부팅 및 daemon 전체의 작업 추적은 이 어댑터 범위가 아니다.

각 변경 명령 전후에 Docker daemon에서 상태를 재조회한다. stop·rename·start는
재시작 정책 `no`를 요구하며 rename·start는 중지 상태, 재시작 정책 활성화는
실행 중인 상태를 요구한다. Docker 명령의 실패·timeout 또는 후속 조회 불일치는
daemon의 작업 결과가 미확정일 수 있으므로 sticky 오류로 남는다. 이후 격리용
`stop`과 재시작 비활성화는 시도할 수 있으나 start·rename·재시작 활성화나
미해결 작업이 없다는 판정을 허용하지 않는다. 프로세스가 재시작하면 이 메모리
상태는 보존되지 않으며, 별도 durable marker와 실제 daemon 작업에 대한 독립적
확인이 반드시 필요하다.

단위 검사 12개가 ID·이름·이미지·소유 label 및 네트워크 오류, timeout·중단 후 상태가
정상처럼 보여도 미확정 유지, 격리 재시도와 상태 전제 등을 확인했다. 별도로
이미 로컬에 있던 Ubuntu 이미지를 사용해 고유 label의 `network=none` 컨테이너와
별도의 내부 전용 네트워크 컨테이너를 각각 두 개씩 생성하고 start·stop·rename·
재시작 정책 및 소유하지 않은 ID 거부를 시험했다. 소유 컨테이너와 네트워크만
삭제하고 daemon 재조회로 부재를 확인했다. Docker는 생성 직후 네트워크 ID가 빈
값일 수 있어 `created` 상태에서만 이를 허용하고, start 이후 정확한 ID를 확인한다.
이는 실제 systemd 부팅, provider 응답, 전체 전환 또는 운영 안전성의 증거가
아니다. 실제 daemon 사용 예시는 `scripts/run_provider_cutover_docker_fixture.py`,
대역 검사는 `scripts/tests/test_provider_cutover_docker_runtime.py`를 따른다.
