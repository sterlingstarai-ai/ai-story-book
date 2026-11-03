# API readiness 외부 알림 — 2026-11-03

운영의 제공자 관측은 86,400초 동안 새 성공 관측이 없으면 만료돼 `/health/ready`가 503을 반환할 수 있다. 이 후보는 5분마다 VM 내부 loopback의 해당 엔드포인트만 읽고 별도 이진 Cloud Monitoring 시계열을 기록한다. 성공 응답과 provider 관측이 모두 healthy이면 1, 503·unverified·응답 오류·연결 실패면 0이다. 실제 AI 호출이나 제공자 관측 조작은 하지 않고 사용자 데이터와 응답 본문을 출력하지 않는다.

기존 백업·개인정보 파기 신호와 독립된 이름 및 정책을 사용한다. 정책 후보의 10분 `ALIGN_MAX`와 5분 지속 조건은 짧은 백업 중단의 오경보를 줄이는 대신 지속 오류 감지를 늦출 수 있다. 신호 부재 조건은 25분이다. Cloud Monitoring의 실제 평가·지연은 설치 후 시험해야 하며 VM뿐 아니라 메트릭 전송 중단도 장애 신호가 될 수 있다. 신호가 최초에 기록되지 않으면 부재 경보가 보장되지 않으므로 첫 시계열 확인이 필요하다.

운영 VM 서비스 계정의 확인된 권한은 `monitoring.timeSeries.create` 하나다. 새 descriptor 생성과 alert policy 추가는 관리자 권한으로 별도 수행하고, 이미 사용자가 지정한 기존 이메일 채널만 사용한다. 기존 역할을 넓히거나 백업 경보를 변경하지 않는다. 수신 채널이 enabled인 것은 확인됐으나 현재 API 응답의 verificationStatus는 생략돼 있다. 과거 시험 이메일 수신은 현 정책의 향후 전송 성공 보증이 아니다.

