# 무료 운영 후보 — 2026-11-02

> 현재 상태: Google VM에서 비공개 API·worker 시험이 실행 중이다. Neon Free 화면의 2026-11-02 확인값은 0.25 CU-hours 및 저장 용량 32.96 MB였다. 이 수치는 시점별로 변하며 무료 잔여량이나 장시간 운영을 보증하지 않는다. 현재 운영 조건과 미완료 항목은 [Google 시험 운영 기록](GOOGLE_PILOT_OPERATIONS_2026-11-02.md)을 우선한다. 아래는 시간순 시험 이력이다.

## 후속: Oracle 가입 실패와 Google 대안

사용자는 Oracle 가입 마지막 단계에서 일반 계정 생성 오류를 반복해 확인했다. 화면만으로 구체 원인은 확인되지 않았고 가입 성공으로 취급하지 않는다. 사용자는 Google 대안을 지시했다. Chrome에서 기존 `AI Story Book Beta` 프로젝트와 연결된 유료 Google 결제 계정을 확인했다. 결제 화면의 당월 표시액은 0원이지만 보고 지연이 가능하며, 예치금이나 청구 상한을 의미하지 않는다. 사용자가 Compute Engine API를 활성화하고 시험용 VM을 생성했다. VM은 실행 중이나 운영 API와 worker는 아직 실행되지 않는다.

Google 콘솔에서 준비한 시험용 VM 설정: Iowa `us-central1-c`의 e2-micro, Debian 13 x86, 10GB 표준 영구 디스크, Standard 네트워크, 임시 외부 IPv4, 서비스 계정 없음. 공개 HTTP/HTTPS 방화벽 규칙과 자동 스냅샷은 사용하지 않는다. 스냅샷을 끈 설정은 합성 데이터 시험용이며 운영 백업 대책이 아니다. 콘솔에서 `asb-free-test` 실행 상태를 확인했으며 운영 서비스 연결과 실제 부하는 아직 검증하지 않았다.

CLI 재조회에서 서비스 계정 0개, Standard 네트워크 및 자동 재시작을 확인했다. 기본 VPC에는 인터넷 전체에 SSH 22와 RDP 3389를 허용하는 기본 규칙이 있으나, 호스트 관측 시 SSH 22 외 RDP 수신 프로세스는 없었다. SSH는 공개키 인증이 켜져 있고 root 로그인·암호 인증은 꺼져 있었다. 인터넷에 공개되는 운영 HTTPS 진입점과 별도의 최소 권한 접근 통제는 아직 검증하지 않았다. 부팅 디스크는 VM 삭제 시 자동 삭제 설정이므로 백업으로 간주할 수 없다.

