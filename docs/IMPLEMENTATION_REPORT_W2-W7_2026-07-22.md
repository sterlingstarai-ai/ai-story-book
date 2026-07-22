# 구현 보고서 — DEV_SPEC v1.3 · Wave 2 → Wave 7

- **수신**: CTO
- **작성**: 구현 개발자 (Claude Code)
- **일자**: 2026-07-22
- **정본 명세**: `docs/DEV_SPEC_2026-07-20.md` (v1.3)
- **진행 원장(티켓별 상세)**: `docs/FIXLOG_2026-07-20.md`
- **베이스라인**: **W1**(치명 + M8)은 이전 세션에서 구현(`fab7bd8`) + **CTO 감사 PASS(확정 결함 0)** 완료 — 본 보고서는 그 위의 **W2→W7**를 다룹니다.

---

## 1. 요약 (Executive Summary)

DEV_SPEC v1.3의 **W2~W7 전 티켓(84건)을 TDD로 구현·커밋 완료**했습니다. 각 티켓은 롤백 체크포인트로 per-ticket(또는 상호의존 클러스터) 커밋했으며, **푸시는 하지 않았습니다**(정책: 리뷰 후 창업자 직접 푸시).

최종 인수 게이트는 전부 그린입니다:

| 게이트 | 결과 |
|---|---|
| 백엔드 `pytest tests/` | **619 passed / 0 failed** |
| 백엔드 `ruff check src/ tests/` | 통과 |
| Alembic | 단일 head `f6a7b8c9d0e1` |
| OpenAPI 계약 신선도 | 통과 (committed == generated) |
| 모바일 `flutter test` (3.38.7) | **242 passed** |
| 모바일 `flutter analyze` | 무이슈 |
| gen-l10n | 최신 (ko/en/ja 패리티) |

**⚠ 단, "코드는 완료·검증됨"이지 "실환경까지 검증됨"은 아닙니다.** 단위/통합 게이트로 대체 불가한 4개 실환경 검증(CI 런타임·실서버 배포·iOS Xcode/디바이스·Android 실빌드)은 §6에 명시했으며, 이는 미구현이 아니라 제 실행 환경의 한계입니다.

---

## 2. 구현 규율 (Methodology)

- **TDD**: 티켓별 실패 테스트(RED) 작성 → 최소 수정 → GREEN. 엔드포인트 재현이 어려운 경우 순수 헬퍼 추출 또는 시임/정적 가드로 불변식 잠금.
- **최소 변경**: 스코프 외 수정 배제.
- **§2 규범(G-결정) 준수**: 34/34 확정 결정을 그대로 이행(§5 상세).
- **핸드오프 정정 우선**: 각 티켓의 `⚠ 핸드오프 검토 정정` 블록을 원 fix_steps보다 우선 적용(예: MI3 — STT `:-mock` fail-open 재도입 금지).
- **웨이브별 회귀-0 게이트**: 커밋 전 관련 스위트 그린 확인. 계약을 바꾸는 티켓은 **풀 회귀 후** 커밋(§4의 M9 사건 이후 강제).
- **돈/삭제/스키마**: 실DB(임시 PG) 리허설 또는 정적/행위 가드로 검증.

---

## 3. 웨이브별 구현 결과

### Wave 2 — IAP 영수증·웹훅·구독 정합의 돈 코어
**티켓**: C1, H4, H5, M13, M16, L8, L10 · **커밋**: `4d0933b`
- **C1 (헤드라인 치명 — 복원 무한 수익화)**: restore 경로 `grant_credits=False`·이전 소유자 만료·트랜잭션 직렬화로 영수증 재사용 무한 크레딧 차단.
- H4/H5: 웹훅 미기록·오타깃(최신 구독 오만료) — `_apply_webhook_status` 공유 경로 수정.
- M13: free 전환이 유료 구독을 즉시 소멸시키던 결함 수정. M16: `credit_transactions` 멱등 DB 강제. L8: get_or_create 레이스 500. L10: 운영에서 Sandbox 영수증 차단.

