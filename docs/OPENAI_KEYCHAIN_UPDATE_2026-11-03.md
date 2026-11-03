# OpenAI 키체인 항목 갱신 도구

`scripts/update_openai_keychain_after_probe.py`는 기본 실행 시 네트워크와 키체인 쓰기를 하지 않는 dry-run이다. `--execute`는 대화형 터미널에서 키를 한 번 숨김 입력받는다. 비밀을 인자·환경변수·파일·로그에 기록하지 않는다.

먼저 `GET /v1/models/gpt-5.6-sol`에 인증해 HTTP 200 및 모델 ID를 확인한다. 이 조회가 403인 경우에만 사용자가 승인한 가상 텍스트 호출을 최대 한 번 수행한다. 이 호출은 유료일 수 있고 최대 출력 토큰은 128이며 `store=false`다. 실패 응답의 본문은 읽거나 기록하지 않는다. 텍스트 성공만 확인하며 이미지 권한·운영 연결·출시 가능성을 보증하지 않는다.

인증 검사가 성공하면 기본 키체인에서 기존 `ai-story-book-openai-production-2026-11-03`/`ai-story-book` 항목의 영구 참조를 찾은 뒤, Security.framework `SecItemUpdate`로 그 항목의 값만 갱신한다. 기존 항목을 삭제하거나 새로 만들지 않으며 ACL을 바꾸는 요청을 하지 않는다. 검사 실패 시 키체인 변경을 시도하지 않는다. 인증 창의 허용 여부는 macOS가 결정한다. 네이티브 호출 중 오류가 발생하면 최종 저장 상태를 확정하지 않고 `KEYCHAIN_UPDATE_UNCONFIRMED`로 출력한다.

격리 fake API·fake Security.framework 기반 unittest 8개와 Ruff가 통과했다. 실제 Mac의 기존 항목을 비밀 없이 영구 참조로 찾는 단계는 통과했고 갱신 함수는 대역으로 막았다. **실제 키체인 갱신, 모델 호출, 운영 적용은 이 도구 검증에서 수행하지 않았다.**
