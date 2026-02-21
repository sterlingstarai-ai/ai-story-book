# Autonomous Progress Snapshot (2026-02-21)

## 이번 사이클 구현 완료

1. 무료 플랜 서버 강제 정책 추가
- 월 생성 한도(기본 2권), 스타일 제한(`watercolor`/`cartoon`), PDF/오디오 제한을 `/v1/books` 경로군에 적용.
- 테스트 환경에서는 기본 비활성, 필요 시 `FREE_PLAN_ENFORCE_IN_TESTING=true`로 검증 가능.

2. 무료 플랜 정책 회귀 테스트 확장
- 스타일 제한, 월 한도, PDF/오디오 차단, 시리즈 생성 제한, 유료 플랜 우회 케이스 추가.

3. 구독 중복/라이프사이클 보강
- IAP 동일 플랜 중복 구매 시 `already_subscribed` 응답 처리.
- 취소 구독은 기간 종료 전까지 권한 유지하도록 정정.
- 플랜 변경 시 최신 플랜 우선(기존 플랜 기간 즉시 종료)으로 정정.
- `/v1/credits/subscribe` 직접 호출의 동일 플랜 재구독 중복 크레딧 지급 차단.

4. 모바일 결제 제한 UX 보강
- `PAYMENT_REQUIRED(402)`를 생성/뷰어 경로에서 감지해 일반 에러 대신 크레딧/업그레이드 모달 표시.
- 취소 예정 구독 상태(`cancelled`) UI 배지/안내 문구 반영.

5. 외부키 최종 점검 자동화
- `scripts/final-external-preflight.sh` 추가.
- 외부 연동 키 누락을 한 번에 점검하고 최종 검증 명령을 안내.

6. 학습 모드 접근 조건(P1-12 확장) 보강
- `PageResult.hasLearningContent` 추가 (`vocab/질문/퀴즈` 중 하나라도 있으면 true).
- 뷰어의 학습모드 노출 조건을 `vocab` 단일 기준에서 통합 기준으로 전환.
- 모델 테스트에 `질문만 존재`, `퀴즈만 존재`, `학습자산 비어있음` 케이스 추가.

7. 아동 UX 터치 타겟(64px) 적용 확대
- 공통 상수 `AppSizing.minTouchTarget=64` 추가.
- 뷰어 네비/오디오/공유/언어 토글 및 서재 필터 초기화 버튼, 생성 화면 캐릭터 옵션 아이콘 영역을 64px 기준으로 상향.

8. 다자녀 프로필 기본값 일관성 보강
- 첫 프로필 생성 시 자동 기본 프로필 지정.
- 기본 프로필 직접 해제(`is_default=false`) 차단.
- 기본 프로필 삭제 시 남은 프로필 중 1개를 자동 기본 지정.
- 회귀 테스트 추가(`test_profiles_default_is_always_maintained`).

9. 분기형 스토리 입력 정규화/검증 강화
- `node_key`, `to_node_key`, `option_text` 공백 정규화 및 공백-only 값 차단.
- 동일 노드 내 중복 선택지 문구 차단.
- 선택 처리 시 `option_text` 공백 정규화 매칭 지원.
- 회귀 테스트 추가(`test_branch_story_rejects_duplicate_options_and_trims_inputs`).

10. POD 주문 입력 검증 강화
- `shipping_address`를 구조화 모델로 전환해 필수 필드/길이 검증을 강화.
- 국가코드(`country`)는 2자리 ISO 코드만 허용하고 대문자로 정규화.
- 저장 전 `name/line1/postal_code/phone` 공백 정리(트림) 적용.
- 회귀 테스트 추가(`test_pod_order_validates_and_normalizes_shipping_address`).

11. 인수 산출물 스크립트 고도화
- `scripts/build-acceptance-artifacts.sh`를 개선해 API 가상환경 파이썬 자동 감지/사용.
- 옵션 추가:
  - `--skip-android-build`
  - `--skip-ios-build`
  - `--skip-phase-gate`
- 산출물에 `phase-gate.log`, `git-status-short.txt`, `flutter-pub-get.log` 추가.
- 실행 검증 완료: `docs/acceptance/20260221-125626` 생성.

12. 에러 응답 표준화 회귀 테스트 확장
- POD 주소 검증 실패(국가코드 형식 오류) 시 표준 `VALIDATION_ERROR` 응답 포맷 검증 추가.
- 기본 프로필 직접 해제 차단 시 표준 `VALIDATION_ERROR` 응답 포맷 검증 추가.
- 파일: `apps/api/tests/test_error_responses.py`

13. 프로필/음성프로필/IAP 입력 정규화 강화
- 프로필 이름 공백-only 입력 차단, 이름/선호테마/아바타 URL trim 및 optional 필드 빈 문자열 `null` 정규화.
- 음성 프로필 라벨/URL 정규화 및 URL 형식 검증 강화, 동의 없는 프로필 활성화 차단.
- IAP `product_id`/`transaction_id`/token/receipt 공백 trim 및 공백-only 입력 차단.

14. 분기형 선택 API 공백 입력 차단 보강
- `/v1/branch/books/{book_id}/choose`에서 `option_text`/`to_node_key`가 공백-only인 경우 명시적 검증 에러 반환.

15. 테스트 커버리지 확장(무개입 범위)
- API: 신규 정규화/검증 회귀 테스트 5건 추가.
- Mobile: `api_client_test.dart`에 프로필 헤더 전달, 설정 패치, POD 주문, 발음평가 페이로드 테스트 추가.

## 검증 결과

1. API 테스트: `278 passed`
2. Mobile 정적 분석: `No issues found`
3. Mobile 테스트: `All tests passed`
4. 통합 게이트: `./scripts/phase-gate.sh` 통과

## 현재 남은 사용자 개입 항목

1. 실서비스 키/계정 주입
- Apple/Google IAP 검증 키
- Printful 키
- Kakao/AdMob 모바일 키

2. 실제 Sandbox/스토어 환경 검증
- 실결제/갱신/취소 웹훅 이벤트
- 실POD 상태 동기화
