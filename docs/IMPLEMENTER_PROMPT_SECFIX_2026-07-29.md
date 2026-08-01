# 구현 개발자용 프롬프트 — 출시 전 보안 fix

> CTO 전용 보안 감사 결과 Critical/High 0. 아래 **중간 4건 + 버킷 ACL 확인**을 출시 전 처리한다.
> 전체 보고서: `docs/SECURITY_AUDIT_2026-07-29.md`. 낮음 7건은 이번 범위 밖(로드맵 이관).
> 아래 블록을 구현 개발자 세션에 붙여넣으세요.

---

당신은 AI Story Book 모노레포의 **구현 전담 개발자**입니다. 전용 보안 감사에서 Critical/High는 0이었고, **출시 전 정리 권고 중간 4건**을 수정합니다. 아동 데이터·결제 앱이라 규제·비용 항목이 섞여 있습니다.

## 먼저 읽기
- `docs/SECURITY_AUDIT_2026-07-29.md` — 근거 보고서(확정 11건·기각 2건·OWASP 매트릭스). 이번 스코프는 **중간 4건 + §CTO판단 §2 버킷 ACL**만. 낮음 7건과 기각 2건은 **손대지 말 것**.
- `docs/CLAUDE.md` — 규칙(검증 루프·계약·마이그레이션).

## 절대 규칙 (이 팀 규율)
- **TDD·false-green 금지**: 보안 수정마다 수정 전 red 확인. 특히 파기·차단 계약은 **실경로 행위 검증**(예: 스토리지 delete가 실제로 호출되는지 spy). 검증 대상 통째 mock 금지 — mock은 최하위 외부 경계(HTTP·S3 client)에만.
- 최소 변경·§보고서 범위 준수·`.env`/secrets 금지·커밋은 오너(staged까지).
- 게이트: `venv/bin/python -m pytest tests/`(회귀 0) · `ruff check src/ tests/` · `flutter test`/`analyze` · 계약 변경 시 openapi 동기 · DB 변경 시 `alembic heads` 단일 + 실PG 리허설.

## 🟡 S1 (규제 — 먼저) — 음성 프로필 단건 삭제가 S3 오디오를 파기하지 않음
- **취약**: `apps/api/src/routers/voice_profiles.py:303` `delete_voice_profile`이 DB 행만 지우고 `sample_audio_url`(voice-samples/{user_key}/…의 실제 오디오)을 스토리지에서 삭제하지 않는다. 형제(계정 삭제 users.py:127·캐릭터 삭제 characters.py:504)는 파기하는데 이 경로만 누락 → 가족 음성(biometric-adjacent PII)이 사용자 명시 삭제 후에도 영구 잔존(PIPA/GDPR 파기 의무 위반). 동의 철회 경로(voice_profiles.py:270 부근)도 같은 클래스인지 함께 점검.
- **fix**: delete 커밋 전 `profile.sample_audio_url`을 `storage.key_from_public_url`로 역산해 `delete_keys([key])`(또는 프로필 하위 `delete_prefix`) 호출. 실패 키는 계정 삭제(H8)의 `status=partial` 계약과 동일하게 표면화(조용히 삼키지 말 것).
- **테스트**: 오디오 URL을 가진 프로필을 시드 → DELETE → S3(mock) delete 호출에 해당 키가 포함되는지 assert(spy). 수정 전 red 확인. 동의 철회 경로도 커버.

## 🟡 S2 (CVE — 1줄) — python-multipart 취약 버전
- **취약**: `apps/api/requirements.txt`의 `python-multipart==0.0.12`가 CVE-2024-53981(<0.0.18, 악성 multipart boundary로 이벤트루프 블록 DoS). 업로드 엔드포인트(pronunciation·voice-profiles·인페인트·characters)가 near-unauth로 도달 가능.
- **fix**: `python-multipart>=0.0.18`로 상향(venv 재설치 후 전체 pytest 회귀 0 확인). 겸해 CI Trivy fs 게이트가 CRITICAL만 차단하니(ci.yml) **HIGH도 blocking에 포함**하거나 `safety` 게이트가 이 GHSA를 실제로 잡는지 확인.