### Wave 3 — POD 돈 정합 + 오케스트레이터 크레딧 fence + 모바일 이중차감
**티켓**: M14, H6, H12, H13, L6, L11, H20, H9, H10, H18 · **커밋**: `89ff08b`
- H10: job write-back **fence**로 '책 + 환불' 이중지급 차단. H6/H12/H13/L6/L11: POD 주문 멱등·orphan·Printful payload·통화 ×1300 오염·상태 동기·config fail-open.
- M14: 구독 환불 clawback. H20: 모바일 POD KRW 하드코딩 → 서버 quote 소비. H9: 재시도 가능 LLMError 재시도. H18: 생성 POST 멱등키 미전송 이중차감 차단.

### Wave 4 — 글로벌 i18n(생성·안전·오디오·스트릭) + 모바일 법정 동의/삭제 + 파이프라인 안전
**티켓(21)**: H1, H3, H24, M28, M29, M31, M34, L16, M15, H14, L17, H2, M18, M19, M21, M12, H15, H16, H21, H19, H17
**커밋**: `d31f50b`·`4d4ee1e`·`7da0757`·`31d87e1`·`a86f3a0`·`b743a9c`·`61eddc0`·`5ee9beb`·`c306b95`·`9e96292`·`d1cd8aa`·`d96cce6`·`00e08eb`·`310b497`·`a413f78`·`5b6955f`
- **ja/zh/es 파손 표면 복구**: H1(TTS/STT fail-closed + readiness 게이트), H3(오디오 5개 언어), H24(출력 안전 no-op 폴백), M28/M29(프롬프트·모더레이션 언어), M34(골든 게이트 ja/zh/es), L16(display_name), M15(₩/한국어 하드코딩 + 에러/플랜/타이틀 l10n).
- **파이프라인 안전**: M31(rewrite 검증), M12(재생성/리텔/인페인트 입출력 모더레이션 — 조용한 no-op 제거), M18(좀비 잡 재큐), M19(이미지 게이트), M21(사진 분석 fail-open 제거), H2(**사용자별 DST-safe 타임존** — G 결정으로 스코프 증가).
- **모바일 법정/출시차단**: H15/H16(사진 동의 fail-closed + PIPA), H21(로케일별 삭제 키워드), H19(시리즈 스타일/연령 상속), H17(폴링 예산 10분 SLA 정합).

### Wave 5 — i18n 종속 해금 + 데이터 유실·삭제권·동시성 + 잔여
**티켓(20)**: M30, M27, H23, M20, M23, M32, H26, M22, H25, L7, L9, L12, M24, M25, H7, H8, H11, M10, M11, N1
**커밋**: `7c0d071`(M20)·`d701f9a`(M24)·`4ce2120`(M25)·`2be8bcf`(M32)·`7429adb`(H23)·`a618b6e`(M10)·`8a2c8df`(H8)·`e447b92`(H11)·`297f00c`(H7)·`25222b3`(M23)·`a5ae27a`(M27)·`65c4e96`(M22)·`434317b`(N1)·`40f4df8`(L9)·`002193a`(L7)·`ee20039`(L12)·`1bf7b0e`(M11)·`246b82b`+`1750e06`(H25)·`2c6099e`(M20 폴링)
- **삭제권/데이터 유실**: H7(series FK로 erasure 500 → 삭제 순서·nullify), H8(스토리지 파기 실패 은폐 → partial 표면화), N1(계정 삭제 시 cover/page 이미지 S3 키 파기), H11(PDF SSRF allowlist — 삽화 전무 수정), M10(retell self-FK ON DELETE SET NULL).
- **동시성/정합**: M23(Celery 재전송 멱등), M22(오늘의 동화 book_id 채워 반복 크레딧 소모 차단), M20(SAFETY_OUTPUT 재시도 + 폴링 상한).
- **잔여**: M27(프리셋 로케일 표시), H23(rewrite 이중 컬럼 동기/무효화), M32(안정 step 키), M24(age gate), M25(인페인트 오분류), L7/L9/L12(스트릭·성장 정합), M11(시리즈 Celery 큐잉).
- **참고**: **M30·H26은 선행 티켓과 중복으로 클로즈**(FIXLOG 기록). 병렬 워크플로우 4-에이전트 배치를 stale-base 위험을 넘어 수동 통합(M23/M27 auto-merge·M22 hand-port·N1 재구현).

