# 구현 개발자용 프롬프트 — PR #58 CI 첫 가동 실패 3건 수정

> PR #58에서 CI가 처음 돌아 3개 잡 실패. CTO가 로그를 진단함(아래). 하나는 진짜 CVE, 둘은 CI 재현성/설정. 코드 심층 결함 아님.
> 아래 블록을 구현 개발자 세션에 붙여넣으세요. (Run: https://github.com/sterlingstarai-ai/ai-story-book/actions/runs/30681454303)

---

당신은 AI Story Book 모노레포의 **구현 전담 개발자**입니다. PR #58(main←feat 브랜치)에서 CI가 처음 가동돼 3개 잡이 실패했습니다. 로컬 게이트(675/252)는 통과했는데 CI가 실패한 것 = **로컬과 CI의 환경/재현성 차이 + 이제 작동하는 CVE 게이트**입니다. 아래 3건을 수정하세요.

## 절대 규칙
- 최소 변경. `.env`/secrets 금지. 커밋은 오너(staged까지). 각 수정 후 로컬 게이트 회귀 0.
- **CI-1(의존성 bump)은 반드시 전체 백엔드 pytest 재실행**으로 회귀 0 확인(마이너 bump가 뭔가 깰 수 있음).

## CI-1 (진짜 취약점 — Security Scan 잡) — aiohttp HIGH CVE
- **진단**: `apps/api/requirements.txt:28` `aiohttp==3.11.0`가 **CVE-2025-69223**(HIGH, HTTP 파서 auto_decompress zip bomb, 3.13.3에서 수정). 우리가 S3에서 trivy-action을 고쳐(존재하지 않던 ref → SHA + HIGH blocking) **이제 스캔이 실제로 돌아 이 CVE를 정확히 잡은 것** — 게이트가 의도대로 작동 중.
- **fix**: `aiohttp`를 `>=3.13.3`(또는 최신 3.13.x)로 상향. venv 재설치 후 **전체 `pytest tests/` 회귀 0** 확인(3.11→3.13 breaking 여부). aiohttp 사용처(직접 import 또는 SDK 전이)를 grep해 영향 확인.
- **DoD**: `trivy fs --severity CRITICAL,HIGH --exit-code 1 apps/api`(또는 CI 재실행)가 이 CVE로 더는 실패하지 않음 + 백엔드 675 pass 유지.

## CI-2 (재현성 — API Tests 잡, linting) — CI ruff 버전 미핀
- **진단**: CI `Run linting` 스텝이 `ruff check src/ tests/`(로컬과 동일 명령)이지만, 설치가 `pip install ruff safety coverage`로 **ruff 미핀** → CI가 로컬(0.14.14)보다 최신 ruff를 설치 → 최신 버전의 달라진 기본 규칙으로 726건 보고(513 auto-fixable = 대부분 import 정렬·datetime 스타일). ruff 설정 파일([tool.ruff])이 저장소에 없어 버전별 디폴트 차이가 그대로 드러남. **로컬 ruff 0.14.14는 clean = 코드 회귀 아님, 도구 버전 드리프트.**
- **fix (재현성 우선)**: `.github/workflows/ci.yml`의 백엔드 잡 설치 라인을 **`pip install ruff==0.14.14 safety coverage`**로 핀(로컬과 일치). 겸해 safety/coverage도 버전 핀 권장(재현성). 이러면 CI linting == 로컬(둘 다 clean).
- **권장(내구성)**: `apps/api/pyproject.toml`에 `[tool.ruff]` 블록 신설 — `target-version`, `line-length`, 명시적 `select`(현재 통과하는 규칙셋 고정) — 이후 ruff 버전이 올라가도 규칙셋이 흔들리지 않게. 최소는 핀, 여력되면 config까지.
- **주의**: 726건을 "최신 ruff로 전부 auto-fix"하는 건 **이번 스코프 아님**(출시 차단 아닌 스타일 정리 = 출시 후 별도). 지금은 **핀으로 게이트를 재현 가능하게** 만드는 것이 목표.
- **DoD**: CI가 로컬과 동일 ruff 버전으로 linting을 돌려 통과.

## CI-3 (CI 설정 — Flutter 잡) — integration_test device 미지정
- **진단**: 유닛 `flutter test`(252)는 통과. 실패 스텝은 **`Run integration tests (headless flutter_tester)`** — `More than one device connected; please specify a device with -d` → `No devices are connected`로 종료(exit 1). 예전엔 tee/파이프로 마스킹돼 있던 게(M5) pipefail 하드닝으로 이제 표면화된 것.
- **fix**: CI의 integration test 실행에 **명시적 headless 디바이스 지정** — `flutter test integration_test -d flutter-tester`(또는 프로젝트 관례에 맞는 `-d linux`/`-d chrome`). flutter_tester가 여러 디바이스 후보와 충돌하지 않게 단일 지정. integration_test가 CI에서 의미 있게 돌 수 없는 구조면(디바이스/에뮬레이터 필요) 이 스텝을 명시적으로 `if:`로 게이트하거나 유닛과 분리 — 단 **조용히 스킵하지 말고** 왜 분리했는지 주석. (실기기 integration은 실환경 검증 항목과도 연결.)
- **DoD**: Flutter 잡이 device 오류 없이 통과(유닛 커버리지 게이트 포함).

## 진행
1. **CI-1 → CI-2 → CI-3** 순. 각 수정 후 로컬 게이트(pytest/ruff/flutter) 회귀 0.
2. per-fix 커밋(푸시는 오너) → FIXLOG 갱신 → 푸시하면 PR #58 CI 재가동.
3. 끝나면 CTO에 요약(각 수정·로컬 게이트·aiohttp 회귀 확인) 제출. CTO가 CI 재실행 결과로 재감사.

**착수 전 CI-1 aiohttp 사용처 grep 결과 + CI-2/3 수정 방침을 3–5줄로 먼저 제시**하고 진행하세요.

---

## CI-2 후속 결정 (CTO, 2026-08-01) — safety 게이트 처리

CI-2로 ruff를 핀하면 그 뒤 `safety check` 스텝이 처음 실행되며 20건을 보고하는데, **수정 버전이 PyPI에 존재하지 않는 유령 findings가 대부분**임을 CTO가 실측 확인:
- python-multipart 주장 0.0.31(실제 최신 0.0.20, 우리 0.0.20=CVE 해소) · pytest 주장 9.0.3(실제 최신 8.4.2) · python-dotenv 주장 1.2.2(**우리 1.2.1이 이미 최신**). → 존재하지 않는 버전으로는 올릴 수 없어 **게이트가 충족 불가능**.

**결정: B — safety를 advisory로 낮추고 Trivy를 블로킹 정본으로.** (safety 무료 DB 품질 문제; Trivy는 aquasec DB로 aiohttp CVE를 실존 수정본과 함께 정확히 잡음.)

구현 조건(필수):
1. `ci.yml`의 safety 스텝에 **`continue-on-error: true`**를 명시하되 **출력은 그대로 보이게**(`|| true`/`|| echo`로 삼키지 말 것 — 원 감사 M2 'silent safety' 반복 금지). 실패가 노란색으로 표시되되 잡을 막지는 않음.
2. **Trivy fs는 CRITICAL+HIGH 하드 블로킹 유지**(S2대로). aiohttp(CI-1)는 이 게이트로 여전히 반드시 수정.
3. safety 스텝 주석에 사유 명기: "safety 무료 DB가 존재하지 않는 fix 버전을 보고(unsatisfiable)해 advisory로 둠. 블로킹 정본은 Trivy(aquasec DB). 출시 후 재평가."

---

## CI-1 정정 (CTO, 2026-08-01) — aiohttp는 상향이 아니라 **제거**

구현자가 aiohttp가 **고아 의존**임을 발견, CTO가 실측 확인: src·tests import 0건 / `pip show` Required-by 비어 있음 / 유일 역참조는 `uvloop`의 선택적 `extra == "test"`(미설치)뿐. 상향(3.13.5)해도 CVE 11건(수정본 미존재) 잔존.

**결정: A — `requirements.txt`에서 `aiohttp` 라인 제거**(원 '상향' 지시 취소). 안 쓰는 의존 제거로 현재 11건 + 향후 모든 aiohttp CVE 영구 소멸, 공격표면·이미지 감소, 기능 비용 0. 상향은 증상 치료라 근본 해결 아님.

조건:
1. `requirements.txt`의 aiohttp 라인 삭제.
2. `pip install -r requirements.txt` 클린 + **전체 pytest 675 회귀 0** 확인.
3. fresh install 환경에서 aiohttp 부재 확인 → Trivy 스캔에서 aiohttp CVE 전부 소멸(CI-1 블로커 해소).
4. (선택) safety/Trivy 지적 다른 패키지도 orphan(import 0·역의존 0)이면 동일 제거 — 과범위 금지.