## 🟡 S3 (공급망) — CI 배포 액션 SHA 핀
- **취약**: `.github/workflows/ci.yml`의 서드파티 액션이 가변 태그(@v1.2.5·@v2·@v5·@v3/@v6). 특히 deploy 잡의 `appleboy/ssh-action`은 프로덕션 SSH 개인키(secrets.DEPLOY_*)를 주입받는다 — 메인테이너 계정 탈취/악성 리태그 시 배포 파이프라인 장악.
- **fix**: **최소한 `appleboy/ssh-action`을 전체 커밋 SHA로 핀**(주석에 버전 병기). 여력되면 codecov·gitleaks·subosito·docker/* 도 SHA 핀 + dependabot/renovate로 업데이트 관리. (codecov·gitleaks·flutter는 PR에서만 돌고 SSH 키 없음 → 상대적 저위험, appleboy 우선.)

## 🟡 S4 (비용 — 최소 가드레일만) — 크레딧 cost-DoS
- **취약**: `apps/api/src/services/credits.py:62` — 처음 보는 user_key에 무조건 3크레딧 지급. X-User-Key는 클라 임의 UUID(dependencies.py)라, 매 요청 새 UUID로 3크레딧을 받아 LLM/이미지 비용을 무제한 소진 가능(모든 rate/daily/free 통제가 로테이션 가능한 동일 키에 묶임).
- **범위 주의**: 완전 해법(디바이스 attestation·IP 신규키 스로틀·지연 보너스)은 **제품 결정이라 이번 스코프 아님**. 이번엔 **비용 상한 가드레일만** 넣는다:
  - **fix (택1, CTO 승인 범위)**: (A) 서버측 **전역 일일 생성 예산**(전 user 합산 이미지/LLM 생성 횟수 상한, Redis 카운터) — 초과 시 신규 생성 429 + 운영 알림 로그. 또는 (B) 신규가입 보너스를 3→1(또는 0)로 축소하고 첫 IAP/재방문 전 상향 보류. **A(전역 예산 가드레일)를 권장** — 익명 온보딩을 안 깨면서 청구서 폭증만 막는다.
  - production-ops 비용 가드레일 성격이라 임계값은 설정값(env)으로 두고 기본은 보수적으로.
- **테스트**: 전역 카운터가 상한 도달 시 신규 생성이 429로 차단되고 알림 로그가 남는지. 정상 범위는 통과(과잉 차단 회귀 방지).

## 🔍 S5 (실환경 확인 — 코드 아님) — 민감 미디어 버킷 ACL
- 아동 사진(`characters/{id}/photo`)·가족 음성(`voice-samples/…`)이 만료 없는 안정 공개 URL(`{s3_public_url}/{key}`)로 저장된다. `storage.put_object`에 `ACL='public-read'`는 없으니 **실제 공개 여부는 프로덕션 버킷 정책**이다.
- **할 일**: 운영 버킷(R2/S3)의 민감 미디어 prefix가 public-read인지 확인 → **public이면 비공개 + 서명 URL(presigned) 또는 인증 프록시로 전환**. 이건 코드 수정일 수도(서명 URL 발급), 버킷 정책 변경일 수도 있음 — 어느 쪽인지 판단해 FIXLOG에 기록. 불명확하면 CTO에 확인.

## 진행
1. **S1(규제) → S2(CVE) → S3(SHA 핀) → S4(비용 가드레일) → S5(버킷 확인)** 순.
2. 각 수정 red 확인 → green → 게이트 회귀 0 → per-fix(또는 클러스터) 커밋(푸시 안 함) → FIXLOG 갱신.
3. **낮음 7건·기각 2건은 손대지 말 것**(범위 밖).
4. 끝나면 CTO 재감사용 요약(수정 파일·실경로 red 확인 여부·게이트·S5 버킷 판단) 제출. CTO가 동일 방식(게이트 재실행+실경로 검증)으로 재감사.

**S1부터 시작하되, 착수 전 계획(S1 스토리지 파기 경로 + S4 가드레일 A/B 중 택)을 3–5줄로 먼저 제시**하고 진행하세요. S4는 A/B 선택을 먼저 확인받고 구현.
