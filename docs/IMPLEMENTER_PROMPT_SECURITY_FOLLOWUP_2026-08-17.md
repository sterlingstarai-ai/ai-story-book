# 구현자 후속 소웨이브 — 2026-08-17 보안 감사 잔여분

> 선행: 보안 감사(`docs/SECURITY_AUDIT_2026-08-17.md`) + 1차 수정 웨이브(`docs/CTO_REPORT_SECURITY_WAVE_2026-08-17.md`, 커밋됨).
> CTO 감사 PASS 후 오너 결정으로 확정된 잔여 3건. 이 문서 하나를 구현자에게 그대로 주면 된다.

현재 `/Users/jmac/Desktop/ai-story-book` 저장소에서 아래 3건을 원샷으로 수정하라.
0. 절대 규칙은 1차 지시서(`docs/IMPLEMENTER_PROMPT_SECURITY_2026-08-17.md` §0)와 동일:
커밋 금지·staged까지만, red-proof 첨부, 신규 문자열 ko/en/ja + gen-l10n, false-green 금지.

---

## F1 (Q1 오너 결정 — 사진 동의 해제 시 확인 다이얼로그)
**결정**: 사진 동의 항목 해제(photos on→off) 및 전체 철회 시 **즉시 파기 유지 + 확인 다이얼로그 추가**.
- 현재 백엔드는 이미 즉시 파기(1차 웨이브 R1-6 완료). 이번엔 **모바일 UX만** 추가한다.
- 동의 화면(`consent_screen.dart`)·설정에서 photos를 끄거나 철회를 누르면, 확정 전 다이얼로그:
  "사진 동의를 끄면 이 아이 사진으로 만든 **캐릭터와 책이 삭제되며 복구할 수 없습니다.** 계속할까요?"
  (취소/삭제 2버튼). 삭제 확정 시에만 API 호출.
- 문구는 ko/en/ja 3개 `.arb` 동시 + `flutter gen-l10n`. 삭제 대상 건수(캐릭터 N·책 M)를 문구에
  넣으면 더 좋다(선택).
- 테스트: 위젯 테스트 — 미확인 시 API 미호출, 확인 시 호출. red-proof: 다이얼로그 게이트 제거 시 FAIL.

## F2 (감사 Low, books.py:895 — 인페인트 마스크 업로드 하드닝)
- 인페인트 마스크 업로드에 **크기·콘텐츠타입 검증 없음** + 업로드분이 어떤 파기 경로에도 없어 영구 고아.
- 기존 이미지 검증 헬퍼(`_validate_and_read_image` 등 캐릭터 업로드가 쓰는 것)를 재사용해 크기 상한·
  content-type 화이트리스트 적용. 마스크 키(`masks/{book_id}/…`)를 잡 레코드(`image_keys`) 또는
  파기 경로에 편입해 계정 삭제·철회 시 함께 지워지게.
- 테스트: 과대·잘못된 content-type 거부, 마스크가 파기 대상에 포함됨(실PG FK 게이트에 1건 추가 권장).

## F3 (감사 Low, books.py:264 — 크레딧-잡 상태 원자성)
- 크레딧 차감이 잡 상태전이와 **별도 트랜잭션**으로 커밋 → 그 사이 크래시 시 크레딧만 빠지고 잡은
  미생성(무성 유실, 대사 경로 없음). 사용자 손해 방향.
- 크레딧 차감과 잡 생성/상태전이를 같은 트랜잭션 경계로 묶거나, 실패 시 자동 환불(job_monitor의
  기존 refund_for_job 경로 재사용) 도달을 보장. 멱등 유지.
- 테스트: 잡 생성 직전 크래시 시뮬(차감 후 예외)에서 크레딧이 되돌아옴(또는 잡과 원자적).

---

## 완료 게이트
- `venv/bin/python -m pytest tests/` 회귀 0 · `ruff check src/`
- 실PG FK 게이트(F2 마스크 파기 추가분 포함) · `flutter analyze && flutter test` 회귀 0
- `openapi.json` 재export(표면 변경 시) · red-proof 각 건 첨부
- 보고서 `docs/FIX_WAVE_SECURITY_FOLLOWUP_2026-08-17.md`, staged까지만. CTO 감사 후 커밋.

## 스코프 밖 (이번에도 손대지 말 것)
- H4 예산 **값**(오너가 .env 에 실측 기준 주입 — prod compose 기본 300 폴백은 배선 완료), H9 실인증서,
  C1 실기기 IAP 관통(최종 E2E). 수용리스크 4종·Deferred 5종. iap.py:614(쿼리 토큰 로그 유출)는
  1차 웨이브 마감에서 **이미 헤더 전용으로 닫음** — 재작업 불필요.