Cloud Monitoring custom metric은 결제 계정 전체의 공유 무료 구간을 초과하면 과금될 수 있다. [Google Cloud Observability 가격](https://cloud.google.com/products/observability/pricing)에 따르면 비 Prometheus 측정 데이터는 계정당 첫 150 MiB/월 무료 구간이 있고 Monitoring 쓰기 API 호출은 무료다. 현재 계정의 전체 사용량과 최종 청구액은 별도 확인해야 한다. 이 기록은 무료 운영이나 실제 이메일 수신을 보장하지 않는다.

`publish_readiness_health.py --check`는 로컬 readiness만 조회하며 메트릭을 전송하지 않는다.

## 운영 설치 및 확인

2026-11-03에 v2 후보 manifest SHA-256 `10a22d830d5dc3d58791277eac515dccdfd5a7aa710f55cbf2a0f471c33d4cea`와 파일 5개를 검증한 후 다음 독립 리소스를 설치했다.

- script: `/opt/ai-story-book/readiness-monitor/publish_readiness_health.py`, SHA-256 `6d3e541d3aeaadbe37717cbd2c597da25ecfc1dafc1093e9715641ea0cc9a945`, root:root 0600.
- systemd: `/etc/systemd/system/asb-readiness-signal.service` 및 `asb-readiness-signal.timer`; timer는 enabled·active·waiting, 첫 수동 signal 서비스는 Result success.
- metric descriptor: `projects/gen-lang-client-0308507618/metricDescriptors/custom.googleapis.com/ai_story_book/api_readiness`, GAUGE/INT64. Cloud Monitoring에서 실제 정상 값 `1`의 시각 `2026-11-03T10:59:51Z`를 확인했다.
- alert policy: `projects/gen-lang-client-0308507618/alertPolicies/8576712623432685072`, enabled. 기존 email channel `projects/gen-lang-client-0308507618/notificationChannels/3409107688534938226` 하나를 연결했다. 기존 정책·채널은 생성 전후 내용이 같았다.

설치 후 로컬 `--check`는 READY, API·worker·nginx는 실행 중이고 기존 backup/watch/signal timer는 모두 active였다. Mac 외부에서 인증서 검증을 유지한 HTTPS `/health/ready`도 HTTP 200이었다. 이 외부 요청은 설치 확인일 뿐 지속적인 외부 HTTPS 감시가 아니다.

첫 파일 설치 시 이번 작업의 staging 중간 디렉터리가 예상과 다른 0755여서 쓰기 전에 중단됐다. 대상이 모두 부재함을 확인하고 소유 staging 디렉터리만 0700으로 조정한 뒤 별도 기록을 남겨 설치했다. metric·unit·정책 생성 기록은 비밀을 포함하지 않는 소유 전용 로컬 운영 저널에 보존했다.

threshold 조건은 최근 10분의 최대값이 계속 0인 상태가 5분 지속돼야 충족되므로, 새 장애의 감지는 대략 15분 이상 걸릴 수 있고 수집·평가 지연이 추가될 수 있다. 신호 부재 조건은 25분이다. 장애 신호를 의도적으로 만들거나 이 신규 정책의 실제 평가·복구 및 이메일 전달을 시험하지 않았으므로, 해당 전달 성공은 아직 미검증이다. 알림 정책 비용은 공식 요금표에 2027-09-01부터 metric reference 과금이 예정돼 있으므로 향후 요금과 계정 전체 사용량을 재확인한다.

## 설치와 부분 실패 처리

설치 전 별도 root 전용 staging 사본의 manifest와 다섯 파일 해시, 파일 소유권·권한 및 심볼릭 링크 부재를 확인한다. 정확한 대상 VM·프로젝트를 재확인하고, `/opt/ai-story-book/readiness-monitor`, `asb-readiness-signal.service`, `asb-readiness-signal.timer`의 파일과 로드된 systemd unit이 모두 없는지 확인한다. 동일 이름이 이미 있거나 소유권이 불분명하면 덮어쓰지 않는다. 관리자 계정의 descriptor·policy 생성 권한, VM의 시계열 쓰기 IAM 권한과 OAuth scope, 기존 활성 이메일 채널의 정확한 대상, 같은 metric/정책의 기존 존재 여부도 읽기 전용으로 확인한다. 기존 항목이 있으면 생성하거나 변경하기 전에 소유권과 정확한 구성을 대조한다.

관리자 권한으로 별도 metric descriptor만 생성하고 VM 역할은 변경하지 않는다. 정확한 파일만 별도 경로와 두 새 unit에 충돌을 거부하는 방식으로 설치하고 systemd 구문 및 로드 상태를 검증한다. 첫 signal을 한 번 게시해 해당 metric의 정확한 값을 확인하고 timer를 켠 뒤, 확인된 기존 이메일 채널을 연결한 별도 정책을 생성한다. 실패 또는 결과가 불명확하면 자동 반복하거나 이미 있던 정책을 지우지 않는다. 설치된 경로·파일 해시, descriptor와 policy의 정확한 리소스 이름, 실행한 단계와 확인 결과를 비밀 없이 기록한다. 외부 알림의 실제 발생·복구 및 이메일 전달은 별도의 통제된 시험으로 확인한다.

부분 설치 시에는 새 timer/service 및 파일이 이번 설치의 정확한 소유물이며 해시가 일치한다는 것을 먼저 확인한다. 정책이 생성됐으면 부재 경보를 고려해 정확한 정책 상태부터 확인한 다음 해당 새 timer만 중지한다. 기존 백업·개인정보 파기 unit, 정책, 이메일 채널 및 계정 데이터는 변경하지 않는다. 시계열 쓰기나 정책 생성의 응답이 불명확하면 Cloud에서 정확한 리소스 상태를 재조회하며, 소유를 확정하지 못한 파일이나 리소스는 보존하고 수동 확인한다.