Google 공식 IPv4 요금표는 외부 임시 IPv4를 시간당 $0.005, 결제 계정당 첫 1시간만 무료로 표시한다. 730시간 가동 시 다른 사용이 없고 무료 1시간이 남아 있다는 가정에서 약 $3.645/월이며 세금·전송·AI 사용료는 별도다. VM 연산과 표준 디스크의 무료 한도는 같은 결제 계정의 다른 프로젝트와 공유한다. 무료 한도 잔여량이나 실제 청구액은 확인되지 않았으며 UI의 가격 추정과 실제 무료 할인은 다를 수 있다. [Google 네트워크 요금](https://cloud.google.com/vpc/network-pricing), [무료 등급 조건](https://docs.cloud.google.com/free/docs/free-cloud-features)

2026-11-02 후속 연결 준비: Neon 콘솔에서 전용 `storybook-private` 버킷이 Private임을 재확인했다. Mac FileVault가 켜져 있고 서버와 일치하는 PostgreSQL 16 `pg_dump`·`pg_restore`·`psql`이 설치되어 있다. 이는 최초 백업을 암호화된 로컬 디스크에 기록할 수 있다는 뜻이지, 독립 원격 백업·자동 실행·실제 복원 완료가 아니다. 공개 HTTPS용 기존 도메인 소유권은 아직 확인되지 않았다. Let's Encrypt는 공개 IP용 6일 인증서를 제공하지만 IP 고정, 자동 갱신과 실기기 검증이 필요한 대안일 뿐 적용·검증된 것은 아니다. [IP 인증서](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)

후속 시험: 기존 외부 IPv4를 Standard 고정 IP로 전환하고 Let's Encrypt 단기 IP 인증서를 발급해 적용했다. 443 방화벽은 시험 당시 이 Mac의 공인 IP 한 곳으로 제한했다. Mac에서 인증서 검증을 끄지 않고 HTTPS `/health/ready` 200, HTTP→HTTPS 301, `/health/detailed` 403을 확인했다. 인증서는 2026-11-08 만료이며 갱신 dry-run 및 수동 서비스 실행을 통과했고 하루 두 번 검사하는 systemd timer가 활성화됐다. 실제 향후 자동 갱신과 만료 알림은 아직 확인되지 않았다. 고정 IP는 VM을 멈춰도 예약되어 비용이 계속 발생할 수 있고, 현재 범위 제한은 일반 사용자 공개 서비스가 아니다.

초기 빈 Neon 백업 및 이후 가상 동화·그림 5개를 포함한 백업을 Mac의 FileVault 디스크와 Google Cloud Storage의 전용 비공개 US-CENTRAL1 Standard 버킷에 보관했다. 후자는 공개 접근 차단·uniform IAM이 켜져 있고 익명 요청이 403이었다. 두 번째 백업을 격리 PostgreSQL 16·MinIO에서 복원해 33개 테이블과 오브젝트 5개의 해시·메타데이터·접근 통제를 비교했고, 원격 사본도 다시 내려받아 파일별 일치를 확인했다. 시험용 합성 콘텐츠에 대한 수동 리허설이며 자동 백업, 실제 사용자 데이터 복원, 운영 RTO/RPO는 아니다. 버킷의 기본 soft-delete 보존은 7일이므로 삭제·동의 철회 기록과 백업 삭제 정책을 검증하기 전 실제 아동 데이터를 백업 대상으로 운영하지 않는다.

VM 기본 용량 시험: Docker를 설치하고, 별도로 만든 시험용 amd64 이미지에 현재 소스와 의존성을 넣어 mock/SQLite 설정으로 API, 단일 solo Celery worker, 비영속 시험용 Redis를 외부 공개 포트 없이 기동했다. API `/health/live` 응답과 Redis를 통한 Celery `inspect ping`이 성공했고 세 컨테이너의 OOM 종료 및 재시작은 없었다. 유휴 시 Docker 메모리 관측치는 API 129.1MiB, worker 65.52MiB, Redis 10.44MiB이고 시스템 `MemAvailable`은 약 269MB, swap은 0이다. 두 번째 관측에서는 약 251MB였다. 이는 최소 모의 유휴 시험이며 실제 DB·스토리지·이미지 생성·PDF·동시 요청·장시간 운영이나 `/health/ready` 검증이 아니다. 운영 이미지에는 이 시험에서 생략한 폰트 등 자산도 필요하다. 시험 컨테이너·네트워크 및 시험 코드는 정리하며 Docker 설치는 서버 준비를 위해 유지한다.

추가로 같은 VM에서 SQLite·비영속 Redis·임시 비공개 MinIO와 모의 AI/삽화검수로 API→Celery 동화 생성, 페이지 재생성, 읽기·소유권·동의 철회 여정을 두 번 실행하여 각각 34/34 검사가 통과했다. 첫 시도는 시험 구성에 일일 생성 예산이 없어 생성이 503으로 차단됐고, 시험 예산을 명시한 재시도부터 통과했다. 생성 중 한 차례 `MemAvailable` 약 130MB, 컨테이너 API 149.7MiB·worker 118.4MiB·MinIO 89.83MiB·Redis 8.883MiB였으며 관측된 OOM·재시작은 없었다. 합성 단일 사용자/모의 AI 및 임시 SQLite 결과이므로 실제 Neon·외부 AI 생성, 운영 저장소, 동시 사용자, 장시간 안정성이나 그림 품질의 증거가 아니다.

별도 임시 Redis에서 AOF `appendfsync everysec` 설정으로 합성 목록 항목을 기록하고 3초 후 프로세스를 강제 종료한 뒤 재시작해 같은 항목을 확인했다. 한 건의 강제 종료 지속성 검사이며 장애 직전 데이터의 무손실, Celery 메시지의 중복·재전달, 또는 운영 대기열의 복구를 증명하지 않는다.

더 나아가 Google VM 내부에 임시 PostgreSQL 15를 추가하고 mock AI·단일 solo worker·Redis·MinIO와 결합해 같은 합성 HTTP 여정을 연속 2회 각각 34/34 통과했다. 이어 두 합성 이용자의 여정을 동시에 실행해 둘 다 각각 34/34 통과했고, 1초 간격 표본의 최저 `MemAvailable`은 92,084KiB였다. 다섯 컨테이너에서 OOM 종료·재시작은 관측되지 않았다. worker 동시성은 1이므로 동시 요청이 동시에 AI 생성됐다는 뜻이 아니며, 최저 수치 역시 표본 사이의 순간 최솟값은 놓칠 수 있다. Neon·실제 AI·운영 보안 설정·장시간·다수 사용자 시험은 여전히 미완료다.

원본 API·worker Dockerfile을 allowlist로 추린 비밀 없는 소스와 폰트를 사용해 해당 x86 VM에서 각각 빌드했다. 운영 Compose의 기본 prefork 동시성 2로 합성 PostgreSQL·Redis·MinIO와 기동하자 책 생성 접수 뒤 HTTP 폴링이 30초 timeout이 났고 별도 관측 가용 메모리는 약 59MiB였다. VM SSH도 느려져 합성 데이터 전용 VM을 reset해 복구했다. 커널 OOM은 확인되지 않았으므로 정확한 원인을 메모리로 확정하지 않는다. 같은 이미지의 prefork 동시성 1에서는 단일 여정이 34/34 통과했다. 이는 운영 이미지 보안 스캔·실제 공급자 배포나 24시간 운영 증거가 아니며, 이 VM에 기본 동시성 2를 그대로 배포하지 않는다.

원본 이미지·prefork 1로 두 사용자를 시험한 첫 실행은 생성 자체는 완료됐지만 누적 합성 이용자 때문에 테스트의 ‘또래 5명 미만’ 가정이 깨져 두 실행 모두 32/34였다. DB를 새로 만든 재시험은 서버가 심하게 느려져 완료 전에 중단·재시작했다. 이후 임시 1GiB 디스크 스왑을 적용한 별도 재시험에서는 prefork 1과 2 모두 동시 두 여정이 각각 34/34 통과했다. prefork 1에서는 스왑 약 140MiB, prefork 2에서는 약 242MiB가 사용됐고, 후자에서는 합성 생성 작업 한 건의 Celery 실행 시간이 약 164초까지 걸렸다. 시간과 메모리는 관측 당시의 값이며 실제 부하·응답시간 보증이 아니다. 테스트 스왑, 생성 데이터, 컨테이너·임시 네트워크와 이미지 및 임시 SSH 키는 제거했고 VM과 Docker 설치는 유지했다. 스왑은 운영에서 민감정보와 보안·보존 정책을 검토하기 전 영구 설정하지 않는다.

시험 중 기존 고정 Quay MinIO 이미지는 이 Mac과 VM에서 익명 pull 시 401로 실패했다. 일회용 통합/복원 시험은 `infra/Dockerfile.minio-test`에서 공식 릴리스 바이너리를 SHA-256 검증해 로컬로 빌드하도록 변경했다. 이는 시험 전용이며 기존 로컬·운영 Compose의 해당 Quay 참조는 그대로여서 필요한 경우 별도 해결해야 한다.

무료 e2-micro는 미국 지정 리전에서 1GB RAM·0.25 공유 vCPU다. API·worker·Redis 동시 운영 가능 여부는 미측정이다. 2GB e2-small을 아이오와에서 730시간 계속 사용하면 공식 on-demand 시간당 $0.016752855 기준 약 $12.23이며 디스크·네트워크·세금·AI 비용은 별도다. 지역·과금 계정·환율에 따라 금액은 달라진다. [Google 가격](https://cloud.google.com/products/compute/pricing/general-purpose?hl=en)

Google의 일반 예산 알림은 자동 청구 상한이 아니다. Google의 서비스별 spend cap 목록에 Compute Engine은 포함되지 않으며 감지 지연 초과분도 청구될 수 있다. 실제 금액 제한·기존 다른 프로젝트 영향·API 과금은 별도로 검토한다. [예산 알림](https://docs.cloud.google.com/billing/docs/how-to/budgets), [spend cap 제한](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

2026-11-02 사용자가 월 1만 원 정도를 언급하고 작업을 위임한 뒤 프로젝트에 한정된 월 10,000 KRW 예산 알림을 생성하고 재조회했다. 실사용액 기준 50%·80%·100%에서 기본 결제 역할 수신자에게 알리는 설정이다. 생성 전 결제 계정의 기본 알림 대상 역할 구성원은 현재 사용자 한 명으로 확인했다. 이것은 프로젝트에 한정된 **알림**이며 사용을 자동 중단하거나 청구를 10,000원으로 제한하지 않는다. OpenAI 등 다른 공급자 비용과 같은 결제 계정의 다른 프로젝트 비용은 이 프로젝트 예산에 포함되지 않는다.

## 우선 후보

사용자 소유 Neon Free DB·private S3와 Oracle Cloud Always Free의 ARM VM을 조합해, API와 Celery worker 및 전용 영속 Redis를 VM에서 실행하는 방안을 먼저 검증한다. 이는 설계 후보이며 서비스 생성이나 운영 준비 완료를 뜻하지 않는다. 가입·지역·VM 가용성과 실제 부하, 지속성, 삭제/환불 복구, 외부 접근 보안 및 정책 검증을 통과해야 한다.

- Oracle 공식 문서의 현재 Always Free 기준은 ARM 합계 2 OCPU·12GB, 블록 스토리지 200GB다. VM은 홈 리전에만 만들 수 있고 리전·가용 영역의 용량 부족 및 유휴 인스턴스 회수 가능성이 있다. 서울 가용 여부는 계정에서 직접 확인한다. [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- Oracle은 개인당 무료 계정 하나만 허용하며 대부분의 가입자에게 카드·전화 확인이 필요하다. 사용자가 직접 약관과 카드 인증을 완료해야 하고 유료 업그레이드는 별도 결정이다. [Oracle Free Tier](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm)
- Neon의 2026-10-02 공개 안내는 프로젝트당 DB 1GB, 월 100 CU-hours, 저장소 5GB와 6시간 복구 창을 제시한다. 최저 0.25 CU가 24시간 활성일 경우 30일 약 180 CU-hours로 무료 한도를 초과할 수 있다. 현재 API monitor·worker의 실제 소비는 미측정이며 파기·환급 루프를 임의로 끄지 않는다. [Neon Free](https://neon.com/blog/neon-free-plan-1-gb-per-project)
- 무료 서버는 AI 공급자 호출을 무료로 만들지 않는다. 서버 생성 한도는 요청 수 제한이며 금액 상한이 아니다. 실제 잔액·과금 및 무과금 차단 조건을 별도로 확인한다.
- 외부 백업은 API/worker 중지 및 작업 정리 이후 DB와 비공개 미디어를 함께 보관한다. 암호화·독립 보관 장소, 최신 삭제·인증 폐기 기록의 재적용, 실제 복원 리허설이 아직 없다. VM의 디스크 한 벌만을 독립 백업으로 간주하지 않는다.

## 다른 후보

| 후보 | 확인한 조건 | 판단 |
| --- | --- | --- |
| Google Cloud Free Tier | 미국 3개 리전의 e2-micro 1대, 1GB RAM 및 제한된 무료 디스크·전송량. 기존 CLI 인증은 재인증이 필요하다. | 후보이나 API·worker·Redis가 1GB에서 안정적인지는 측정 전이며 미국 리전과 요금 초과도 확인해야 한다. [공식 조건](https://docs.cloud.google.com/free/docs/free-cloud-features) |
| Render Free | 웹 서비스는 유휴 중지되며 무료 worker는 지원하지 않고 무료 Key Value는 재시작 시 데이터가 유실된다. 계정에 결제수단이 있으면 일부 초과량이 청구될 수 있다. | 지속 작업·큐 운영의 현재 요구를 단독으로 충족하지 않는다. [공식 조건](https://render.com/docs/free) |
| Koyeb Free | 무료 인스턴스 512MB, worker 서비스 불가, 유휴 시 0으로 축소, 프랑크푸르트 또는 미국 지역. | 상시 worker와 내구성 있는 운영에 단독으로 사용하지 않는다. [공식 조건](https://www.koyeb.com/docs/reference/instances) |

## 준비·전환 조건

2026-11-02 로컬 준비: API·worker를 `linux/arm64`로 각각 빌드하고 네트워크를 차단한 컨테이너에서 ARM 실행 및 필수 모듈 import를 확인했다. Docker 빌드 문맥에서 로컬 `.db`·저널 제외가 누락된 것을 발견해 규칙과 회귀 검사를 추가했으며, 최종 두 이미지에 DB 파일과 실제 `.env`가 없는 것을 확인하고 시험 이미지를 삭제했다. 배포 이미지 보안 스캔·레지스트리 게시·실제 VM 실행은 하지 않았다. 현재 GitHub Actions 이미지 빌드는 ARM 플랫폼을 명시하지 않으므로 서버가 확정되면 불변 ARM 이미지의 빌드·스캔·배포 절차를 별도로 확인한다.

1. 계정 홈 리전, Always Free 표기, 카드 확인과 과금/업그레이드 상태 및 실제 배정 가능 용량을 직접 확인한다. 기존 다른 프로젝트를 변경하지 않는다.
2. ARM용 API·worker 이미지 빌드와 보안 검사를 통과하고, 실제 배포에 쓰는 불변 이미지 digest를 식별한다. 로컬 이미지를 운영 배포 완료로 표시하지 않는다.
3. 비공개 자격증명과 CA, HTTPS, 방화벽, Redis 지속성·재기동·복구, 무료 사용량·용량 경고를 검증한다. 현재 Neon은 migration head를 적용했으나 API·worker 운영 연결은 미완료다.
4. 합성 데이터로 연속 작업, 실패·중단 복구, 동의 철회·파기와 환불 처리, 서명된 미디어 접근, 별도 환경 복원을 검증한다. 실제 사용자 데이터는 검증·정책 승인 이전에 사용하지 않는다.
5. 사용자와 운영 빌드를 공동 최종 검토하기 전에는 스토어 등록·업로드·제출하지 않는다. 실결제 연결은 기본 서비스와 운영 기반 이후 별도 진행한다.
