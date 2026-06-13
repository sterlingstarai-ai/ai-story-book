# 창업자 결정 대기 항목 (배치 처리용)

> 작성: 2026-06-13 · 작성자: Claude (자율 세션)
> 이 문서는 **내(창업자) 결정/키/법무가 필요해 자율로 진행 불가한 항목**만 모았다.
> 한 번에 검토→결정 후, 그 결정을 알려주면 나머지를 이어서 자율 처리한다.
> (자율로 이미 처리한 것·이어서 자율 가능한 것은 `SESSION_2026-06-13.md` 참조.)

---

## 🔴 A. 출시 핵심 관문 (마스터워크 #2 — 이게 no면 그 위 전부 무의미)

### A1. 실키 1세트 투입 → 품질 실측 ★최우선
- **무엇**: LLM/이미지 API 키 1세트를 넣고 `golden_prompts_harness.py --live` 실행 → 한국어 연령별·캐릭터 일관성 품질을 **실측**.
- **왜 결정 필요**: 키가 있어야 실행. 코드·하니스는 **이미 준비 완료**(PR #41 머지됨).
- **하는 법**:
  ```bash
  cd apps/api
  LLM_PROVIDER=openai IMAGE_PROVIDER=gemini IMAGE_API_KEY=... LLM_API_KEY=... \
    python scripts/golden_prompts_harness.py --live --report-dir results/golden
  ```
  → `results/golden/*.json`에 텍스트·이미지·학습자산 덤프 → 의미 축(이야기구조·정서톤·캐릭터일관성·번역정합)은 사람/LLM 심사.
- **결정 사항**: (1) 어떤 키로 실측할지 (2) 품질 합격선

### A2. 이미지 provider = gemini 확정?
- **무엇**: 사진 캐릭터 얼굴보존은 **gemini(Nano Banana)만** 가능. 출시 provider 확정 + 영속화 최종형태·비용 결정.
- **참고**: 권당 ≈$0.35(DALL·E 동급비용+최고품질). 통합 완료(키만 넣으면 동작).
- **결정 사항**: gemini 확정 여부 + 비-gemini 폴백 정책

---

## 🟠 B. 인프라 / 배포 (키·프로비저닝 필요)

### B1. IAP strict + 배포 활성화
- `iap_verification_mode=strict` + `IAP_WEBHOOK_SECRET`(Apple/Google JWS) + 운영 `ALLOW_UNVERIFIED_SUBSCRIBE=false` + 인프라 프로비저닝 + `DEPLOY_ENABLED`.
- **현재**: main 푸시 CI는 Build Docker까지만, Deploy는 `DEPLOY_ENABLED` 미설정이라 자동배포 안 됨.

### B2. 공유 커스텀 도메인
- `SHARE_BASE_URL`(예 `share.aistorybook.app`). 미설정 시 요청 호스트 사용(동작은 함).

### B3. analytics 실 sink 키
- firebase vs posthog **택1** + 키. 코드는 **드롭인 준비됨**(구현 1개 교체+override). 키만 주면 자율 배선 가능.

---

## 🟡 C. 법무 / 규제 (법무 사인오프 필요 — 자율 금지)

### C1. consent 화면 다국어(en/ja) ★l10n 롤아웃에서 유일하게 보류한 화면
- **무엇**: `consent_screen.dart`의 **PIPA 국외이전 법정 고지**(수신자·국가·보유기간·거부권)를 en/ja로 번역.
- **왜 자율 금지**: 법정 고지의 번역은 **규범적/법적 표현**. 부정확한 자동번역은 PIPA 위반 리스크. 한국어가 정본이고, en/ja는 **법무 검토·사인오프 후**에만 적용.
- **상태**: 다른 18개 화면/위젯은 전부 다국어 완료. consent만 ko 그대로 유지.

### C2. 국외이전 별도 동의 플래그
- 수신자·국가·보유기간의 **법정 정확성**은 실제 계약 사실이 있어야 기재 가능(허위 시 PIPA 위반). 실제 데이터 처리 위탁 계약 확정 후.

---

## 🟢 D. 제품 / UX 결정 (가벼운 입력)

### D1. 사진 "홈/생성 메인 CTA 승격"
- 사진 캐릭터를 홈/생성 최상단 메인 CTA로 올릴지 + **배치·문구**. (코드 준비됨, UX 선호 1줄이면 자율 처리.)

### D2. 부모 게이트 VPC 격상
- 현재 부모 인증 게이트가 "두 자리 덧셈" 수준. 더 강한 방식으로 격상할지.

### D3. dependabot major 6건 진행 여부
- `pytest-asyncio` 0.24→1.3(MAJOR) · `share_plus` 7→12(MAJOR) · `intl` 0.19→0.20 · `riverpod_generator` 등(codegen 재생성) · `alembic` 1.14→1.18 · `just_audio` 0.9→0.10.
- **코드영향/마이그레이션 필요**라 안전범프(PR #42)에서 제외. 진행 결정 시 자율 마이그레이션 가능.

---

## 결정 후 내가 이어서 자율 처리할 것
- A1 키 → 실측 실행 + 의미심사 하니스
- A2/B1/B2/B3 결정 → 해당 배선·프로비저닝
- C1 법무 OK → consent en/ja 적용
- D1 문구 → CTA 승격 / D3 진행 → major 마이그레이션
