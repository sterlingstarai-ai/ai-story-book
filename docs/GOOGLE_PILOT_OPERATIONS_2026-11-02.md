# Google VM 비공개 시험 운영 기록 — 2026-11-02

> 최신 변경: 개인정보 사건 기록과 매일 백업 예약을 적용했고 마이그레이션 이후 백업을 격리 DB에서 복원했다. 외부 백업 경고 메일의 실제 수신과 시험 경보 해제도 확인했다. 아래의 수동 백업·예약 미설치 및 외부 알림 없음 설명은 이전 시점 기록이다. 최신 실행 근거와 복원 제한은 [백업·삭제 처리 상태](BACKUP_DELETION_GUARD_2026-11-02.md)를 따른다. 보존 기간과 운영 복원 승인은 아직 미완료다.

일반 사용자 대상 공개 서비스가 아닌 소유자 한정 시험이다. Google VM의 443 접근은 시험 시점의 Mac 공인 IPv4 하나로 제한된다. 네트워크가 바뀌면 접속되지 않을 수 있다. 임의로 범위를 전체 공개로 바꾸지 않는다. 포트 80은 인증서 HTTP-01 확인과 HTTPS 리다이렉트에 사용된다.

- 실제 API와 단일 prefork Celery worker는 전용 Neon PostgreSQL·비공개 Neon S3·VM 내부 Redis AOF와 연결됐다. 이미지 및 API 코드는 미커밋 작업 트리의 allowlist 복사본으로 빌드한 로컬 이미지 ID이며, 원격 레지스트리에 게시·스캔된 출시 이미지가 아니다.
- 현재 이미지는 가상 4쪽 시험용 AI 요청 가드와 1일 생성 한도를 사용한다. 시험용 사용자는 합성 생성·삭제 검증 후 삭제됐다. 현재 생성 가드는 시험 요청 횟수를 소진했고 일반 사용자 대상 기능으로 취급하면 안 된다. 글/그림 공급자 관찰의 기본 유효기간은 24시간이며 만료되면 readiness가 503이 될 수 있다. 자동 유료 재검사는 설정하지 않았고 503을 무시하지 않는다.
- API·worker·Redis·nginx는 `unless-stopped` 재시작 정책을 사용한다. 정리된 최종 이미지를 적용한 뒤 VM을 강제 재시작하여 컨테이너 재기동, HTTPS readiness 200 및 worker ping을 확인했다. 시작 직후 API가 준비되기 전 일시적으로 HTTPS 502가 발생했다. 이는 연속 운영이나 장애 없는 복구의 보증이 아니다.
- 2026-11-02 추가 관측: 이전 재시작 후 약 5시간 30분 시점에 네 컨테이너 실행·재시작 횟수 0·OOM 종료 없음, HTTPS readiness 200과 worker ping을 확인했다. 이는 유휴 시점 확인으로 지속적인 가용성이나 부하 시험이 아니다. `asb-observe.timer`는 5분마다 HTTPS 생존 상태와 컨테이너·메모리·디스크·인증서를 기록하고, `asb-observe-ready.timer`는 DB와 저장소를 호출하는 readiness를 1시간마다 기록한다. 두 타이머와 각 서비스의 수동 실행을 확인했고 각 HTTP 응답은 200이었다. 주기 변경 전 5분 타이머의 자동 실행도 확인했지만 변경 후 새 시간표의 자동 실행은 아직 관찰하지 않았다. 별도 알림은 없다. 기존 5분 job monitor와 시간당 readiness는 Neon 무료 컴퓨팅을 깨워 한도를 소모할 수 있으므로 사용량을 확인한다.
- TLS는 고정 IP용 Let's Encrypt 160시간 인증서다. `asb-cert-renew.timer`가 하루 두 번 `asb-cert-renew.service`를 실행한다. 서비스는 [asb-renew-ip](../infra/gcp-pilot/asb-renew-ip)의 고정된 certbot 이미지로 webroot 갱신을 검사하고 nginx를 reload한다. 인증서 갱신 dry-run과 수동 서비스 실행은 통과했다. 만료 알림 및 실제 자동 갱신 시점의 증거는 아직 없다.
- 초기 빈 DB와 가상 동화·이미지 5개가 있는 DB를 각각 백업했다. 후자는 복원한 격리 PostgreSQL 16의 테이블 33개와 격리 MinIO 오브젝트 5개의 체크섬·메타데이터·접근을 대조했다. FileVault Mac 사본과 별도 Google Cloud Storage 비공개 버킷 사본을 비교했다. 백업은 수동이며 일정 실행과 실사용 데이터 복구 시간은 증명하지 않았다.
- 합성 계정 삭제 후 원본 Neon에서 책과 작업 0개, 버킷 객체 0개 및 예전 이미지 URL 접근 거부를 확인했다. 생성 중 미리 기록한 삭제 작업 10건은 15분 안전 유예 후 job monitor가 자동 처리해 모두 `done`·각 최대 1회 시도로 확인했다. 합성 백업 사본은 별도 보존되므로 실제 이용자 삭제의 백업 전파 검증을 뜻하지 않는다.
- Google 백업 버킷은 US-CENTRAL1 Standard, uniform IAM 및 public access prevention을 사용한다. 기본 soft delete가 7일이므로 동의 철회·삭제 기록과 백업 복원/파기 정책을 정하기 전 아동 데이터 운영을 시작하지 않는다.
- 고정 외부 IP는 VM 정지 중에도 요금이 발생할 수 있다. 프로젝트 1만원 예산은 알림이며 자동 차단이 아니다. 2026-11-02 Neon 콘솔은 Free 플랜, 프로젝트 사용량 0.25 CU-hours·32.96 MB를 표시했다. Neon 무료 사용량·OpenAI 호출 및 Cloud Storage 사용량은 별도 확인한다. OpenAI 사용량 화면은 같은 확인 시점에 AI Story Book Beta 프로젝트의 주간 사용액 $1.37, 조직의 11월 사용액 $1.37 / 표시 예산 $100.00을 보여줬다. 사용량 반영 지연이 있을 수 있고 이 금액만으로 개별 시험 비용이나 최종 청구액을 확정할 수 없다. 조직 예산을 변경하거나 충전하지 않았다.

## 운영자가 확인할 명령

```sh
sudo docker ps --filter name=asb-pilot
sudo systemctl status asb-observe.timer asb-observe-ready.timer --no-pager
sudo journalctl -u asb-observe.service -u asb-observe-ready.service --since '24 hours ago' --no-pager
sudo systemctl status asb-cert-renew.timer --no-pager
sudo systemctl status asb-cert-renew.service --no-pager
sudo journalctl -u asb-cert-renew.service --since '24 hours ago' --no-pager
sudo openssl x509 -in /etc/ai-story-book/letsencrypt/live/asb-ip/cert.pem -noout -dates
```

환경 파일과 인증서 개인키, 자격증명, 사용자 키, 서명 URL 및 이미지/본문을 로그나 저장소에 출력하지 않는다. DB·미디어 백업을 다시 만들 때는 API 쓰기와 worker를 중지하고 진행 중 잡 및 삭제 큐를 확인한다. 삭제 후 백업을 복원할 경우 최신 삭제·계정 폐기 기록을 먼저 재적용해야 한다. 백업 스케줄과 복구 키/보존 정책은 아직 설정하지 않았다.
