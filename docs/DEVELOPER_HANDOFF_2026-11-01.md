# AI Story Book 개발 인수인계 — 2026-11-01

## 먼저 읽어 주세요

사용자는 기존 개발자에게 현 상태를 넘기고 싶어 합니다. 이 문서는 현재 Mac의 작업 내용과 검증 이력을 요약한 것이며 배포 승인이 아닙니다. 저장소는 `/Users/jmac/Desktop/ai-story-book`, 브랜치 `codex/pre-release-completion-20260907`, HEAD `c20d312`입니다(작성 시점). **수정·미추적 파일이 많고 기존 개발자의 변경과 이후 AI 작업이 섞여 있습니다. 모두 AI가 작성한 것으로 간주하지 마세요.** `git status --short`, `git diff`와 미추적 파일을 먼저 확인하고, 리셋·클린·강제 체크아웃하지 마세요. 이 문서에는 비밀번호나 키 값을 넣지 않았습니다.

**현재 공개 출시 NO-GO**: 지속 가능한 운영 환경, 정책 확정, 실제 API 동화/그림 품질과 운영 연결 빌드의 사용자 공동 검토가 끝나지 않았습니다. 2026-11-02 사용자 전용 Neon에 앱 드라이버 연결과 마이그레이션은 통과했으나 운영 서비스 연결·복원 검증은 남았습니다. iOS 전체 음성 낭독의 이전 격리 시험은 아래 기록을 참조하세요. 사용자와 실제 앱을 함께 최종 검토한 뒤 스토어 등록·업로드·심사 제출을 진행하기로 한 기존 결정이 있습니다. 물리적 동화책 제작·배송은 범위에서 제외합니다.

## 진행한 주요 작업

아래는 이번 자율 작업에서 기록된 변경이며 기존 미커밋 변경에 덧붙어 있습니다. 실제 diff와 테스트를 확인해 주세요.

- **DB 연결**: `apps/api/src/core/database_options.py`, `database.py`, `alembic/env.py` 등에 `postgresql+psycopg://` 옵트인 추가. `verify-full`과 `channel_binding=require`를 유지하며 기본 asyncpg 경로는 보존. Neon URL의 channel binding 옵션은 asyncpg에서 그대로 지원되지 않습니다. 이 Mac에서 libpq `sslrootcert=system`은 인증서 오류였고 명시적 신뢰 CA 번들은 성공했습니다. `.env.example` 설명 참조.
- **Redis/작업 큐**: 전용 Redis의 DB 0만 사용할 수 있을 때 `CELERY_REDIS_NAMESPACE`로 브로커·결과 키를 분리하고 producer task를 앱의 Celery 객체에 연결. 기본 DB1/DB2 동작 유지. 관련 코드 `src/worker.py`, `src/services/tasks.py`, `src/core/config.py`.
- **운영 복구**: `job_monitor.py`에서 캐릭터 정리 실패가 개인정보 파기 재시도를 막지 않도록 분리. `src/ops/maintenance_once.py`는 공개 엔드포인트 없는 일회성 정리 도구로, 실패 및 일부 미해결 복구 작업을 실패로 반환합니다. 기존 상시 루프는 꺼지지 않았고 외부 스케줄러는 아직 구축·검증되지 않았습니다.
- **비용·요청 보호**: `src/core/cost_budget.py`에서 비테스트 환경의 전역 일일 생성 한도 0 이하일 때 직접 요청도 503으로 차단. 이것은 요청 건수 제한이지 금액 상한이 아닙니다. `src/core/request_body_limit.py`는 요청 바이트 상한 17 MiB를 적용하고 nginx 상한을 정렬; 이미지 마스크는 10 MiB 초과를 거부합니다.
- **사진 동의**: 모바일 `lib/core/photo_consent.dart`에서 사진 동의와 함께 필수 개인정보·데이터 처리 동의 및 철회 상태를 검증하고 불완전한 저장 응답이면 진입을 막습니다. 동의/철회 문구도 구현에 맞춰 조정했으나 공개 개인정보 정책과 법률 검토는 미완료입니다. 서버에는 기존에도 별도 동의 검사가 있었습니다.
- **iOS 환경**: Xcode/iOS 시뮬레이터 실행 환경을 복구하고 iOS 26.2 및 27.2 격리 시뮬레이터에서 온보딩·보호자 확인·Keychain 및 Viewer 관련 시험을 수행. 각 시험의 모의 API/기존 오디오 사용 범위를 확인해 주세요.