### Wave 6 — 인프라·배포·CI·네이티브 출시 하드닝
**티켓(20; M8은 W1)**: H22, M26, L15, M8, M9, H27, H28, M33, L18, L19, M1, M2, M3, M4, M5, M6, M7, L1, L3, L4
**커밋**: `aa5f372`(M9)·`fb3ab91`(M9 정정)·`f8dea6c`(CI 클러스터 M1–M7,L1,L3,L4)·`6d85de1`(H22)·`4148406`(M26)·`f44171e`(L15)·`63f19d3`(L18)·`44ad484`(H27,H28,M33,L19)
- **CI 게이트 실질화**: pipefail 마스킹 제거(M3/M4/M5), safety `||echo` 제거 + Trivy repo/이미지 스캔 **CRITICAL blocking**(M2/M7, G30), `@master`→핀(M6), 배포 직렬화(M1 — 진행 중 배포 취소 금지), L1/L3/L4.
- **배포 배관**: H22(prod compose IMAGE_MODEL/STT/POD/ADMIN/SHARE 미전달 → 이미지 전량 실패 수정), M26(**migrate-before-up** + health 실패 자동 롤백 + volume prune 제거), L15(readiness healthcheck·.env 제외·localhost minio·pg15 통일).
- **보안/버전**: M9(/health/detailed X-Admin-Key 인증 + /ready missing_keys 은닉).
- **네이티브 출시차단**: H27(iOS 카카오 스킴 — 공유 100% 불능 수정), H28(**UIBackgroundModes(audio)** — 취침 오디오 잠금 생존, G27=방식 a), M33(앱명/권한 en/ja l10n), L18(release 서명 fail-closed), L19(도메인 aistorybook.com 통일).

### Wave 7 — 품질·정리 (비출시차단)
**티켓**: L13, L14, L20, L21, L2, L5 · **커밋**: `8f629e6`(L13,L20,L21)·`f21dbeb`(L14)·`ef88cfe`(L2)·`fef1bff`(L5)
- L13(죽은 언어 드롭다운 제거), L20(버전 표기 1.0.0), L21(카카오 딥링크 수신 1차 제외 — G28), L14(계약 드리프트: regenerate `mode` 키·inpaint 409 명세·BookTheme social 패리티), L2(money 경로 per-glob 커버리지 게이트), L5(배치 오디오 실패의 잡 상태 표면화).

---

## 4. 특기사항 — M9 회귀 사건 (투명성 보고)

M9 커밋(`aa5f372`)을 **신규 2개 테스트만 돌리고 풀 회귀 없이 커밋**했습니다. W6 진행 중 풀 스위트에서 **7건 실패**가 드러났습니다. 원인은 로직 결함이 아니라 **M9의 의도된 계약 변경**(① /health/detailed에 X-Admin-Key 필수 ② /ready가 missing_keys 상세 은닉)에 기존 H1/IAP readiness·detailed 테스트가 미갱신 + OpenAPI stale이었습니다(M9 티켓의 explosion-radius가 예고한 H1 공유 불변식 충돌이 정확히 실현).

- **정정**: `fb3ab91` — 테스트를 M9 계약에 정합(앱 로직 무변경) + 계약 재export. 풀 스위트 **619 복구**.
- **재발 방지**: 이후 **계약을 바꾸는 티켓(L2/L5 포함)은 반드시 풀 회귀 게이트 통과 후 커밋**하도록 규율 강화.

이 사건은 적대적 자기검토 게이트가 핸드오프 전에 결함을 잡은 사례로, 숨기지 않고 보고합니다.

