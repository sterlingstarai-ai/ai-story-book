# 임시 SSH 접근 보호 — 격리 구현

후속 관측: 별도로 구성한 일회성 인스턴스 전용 CAS 경로로 실제 읽기 전용 IAP/SSH 접속에 성공하고, 소유 임시 SSH 행을 삭제·재조회했다. 아래 설명은 이 파일의 격리 모듈 및 REST 어댑터 자체에 관한 것이며, 실제 접속의 절차와 미확정 장애 한계는 [별도 기록](IAP_SSH_ACCESS_2026-11-03.md)을 따른다.

**이 문서의 격리 부품은 운영 쓰기와 SSH 접근을 차단한다.** 기존 `/tmp/asb-vm-provider-observation.py`는 `gcloud compute ssh`가 프로젝트 공통 메타데이터에 키를 추가할 수 있는데 정리는 인스턴스 메타데이터만 살피므로 사용하지 않는다. 종전 정리 결과는 인스턴스 범위 결과일 뿐 프로젝트 공통 키 제거의 증거가 아니다. 현재 프로젝트 공통 SSH 항목 하나는 만료 표시가 있으나 소유자를 확정하지 못해 그대로 보존한다.

`scripts/gcp_instance_ssh_guard.py`는 인스턴스 범위에서만 fingerprint 충돌을 재조회·재시도하고, 유효기간 5분 이내의 정확한 자기 행만 추가·제거하는 독립 로직이다. 제출 결과가 불명확하면 나중에 반영될 가능성을 배제할 수 없으므로 정리 확인으로 보고하지 않는다. GCE REST 어댑터 `scripts/gcp_instance_metadata_rest.py`는 인스턴스 읽기 경로와 합성 요청 상태 머신을 제공하지만, **명시적 opt-in을 켜도 메타데이터 쓰기는 하드 차단한다.** 토큰 생성이나 SSH 접속은 수행하지 않는다.

`scripts/gcp_ssh_recovery_journal.py`는 향후 복구를 위해 공개 SSH 행·대상·임의 식별자와 제출 전 `requestId`를 소유자 전용 파일에 기록하는 실험 부품이다. 파일과 디렉터리 fsync, 원자적 생성, 심볼릭 링크·권한 검사를 사용한다. 이 기록은 같은 OS 사용자에 의한 변경까지 방어하지 않으며, 운영 어댑터에 아직 연결되지 않았다. 제출을 시작하고 Operation ID를 저장하기 전 중단되면 결과는 미확정이다. Operation ID를 저장한 경우에도 현재 자동 정리는 허용하지 않는다.

Google은 `setMetadata`의 `requestId`로 중복 요청을 방지한다고 설명하며, Operation의 `clientOperationId`에는 그 값이 포함될 수 있다. 그러나 이 기록만으로 중복 요청의 응답이 원래 Operation을 반드시 반환하는지, 누락된 Operation을 언제나 찾아낼 수 있는지는 보장하지 않는다. 완료된 Operation은 최소 1시간 뒤 제거될 수 있다. 따라서 **빈 조회 결과나 재시도만으로 이전 쓰기가 없었다고 판정하지 않는다.** [setMetadata requestId](https://docs.cloud.google.com/workflows/docs/reference/googleapis/compute/v1/instances/setMetadata), [Operation 목록](https://docs.cloud.google.com/compute/docs/reference/rest/v1/zoneOperations/list), [Operation 보존](https://docs.cloud.google.com/compute/docs/instances/viewing-compute-operations).

`scripts/gcp_ssh_host_pin.py`는 별도 신뢰 경로에서 이미 확인한 Ed25519 공개키 fingerprint를 비교해 strict `known_hosts` 한 줄을 만드는 부품이다. 원격 keyscan을 신뢰하거나 SSH를 실행하지 않는다. 실제 사용할 때는 별도 신뢰 경로의 호스트 신원, SSH 클라이언트의 `StrictHostKeyChecking=yes`, 정확한 고정 known_hosts 파일, 인스턴스 수명 식별자와 접속 경로를 함께 검증해야 한다.

네트워크를 사용하지 않는 unittest 29개와 Ruff가 통과했다. 실제 GCP 동작, 비정상 종료 시 원격 Operation 복구, 컴퓨터 재부팅 후 내구성, SSH 클라이언트 연결이나 운영 readiness는 이 시험에 포함되지 않는다. 실사용 전에는 운영과 격리된 환경에서 권한·호스트·경합·전원 중단·불확실 요청 및 정리 복구를 재검증해야 한다.