## 실제 기능 시험과 한계

- **2026-11-02 새 가상 4쪽 표본**: 별도 실제 AI 생성이 1쪽 자동 보완 후 완료됐고 전체 재검수를 통과했다. AI 보조 시각 검토에서 보완된 장면은 본문과 더 명확히 일치했다. 한 권의 결과이며 독립 사람 검토·실제 아동 데이터·합격률·출시 승인을 뜻하지 않는다. 11월 1일 실패 사례는 그대로 유지한다. [재점검](DEVELOPER_RECHECK_2026-11-02.md), [결과](acceptance/2026-11-02-fictional-quality-review/result.json).

- **동화·그림**: 2026-11-01 가상의 인물로 OpenAI 실제 4쪽 동화/그림 생성 시험을 실행. 153.8초에 1쪽 자동 검수가 `action_mismatch` 1, `unsafe_depiction` 1을 보고해 `IMAGE_QUALITY_FAILED`로 중단했습니다. 이는 자동 판정이며 실제 위험 여부는 독립 육안 검토 전 미확정입니다. 생성 검사·안전 게이트를 끄지 않았습니다. [결과](acceptance/2026-11-01-live-synthetic-recheck/result.json). 이전 실제 4쪽 생성이 기술 완료하고 자동 검수를 통과한 기록도 있으나 육안 검토에서 본문과 그림 차이가 남았습니다. 실제 12쪽 자동 완성의 과거 기록도 있으므로 성공 이력을 삭제하거나 최신 실패를 전체 실패로 일반화하지 마세요. [품질 기록](ILLUSTRATION_QUALITY_GATE.md), [출시 현황](LAUNCH_STATUS.md).
- **전체 워커 흐름**: 격리 PostgreSQL·Redis·MinIO 및 실제 Celery에서 동화 2건 연속 완료. LLM·이미지·그림 검수는 명시적인 모의 구현이므로 실제 AI 품질 증거는 아닙니다. [결과](acceptance/2026-11-01-celery-mock-review-recovery/result.json).
- **음성**: 2026-09-08 OpenAI TTS 일반 한국어 문장 1회 성공 기록이 있으며, 2026-11-01에도 기존 OpenAI LLM 키를 일회성 프로세스 메모리에만 사용해 OpenAI TTS HTTP 200, 93,312바이트/5.832초 MP3 형식을 확인했습니다. 현 로컬 `.env`는 `TTS_PROVIDER=elevenlabs`, `AUDIO_FEATURE_ENABLED=false`; ElevenLabs 키 시험은 HTTP 401이었으며 정확한 원인은 미확인입니다. 키를 출력하거나 영구 설정·권한을 변경하지 않았습니다. 종료 시 Redis 비동기 연결 정리 경고가 있었습니다. **단일 TTS 성공은 iOS 앱의 모든 페이지 연속 낭독 성공이 아닙니다.** 이전 4쪽 Viewer 재생은 저장된 기존 TTS와 루프백 서버를 이용한 시험입니다. [음성 기록](DIGITAL_RELEASE_VERIFICATION_2026-09-08.md), [시뮬레이터 로그](acceptance/2026-11-01-stale-audio-fetch/native-26.2/).
- **추가 확인 — 2026-10-23 선행 음성 시험**: 위 설명 외에, 실제 생성 동화의 본문 4쪽을 격리 서버에 복원하고 OpenAI TTS를 쪽마다 새로 생성한 뒤 iOS 시뮬레이터의 실제 Viewer에서 각 쪽의 재생·일시정지·재개·자연 종료가 통과한 기록이 있습니다. 그림 검수는 테스트 대역이었고 운영 환경·물리 기기·발음 품질은 검증하지 않았습니다. 당시 결과이며 현재 작업 트리의 재검증은 아닙니다. [상세 기록](AUDIO_COMPLETION_2026-09-08.md), [시험 결과](acceptance/2026-10-23-real-book-narration/result.json).
- **비용**: 실제 동화·이미지·음성 시험은 기존 유료 API 잔액을 사용했을 수 있습니다. 계정 잔액은 변동하므로 현재액을 재확인하세요. 새 유료 호스팅·구독이나 충전은 사용자 승인 없이 개설하지 않았습니다.

