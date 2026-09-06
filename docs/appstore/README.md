# Store Submission Assets

이 디렉터리는 스토어 제출 자산의 기준 구조를 정의한다.

구성:
- iPhone 6.9인치 캡처 묶음(없으면 공식 규격의 6.5인치 묶음)
- iPad 13인치 캡처 묶음(현재 iPad도 지원하므로 필요)
- `description.ko.md`
- `description.en.md`
- `keywords.txt`
- `submission-checklist.md`

운영 원칙:
- placeholder 이미지는 제출 자산으로 간주하지 않는다.
- 최종 캡처는 실제 빌드에서 다시 생성한다.
- 스토어 설명/키워드는 심사 직전 버전과 앱 기능 상태가 일치해야 한다.

필수 검증 포인트:
- 동의 -> 온보딩 -> 홈 흐름이 스크린샷과 실제 앱에서 일치할 것
- 크레딧/구독, 설정, 프로필, 공유, 삭제 경로가 실제 구현과 일치할 것
- 다국어 설명문이 현재 기능 범위와 차이가 없을 것
- 법적 문서 링크가 실제 호스팅 URL과 일치할 것

2026-09-06에 [Apple 캡처 규격](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)을 다시 확인했다. 현재 개인 검토용 iPhone 17 Pro(6.3인치) 캡처를 필수 대형 화면 제출 묶음으로 간주하지 않는다. 최종 운영 연결과 공동 화면 검토 후 해당 화면 크기에서 실제 앱을 캡처한다. 개인 아동 사진·개인 동화 모음 자료는 제출용으로 복사하지 않는다.

## 로컬 네이티브 검토 자동화

[등록 전 패키지](../PRE_REGISTRATION_PACKAGE_2026-09-06.md)에 6.9인치 iPhone·13인치 iPad의 실제 규격 검토 증거와 외부 출시 단계를 구분했다. `scripts/capture_store_review.py`는 이름이 `AIStoryBookReview-`로 시작하는 이미 부팅된 전용 임시 기기만 받는다. Simulator.app을 열거나 기존 개인 기기를 재실행하지 않는다.

먼저 격리된 mock AI 미리보기 API임을 확인하고 새 전용 시뮬레이터를 headless로 준비한다. 수신기는 저장소 루트에서 실행하고, 앱 여정은 `apps/mobile`에서 실행한다.

```bash
./apps/api/venv/bin/python scripts/capture_store_review.py \
  --device-id <temporary-device-id> --family iphone-69 \
  --output-dir docs/acceptance/new-private-review/iphone-69 \
  --port 18967 --fictional-fixture
```

```bash
flutter test integration_test/final_product_flow_test.dart \
  -d <temporary-device-id> --no-pub \
  --dart-define=FINAL_E2E_LOCAL_API=http://127.0.0.1:18080 \
  --dart-define=FINAL_E2E_ARTIFACTS=http://127.0.0.1:18967
```

iPad는 `--family ipad-13`과 별도 기기·새 출력 경로를 사용한다. 수신한 Flutter PNG는 저장하지 않고, 해당 시점의 실제 기기 화면을 `simctl` JPEG로 기록한다. 크기·해시·mock 여부가 manifest에 기록되며 승인 상태는 false다. 검증 후 이 작업이 만든 수신기만 종료하고 해당 임시 기기만 shutdown/delete한다. 기존 API·개인 책·다른 기기는 보존한다. OS 평점·알림 요청은 테스트에서 제외하며 실제 스토어 동작 검증으로 표시하지 않는다.
