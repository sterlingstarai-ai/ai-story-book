# 구현 개발자용 프롬프트 — #9 잔여(characters 멱등) 마이그레이션 승인

> CTO 재감사 PASS. 잔여 1건(#9 절반)만 처리한다. 나머지 20건은 이미 검증 통과.
> 아래 블록을 구현 개발자 세션에 붙여넣으세요.

---

당신은 AI Story Book 모노레포의 **구현 전담 개발자**입니다. W2–W7 감사 반송 수정은 CTO 재감사를 통과했습니다. **남은 단 하나** — #9 절반(characters from-photo/from-drawing 서버측 멱등)을 마감합니다. **CTO가 마이그레이션을 승인**했습니다(권고: 이번 작업의 핵심 버그 클래스가 멱등 부재로 인한 이중 차감이고 이 두 경로는 크레딧 차감이므로 멱등 구멍을 남기지 않는다).

## 범위 (이것만, 최소 변경)
- `characters` 테이블에 `idempotency_key` 컬럼 추가 + **(user_key, idempotency_key) 부분 유니크**(NULL 제외) — M16/H18과 동일 패턴 재사용.
- `POST /v1/characters/from-photo`, `POST /v1/characters/from-drawing` 서버측 멱등 수용: `get_idempotency_key` 의존성으로 키 조회 → 같은 키 재요청이면 기존 character 반환(재분석·재차감 없이). retell은 이미 완료됐으니 그 패턴을 미러.
- 모바일 api_client에서 두 엔드포인트에 `X-Idempotency-Key` 시도키 전송(createBook 패턴). 계약(openapi.json) 동기.

## 규칙 (재감사에서 통과한 규율 그대로)
- **TDD·false-green 금지**: 멱등 회귀 테스트는 반드시 **수정 전 red 확인**. 검증 대상을 통째 mock하지 말 것 — 같은 (user_key, key)로 두 번 호출 시 character가 1개만 생기고 크레딧이 1회만 차감되는지 **실경로**로 assert. 부분 유니크는 DB 레벨(직접 2행 insert → IntegrityError)로도 잠글 것.
- **실PG 리허설(필수)**: 이 마이그레이션은 SQLite로 미검증이다. 에페메럴 `postgres:16-alpine`에 기존 characters 데이터(중복 없음이 정상이나 방어적으로) 시드 후 `alembic upgrade head` 실행 → 부분 유니크 생성·NULL 다중 허용 확인. `down_revision`은 `alembic heads`로 현재 head(`f6a7b8c9d0e1`) 확인 후 지정, 적용 후 단일 head 유지.
- 게이트: `pytest tests/`(회귀 0) · `ruff check src/ tests/` · `flutter test` · `flutter analyze` · `alembic upgrade head && alembic heads`. 계약 변경 시 openapi 재export + 신선도 테스트.
- 커밋은 오너(staged까지). `.env`/secrets 금지.

## 완료 시 CTO 제출
- 변경 파일 / 추가 마이그레이션(down_revision·새 head) / 멱등 실경로 테스트명 + **수정 전 red 확인 여부** / 실PG 리허설 결과 / 게이트 결과.

**착수 전 계획(컬럼·부분유니크·두 엔드포인트 배선·테스트 설계·실PG 리허설)을 3–5줄로 먼저 제시**하고 진행하세요.