## Neon과 운영 구성

사용자 계정의 전용 Neon `ai-story-book-beta` (프로젝트 `long-sun-59703131`, branch `br-royal-union-aofmgt8s`, DB `storybook`, Singapore, Free)와 비공개 `storybook-private` 버킷을 만들었습니다. 콘솔 SQL 트랜잭션과 실제 앱 StorageService의 합성 객체 업로드·서명 다운로드·비서명 거부·삭제를 검증했고 시험 객체 및 storage-only 키는 정리했습니다. 기본 Neon 생성 자격증명은 변경하지 않았습니다. [저장소 시험](acceptance/2026-11-01-neon-storage-qa.json).

**2026-11-02 사용자 소유 Neon DB 연결과 마이그레이션 통과:** 지정 직접 호스트와 DB를 확인하고 TLS verify-full·channel binding=require를 적용한 앱 psycopg 동기·비동기 연결에 성공했다. 기존 public 관계 객체가 0개임을 확인한 뒤 마이그레이션 전 백업을 생성하고 아카이브 목록을 읽었다. 온라인 Alembic head `2a8d9e4f610b` 및 public 테이블 33개를 확인했고 Neon 콘솔에서도 테이블 생성을 확인했다. [실행 결과](acceptance/2026-11-02-neon-migration-retry/result.json). 이 백업은 **마이그레이션 전 빈 스키마**다. PostgreSQL 18 `pg_dump`로 만든 원본을 PostgreSQL 16에 그대로 복원하면 `transaction_timeout` 설정 오류가 났고, 16의 `pg_restore`는 아카이브 버전도 읽지 못한다. PostgreSQL 18 `pg_restore`가 출력한 SQL에서 해당 설정 한 줄만 제외해 격리 PostgreSQL 16에 복원하는 별도 시험은 통과했고 public 관계 객체 0개를 확인했다. 이는 운영 데이터 백업·복원이나 자동 복구 성공이 아니다. 향후 Neon 16 백업은 호환되는 PostgreSQL 16 도구를 사용하고 실제 복원까지 검증한다. 앱 운영 설정에 영구 자격증명을 저장하거나 운영 API/worker를 배포하지 않았다. 이전 별도 단기 Neon 시험은 [상세 결과](acceptance/2026-11-01-neon-claimable-tls/REPORT.md)에 남긴다.

프로젝트 한정 API 키를 사용자 승인 후 발급했으나 도구 출력에 비밀값이 노출되어 즉시 폐기·목록 제거 확인했습니다. 공식 CLI/MCP의 초기 OAuth는 계정 전체 권한을 요구해 승인하지 않았습니다. 개발자는 안전한 비밀관리 방식으로 본인에게 필요한 범위의 접근을 받아 연결하세요. 인증정보를 채팅·코드·로그에 넣지 마세요.

Neon Free는 compute/네트워크 한도에 도달하면 중지될 수 있습니다. 기존 API monitor 5분·readiness 30초·상시 worker가 유휴 중지를 방해할 수 있어 월 무료 한도 준수는 미검증입니다. 파기·환급 루프를 대체 스케줄러의 인증, 모니터링, 재시도 및 복구 검증 없이 끄지 마세요. Upstash의 시험용 Redis는 임시 자원으로 영구 운영 자원이 아닙니다.

## 개발자 우선순위

