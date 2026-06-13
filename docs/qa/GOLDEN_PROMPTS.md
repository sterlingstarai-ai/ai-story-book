# Golden Prompt Set

이 문서는 생성 품질 회귀 검증용 기준 프롬프트 세트와 그 **검증 하니스**를 정의한다.

운영 원칙:
- 릴리스 전 최소 1회 실행한다.
- 텍스트, 이미지, 학습 자산, 음성 자산이 모두 기대 방향을 유지하는지 비교한다.
- 회귀 비교는 이전 승인 결과와 나란히 검토한다.
- placeholder 이미지, 빈 학습 자산, 안전 필터 과잉 차단은 실패로 본다.

검증 축:
- 이야기 구조: 시작-전개-해결의 명확성
- 연령 적합성: 어휘/문장 길이/정서 강도
- 캐릭터 일관성: 외형/성격/호칭 유지
- 시각 품질: 표지와 본문 장면 연속성
- 학습 자산: vocab/comprehension/quiz 유효성
- 운영 품질: generation_warnings, asset_status, request_id 기록 여부

실행 소스:
- 구조화 데이터: `docs/qa/golden-prompts.json`
- 결과 보관: CI artifact 또는 외부 QA 저장소

---

## 검증 하니스 (`apps/api/scripts/golden_prompts_harness.py`)

위 골든 프롬프트를 **실제 생성 파이프라인**(`start_book_generation`)으로 통과시키고 결과를
검증한다. HTTP 라우터를 우회(in-process)하므로 무료플랜 스타일게이트·크레딧·일일한도 같은
job-setup 마찰이 없다 — 프리미엄 스타일(claymation·oil_painting 등)도 그대로 통과한다.

검증을 세 층으로 분리한다.

| 층 | 무엇 | 언제 | 키 |
|----|------|------|----|
| **STRUCTURAL**(구조) | 파이프라인 완주·페이지 정합·placeholder 없음·학습자산 존재·퀴즈 채점가능/근거·generation_warnings/asset_status 정합·style/언어/연령 *전파* 일치 | 지금(CI 게이트) | 불필요(mock) |
| **CONTENT**(내용) | 연령별 단어수·`quality_check.py`(forbidden/repetition/vocab/character) | 실키 품질 실측 | 필요(`--live`) |
| **SEMANTIC**(의미) | 이야기 구조·정서 톤·캐릭터 일관성·표지-본문 시각 일관성·번역 의미정합 | 사람/LLM 심사 | 자동채점 안 함 |

> **왜 의미 축은 자동채점하지 않나** — expected_signals 를 LLM 심판에게 정답으로 먹이면
> 독립 평가가 아니라 패턴 매칭이 되어 위양성이 폭증한다(target leakage). 심판 보정·기준쌍
> (정상/불량) 없이 자동 점수화 금지. 하니스는 산출물을 덤프하고 "심사 필요"로 명시 보고한다.

> **mock 의 한계** — mock LLM 은 요청 언어/연령을 프롬프트에서 감지해 반영하므로 spec→story
> *전파* 일치(language/target_age)와 style 은 mock 에서도 구조검증된다. 그러나 mock 텍스트는
> 고정 길이/내용이라 *내용*이 연령에 맞는지(단어수)·품질·의미 축은 `--live` 가 필요하다.

> **알려진 한계** — `character_sheet` 는 생성 후 DB 에 독립 저장되지 않아 `--live` 산출물에선
> null 로 나온다. 캐릭터 일관성 의미 심사는 각 페이지 `image_prompt`(master_description 포함)를
> 사용한다.

### 실행

```bash
cd apps/api

# 1) 구조검증(키 불필요, CI 게이트) — 매 PR 자동 실행
python scripts/golden_prompts_harness.py
#   종료코드 0=구조검증 전부 통과, 1=실패. --json / --report PATH 로 리포트 출력.

# 2) 실키 품질 실측(창업자 결정 단계) — 내용검증 + 산출물 덤프 추가
LLM_PROVIDER=openai IMAGE_PROVIDER=gemini IMAGE_API_KEY=... LLM_API_KEY=... \
  python scripts/golden_prompts_harness.py --live --report-dir results/golden
#   results/golden/<id>.json 에 텍스트·이미지·학습자산을 덤프 → 의미 축 사람/LLM 심사.
```

### CI / 회귀 게이트
- `apps/api/tests/test_golden_prompts.py` 가 매 PR 의 pytest 스위트에서 **모든 골든 프롬프트의
  구조검증 통과**를 게이트한다. 동시에 정상 산출물을 외과적으로 훼손한 불량 케이스가 *각 체크를
  실제로 떨어뜨리는지*(teeth)도 증명해 rubber-stamp 를 방지한다.
- CI `api-test` 잡에 standalone 하니스 스텝(mock)도 실행되어 로그로 가시화된다.

### 프롬프트 커버리지(현재 4종)
- `golden-ko-friendship-001` — ko, 5-7, watercolor(무료), 우정
- `golden-ko-bedtime-002` — ko, 3-5, claymation(프리미엄), 생활습관
- `golden-ko-adventure-004` — ko, 7-9, oil_painting(프리미엄), 모험
- `golden-en-bilingual-003` — en, 7-9, cartoon(무료), 모험(이중언어 학습자산)

한국어 3개 연령밴드(3-5/5-7/7-9) 전부 + 무료/프리미엄 스타일 + 이중언어를 커버한다.
새 프롬프트 추가 = `golden-prompts.json` 에 엔트리 1개(`style`은 유효 enum, `theme`는 한국어 enum 값).
