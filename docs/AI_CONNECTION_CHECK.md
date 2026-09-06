# AI 계정 연결 확인

프로젝트 키는 로컬 API의 `apps/api/.env`에 저장한다. 키 값을 명령행, Git, 테스트 결과에 넣지 않는다. 텍스트 생성은 `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, 그림 생성은 `IMAGE_PROVIDER`, `IMAGE_API_KEY`, `IMAGE_MODEL`을 사용한다. 이 검사 도구는 Anthropic/Gemini 텍스트와 Gemini 그림 공급자를 지원한다.

프로젝트 루트에서 기존 API Python 환경으로 실행한다. `--env-file`은 내용을 실행하지 않고 읽으며, 환경변수보다 명시한 파일 값이 우선한다. `--live`가 없으면 네트워크 요청을 하지 않는다.

```bash
apps/api/venv/bin/python scripts/check_ai_connection.py --env-file apps/api/.env
```

키 발급 후 인증과 선택한 모델의 메타데이터를 확인한다. 아래 명령은 공급자의 고정 HTTPS 주소에 모델 정보 GET 요청만 보낸다. 키는 인증 헤더에만 포함하고 리디렉션·프록시·자동 재시도는 사용하지 않는다. 응답이나 오류의 원문은 출력하지 않는다.

```bash
apps/api/venv/bin/python scripts/check_ai_connection.py --env-file apps/api/.env --live
```

모델 선택이 필요하면 해당 계정의 모델 목록 첫 페이지를 조회한다. Gemini 목록은 현재 어댑터가 사용하는 `generateContent` 메서드를 지원하는 모델만 표시한다. `list_complete=false`이면 목록 전체를 조회한 것이 아니다. 그림 출력 지원 여부는 별도 공식 모델 설명으로 확인한다.

```bash
apps/api/venv/bin/python scripts/check_ai_connection.py --env-file apps/api/.env --component image --live --list-models
apps/api/venv/bin/python scripts/check_ai_connection.py --env-file apps/api/.env --component llm --live --list-models
```

`METADATA_VERIFIED`는 모델 정보 조회가 성공했다는 뜻이다. 생성 권한, 결제·잔액·실제 할당량, 한글 동화 품질, 그림 일관성, 전체 생성 파이프라인을 검증하지 않는다. 이 도구에는 유료 생성 옵션이 없다. 합성 데이터로 수행하는 별도 생성 검증 후에만 해당 증거를 출시 상태에 반영한다. 종료 코드 0은 선택한 검사 단계의 성공이며 출시 승인을 뜻하지 않는다.

공식 API 계약: [Anthropic 모델 조회](https://platform.claude.com/docs/en/api/models/retrieve), [Anthropic 모델 목록](https://platform.claude.com/docs/en/api/models/list), [Gemini 모델 조회·목록](https://ai.google.dev/api/models).

## 소량의 실제 생성 검증

결제·유료 호출이 승인된 경우 별도 도구로 텍스트 1회와 Gemini 그림 1회만 호출한다. 자동 재시도는 없고, 텍스트 출력은 384토큰, 요청 대기는 텍스트 45초·그림 90초로 제한한다. `--live`가 없으면 환경 파일도 읽지 않고 실행 계획만 출력한다. 실행할 때마다 공급자 요금이 발생할 수 있다.

```bash
apps/api/venv/bin/python scripts/run_ai_generation_smoke.py --live --env-file apps/api/.env --output-dir docs/acceptance/2026-09-06-ai-generation-smoke
```

기존 `call_llm`·`generate_image` 어댑터를 통해 가상의 토끼와 반딧불이 이야기만 전송한다. 실제 사용자·아동 데이터와 참조 사진은 사용하지 않는다. 그림 저장만 로컬 파일로 교체하므로 **공급자 어댑터 검사**이며 전체 책 생성·동의·작업 큐·S3 검증이 아니다. 한글 JSON과 디코딩한 PNG, 비밀값을 제외한 응답 상태·요청 횟수·지연·사용 토큰을 새 출력 폴더에 저장한다. 이미 존재하는 폴더를 덮어쓰지 않으며, 결과가 성공해도 `launch_ready=false`를 유지한다.

`--component image` 또는 `--component llm`으로 필요한 공급자만 1회 확인할 수 있다. 기본값은 `both`다. 그림 비율은 `--aspect-ratio`로 지정하며 기본 `3:4`, 선택값은 `1:1`, `3:4`, `4:3`, `9:16`이다. 결과에 요청 비율과 실제 픽셀 비율을 기록하고 상대 오차가 2%를 초과하면 실패한다.

```bash
apps/api/venv/bin/python scripts/run_ai_generation_smoke.py --live --component image --aspect-ratio 3:4 --env-file apps/api/.env --output-dir docs/acceptance/2026-09-06-ai-image-aspect-smoke
```