2026-11-01 후속 점검: 현재 HEAD `c20d312` 및 기존 미커밋 작업을 확인했다. API의 Redis 네임스페이스, 생성 한도, 마스크 크기, 유지보수, psycopg 연결 옵션, 요청 크기 관련 집중 테스트 40개와 Flutter 낭독·사진 동의 집중 테스트 48개가 통과했다. `git diff --check`도 통과했다. 이 결과는 전체 테스트나 운영 연결 검증을 대체하지 않는다. 최신 실패 시험의 보관 디렉터리에는 이미지가 없으며 정리 로그에 격리 컨테이너 제거가 기록되어 있어 해당 이미지의 육안 판정은 여전히 미완료다.

2026-11-02 후속 점검: 사용자 소유 Neon의 정확한 직접 호스트·DB·계정을 확인하고 읽기 전용으로 TLS verify-full 및 channel binding=require, 앱 동기·비동기 psycopg 엔진 연결을 통과했다. 이어 위와 같이 온라인 마이그레이션을 별도 완료했다. 전체 API 첫 실행은 2,199 통과·4 실패·27 건너뜀이었으며 readiness 헤더 변경을 반영하지 않은 픽스처 3건과 Redis 연결이 테스트 간 이벤트 루프를 넘나든 상태 점검 픽스처 1건을 수정했다. 재실행은 2,203 통과·27 건너뜀이다. Flutter analyze 및 전체 테스트 623 통과·2 건너뜀, UI preflight 통과. 개별 구성요소를 실행한 결과이며 최초 phase-gate 명령은 API 실패로 중단됐다. 공급자·운영 DB migration·실제 기기 검증은 이 테스트의 범위 밖이며, Neon migration은 위에 기록된 별도 실측이다.

1. 작업 트리와 변경 출처를 검토해 안전한 보존/통합 기준을 정한다. 실제 사용자 정보와 기존 비밀을 노출하지 않는다.
2. 기존 OpenAI 음성 권한과 올바른 배포 설정을 확인하고 가상 내용으로 각 페이지 생성·일시정지·재개·연속 재생을 iOS 전체 앱에서 검증한다. ElevenLabs 401 원인은 별도 확인한다.
3. 최신 생성 실패의 해당 1쪽을 안전하게 육안 검토해 자동 검수 오탐인지 실제 결함인지 분리한다. 필요하면 원인을 수정하고 합성 내용으로 재검증한다. 품질·안전 검사를 우회하지 않는다.
4. 전용 Neon의 TLS/CA/channel binding과 온라인 migration은 위 결과로 확인했다. 운영 서비스 설정, 운영 스토리지·백업·복원·대기열/worker 및 파기/환급을 검증하고 무료 한도와 무과금 차단·장애 대응을 확인한다.
5. 개인정보 정책의 공급자·처리국·보존/파기 조건을 실제 구현과 맞춘다. 사용자는 OpenAI ZDR 승인을 받았다고 확인했으며 같은 질문을 반복하지 말고 적용 프로젝트·모델/엔드포인트를 독립 확인한다. 실제 아동 정보는 검증 전 사용하지 않는다.
6. 운영 연결 빌드로 사용자와 공동 최종 검토 후 스토어 절차를 진행한다.

## 추가 참고

- [운영 이력](../../00_포트폴리오/AUTONOMOUS_OPERATIONS.md) — 다른 제품의 이력도 포함. 최신 항목이 과거 기록을 보완합니다.
- [Neon psycopg 격리 검증](acceptance/2026-11-01-neon-psycopg-channel-binding/result.json)
- [Celery/Redis 호환 검증](acceptance/2026-11-01-single-db-celery-compat/result.json)
- [삭제·환급 복구 검증](acceptance/2026-11-01-maintenance-recovery/result.json)
- [개인정보·약관 검토본](acceptance/2026-11-01-privacy-server-preparation/REVIEW.md)

일부 `docs/acceptance`는 Git 무시 대상입니다. 개발자가 다른 컴퓨터에서 볼 수 있도록 전달할 때 비밀·개인정보가 포함되지 않았는지 확인한 뒤 필요한 증거만 안전하게 공유하세요.
