# 제공자 복구 가드 부팅 시험 — 2026-11-03

소유한 일회용 GCP `e2-small` VM 한 대와 10GB 표준 부팅 디스크에서 실제 systemd와 Docker를 사용했다. VM ID는 `1625274709400892680`, 디스크 ID는 `4256751826780828936`이다. 시험 컨테이너 네 개는 합성 `busybox`, 네트워크 없음, restart `no`이며 실제 데이터·제공자 키를 사용하지 않았다. 이 VM은 시험 후 삭제됐고, 성공한 API 조회로 VM과 디스크 모두 부재를 확인했다. 실행기는 중복 실행 방지용 소유 journal을 남긴다. 정확한 청구액은 이 시험에서 확인하지 않았다.

시험은 v2 패키지의 실제 legacy backup overlay, 실제 legacy privacy recovery 원본과 interlock, quarantine unit 및 recovery unit 순서를 사용했다. provider recovery 표식이 없을 때 두 복구 경로가 실행됨을 먼저 확인했다. 이후 합성 컨테이너를 구 세대에서 새 세대로 이름을 전환하고 새 API를 실행한 상태에서 표식을 보존한 채 재부팅했다. 부팅 후 quarantine unit 실행 성공, 컨테이너 네 개 모두 정지 및 restart `no`, 표식 보존, 백업·privacy 복구 경로의 거부를 확인했다. 결과는 `BOOT_QUARANTINE_VERIFIED_ON_FIXTURE`다.

이것은 guard 및 unit의 한 가지 합성 중단 시나리오에서의 실제 부팅 시험이다. 운영 이미지·실제 입구와 worker 대기·제공자 호출·고객 데이터·전체 전환을 검증하지 않았고, Docker daemon에 이미 전달되어 완료 시점이 불확정인 요청이 더 늦게 처리되지 않는다는 증거도 아니다. 기존 운영 VM에는 어떠한 가드도 설치하지 않았다.

시험 뒤 daemon 작업의 미확정 상태를 보존하기 위해 `docker-mutation.json` 차단을 privacy interlock, quarantine 및 legacy backup overlay에 추가했다. 해당 최신 v3 패키지는 단위 시험만 수행했으며 이 VM 부팅 시험의 대상이 아니다. daemon 작업 처리의 완전성, 최신 가드 설치와 부팅, 실제 서비스 배수·키 전환·readiness 검증은 별도 미완료다. 지시대로 시험 VM을 추가로 만들지 않았다.

그 후 로컬 후보 staging과 quarantine `arm`에서도 같은 미확정 표식을 거부하도록 추가했다. 이 변경은 이미 생성한 v3 패키지에도 들어 있지 않으므로 v3는 최종 패키지가 아니다. 최종 소스·의존성 freeze 이후 새 패키지를 생성하고 검증해야 한다.

최신 v4 guard에 대한 별도 일회용 mutation 부팅 재시험을 1회 실행했다. VM ID `5516140755997175831`, 디스크 ID `171712378906619927`이며, 두 자원은 실행 후 삭제됐고 성공한 조회로 부재를 각각 확인했다. 전체 결과는 `FIXTURE_FAILED`다. 부팅 로그에서는 quarantine, backup recovery, privacy recovery가 모두 marker가 있는 상태에서 실패한 것으로 관측됐지만, fixture는 전체 확인에 실패했으므로 최신 부팅 시험을 통과로 처리하지 않는다.

실패 원인을 조사한 결과 실행 당시 시스템 로그에서 startup 스크립트 완료가 quarantine unit 종료보다 약 0.55초 빨랐다. 두 서비스 사이 순서 보장이 없어 검증이 unit 종료 전에 수행될 수 있다는 fixture 경합을 확인했다. 당시 fixture가 구체적인 실패 이유를 기록하지 않아 이 경합이 실제 단일 원인인지는 확인하지 못했다. 로컬에서 해당 경합을 재현해 검증 전에 unit 실행 및 종료를 기다리도록 수정했으며, 후속 실패에는 허용된 비민감 진단 문구만 남기도록 개선했다. 추가 실기기 부팅 재시험 없이는 v4 통과를 주장하지 않는다.

수정된 fixture로 최종 v4 가드의 mutation 표식 부팅을 한 번 더 검증했다. 앞선 두 VM과 디스크가 모두 삭제된 사실 및 가드 7개 해시가 바뀌지 않은 사실을 먼저 확인했다. 마지막 VM ID `4143396271060954797`, 부팅 디스크 ID `746725624152075949`는 종료 후 삭제됐고 각 API 재조회에서 부재가 확인됐다. 결과는 `BOOT_MUTATION_QUARANTINE_VERIFIED_ON_FIXTURE`다. 이 시나리오에서 표식이 보존되는 동안 quarantine unit이 의도대로 실패 상태를 유지하고 네 합성 컨테이너가 정지·restart `no`로 남았으며, backup/privacy recovery도 거부됐다. 앞선 실패 기록은 삭제하거나 통과로 바꾸지 않는다.

최종 가드 정본 해시는 `/private/tmp/asb-provider-boot-package-20261103-v4/manifest.json`에 기록됐다. 실행 시점에는 고정된 7개 파일과 hash-pinned 실제 legacy privacy recovery 코드를 사용했다. 이 결과는 일회용 VM의 특정 mutation 표식 부팅에 대한 증거이며, 운영 서버에 가드가 설치되었다는 뜻이 아니다. 진행 중이던 Docker daemon 요청의 완전 종료, 실제 트래픽·작업 배수, provider 인증과 readiness, 운영 복원 및 실제 동화 품질은 계속 별도 검증이 필요하다. 세 번의 일회용 VM 비용은 실제 청구서에서 따로 확인해야 한다.