---

## 5. 규범 결정(G-결정) 이행 확인

| 결정 | 이행 |
|---|---|
| G26 (M26) | 마이그레이션 **expand-then-contract** 규율 채택 — migrate-before-up 순서 + DEPLOYMENT.md 팀 계약 명문화 |
| G27 (H28) | **UIBackgroundModes(audio)** — 수동 잠금에도 오디오 생존 (wakelock 아님) |
| G28 (H27/L19/L21) | 정본 도메인 **aistorybook.com** / 카카오 딥링크 수신 **1차 제외** / KAKAO_NATIVE_APP_KEY **xcconfig 주입**(하드코딩 금지) |
| G29 (M33) | en/ja 앱명 **영문 'AI Story Book'** 통일 / 권한 문구만 번역 |
| G30 (M2/M7) | 의존성·이미지 CVE **CRITICAL 릴리스 blocking** |
| G31 (M27/M28) | master_description **영어 통일** / 프리셋 **표시명만 로케일** |
| H22 스토어 결정 | 양쪽 스토어 / 자격증명은 어느 쪽도 강제 안 함(OPTIONAL 경고), IAP strict·웹훅 시크릿만 필수 |

---

## 6. ⚠ 실환경 검증 잔여 (단위 게이트로 대체 불가 — 창업자 확인 필요)

아래는 코드·정적/행위 가드로는 구현·잠금됐으나, **실제 인프라/디바이스가 있어야 최종 확인 가능**한 항목입니다. "완료"로 표시하지 않고 명시합니다.

1. **CI 런타임** — Trivy 스캔이 실제 CRITICAL에서 red, 배포 concurrency 큐잉, money-coverage 게이트 실동작. (파이프라인에서만 확인. `actionlint` 미설치라 로컬은 PyYAML 파싱 + 가드 테스트로 대체.)
2. **실서버 배포** — migrate-before-up, health 실패 자동 롤백, volume 미prune. (프로덕션 호스트 필요.)
3. **iOS** — `InfoPlist.strings`를 **Xcode에서 Runner 타깃 variant group으로 등록**해야 실기기 지역화 발효(pbxproj 리소스 그래프 손편집은 무결성 위험이라 의도적으로 회피, knownRegions + 파일만 반영). 카카오 공유(canOpenURL true)·백그라운드 오디오·`KAKAO_NATIVE_APP_KEY` CI 실주입은 실기기 스모크 필요.
4. **Android** — `key.properties` 없이 `--release`가 실패하는지 실빌드 확인.

---

## 7. 산출물 인벤토리

- **신규 가드 테스트**: [백엔드] `test_ci_workflow_gates`(15)·`test_deploy_config`(5)·`test_deploy_script`(5)·`test_infra_hardening`(5)·`test_coverage_gate`(6) / [모바일] `android_signing_test`(2)·`native_config_test`(12). 기타 티켓별 단위/위젯/통합 테스트 다수.
- **신규 도구**: `apps/api/scripts/coverage_gate.py`(money 경로 per-glob 커버리지 게이트).
- **문서**: `docs/FIXLOG_2026-07-20.md`(티켓별 원장), 본 보고서, DEPLOYMENT.md(릴리스 게이트·배포 순서·expand-then-contract).
- **계약**: `packages/shared/schema/openapi.json` 재export(H3·M22·M27·H25·H19·L14 반영).

---

## 8. 결론 및 다음 단계

- **W2→W7 전 티켓 구현·테스트·커밋 완료. 최종 인수 게이트 그린.** 코드 수준의 출시 차단 결함은 봉인됐습니다.
- **다음 단계(창업자)**: ① 브랜치 리뷰 후 **푸시**(정책상 제가 하지 않음) → ② §6의 4개 실환경 검증 소진(CI·실서버·iOS 디바이스/Xcode·Android 빌드).
- 커밋 범위: `git log fab7bd8..HEAD` (W1 베이스라인 이후 전부).
