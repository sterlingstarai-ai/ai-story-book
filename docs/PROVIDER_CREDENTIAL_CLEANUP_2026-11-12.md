# 제공자 자격 정리 — 2026-11-12

이 문서는 알려진 이전 키 두 개의 로컬 참조 정리와 제공자 측 폐기 결과를 다룬다.
로컬 값 제거, 운영 연결 확인, 제공자 측 키 폐기는 각각의 근거로 확인했다.
전체 기록·백업·외부 서비스를 포괄한 비밀정보 감사 완료를 뜻하지 않는다.

## 현재 운영 연결

실행 중인 API와 워커에서 글·그림·OpenAI 낭독 자격의 SHA256 및 끝 네 글자를
대조했다. 세 역할은 모두 기존 운영 키 `…SUQA`를 사용하며 비공개 파일 입력이다.
사진 분석과 ElevenLabs 키는 두 실행 컨테이너에 없고 사진 기능은 꺼져 있다.
현재 정상 운영 키를 새로 발급하거나 로컬 dotenv에 복제하지 않는다.

## 확인한 이전 로컬 참조

11월 2일 Settings 출력 사고 문서는 `LLM_API_KEY`와 `PHOTO_ANALYSIS_API_KEY`
노출을 명시한다. 출력이 잘려 다른 필드까지 노출됐는지는 확정하지 못했다.
현재 로컬 값의 해시와 제공자 화면의 끝 네 글자를 대조해 아래 두 키를 구분했다.

| 이전 키 | 로컬 파일 | 제거한 필드 |
|---|---|---|
| 글 비교용 `…TF8A` | `apps/api/.env` | `LLM_API_KEY` |
| 글 비교용 `…TF8A` | `apps/api/.env.openai.local` | `OPENAI_API_KEY` |
| 글 비교용 `…TF8A` | `apps/api/.env.before-e2e-review.local` | `LLM_API_KEY` |
| 사진·그림용 `…Y1sA` | `apps/api/.env` | `PHOTO_ANALYSIS_API_KEY`, `IMAGE_API_KEY` |
| 사진·그림용 `…Y1sA` | `apps/api/.env.openai-photo.local` | `OPENAI_API_KEY` |

승인된 로컬 정리는 **4개 파일의 6개 대입**을 대상으로 했다. 읽은 값의 해시가
예상값과 모두 일치하는지 먼저 확인하고, 해당 대입만 제거해 같은 위치에 원자적으로
교체했다. 파일과 나머지 설정, 소유자 및 0600 권한을 보존했다. 원문 키가 담긴
백업은 새로 만들지 않았으며 키체인은 변경하지 않았다. 비밀 없는 전후 영수증은
`docs/acceptance/2026-11-12-final-key-audit/`에 보관한다.

## 제공자 측 폐기 완료

2026-11-12 사용자가 두 키의 영구 폐기를 명시 승인한 뒤, OpenAI의
`AI Story Book Beta` 프로젝트에서 정확한 키 ID와 끝 네 글자를 대조해 폐기했다.
`photo-runtime-20260906`의 `…Y1sA`와 `model-comparison-20260906`의 `…TF8A`가
각각 **Revoked**로 바뀌었고, 실제 화면의 `2 keys successfully revoked` 결과를
확인했다. [폐기 결과 화면](acceptance/2026-11-12-final-key-audit/revoke-two-final.png)

`production-2026-11-03`의 `…SUQA`는 **Active** 상태로 유지됐고 폐기 대상에
포함하지 않았다. 로컬 정리와 이 제공자 측 확인을 합쳐 알려진 두 노출 키의
정리를 완료한 것이다. 다른 키·서비스 전체의 폐기나 이전 기록·백업에 있는
모든 사본의 제거까지 확인한 결과는 아니다.

폐기 후 공개 `/health/ready`도 HTTP 200이었다. 운영 설정·키체인 변경이나 새 유료
AI 요청은 없었다. [제공자 폐기 영수증](acceptance/2026-11-12-final-key-audit/provider-revocation-verification.json)
· [폐기 후 운영 준비 상태](acceptance/2026-11-12-final-key-audit/public-readiness-after-revocation.json)

## 기존 입력 경로 재사용

- 일반 API·워커 설정은 이미 `LLM_API_KEY_FILE`, `IMAGE_API_KEY_FILE`,
  `OPENAI_TTS_API_KEY_FILE`을 지원한다. 사용할 호스트에 **이미 존재하는** 소유자 전용
  정규 파일을 가리킨다. 원문 변수와 파일 입력을 동시에 지정하면 거부한다.
  세 역할이 같은 파일을 참조하면 한 번 읽어 일관된 값을 사용한다.
- 서버의 파일 경로를 Mac에서도 사용할 수 있다고 가정하지 않는다. 이 정리를 위해
  서버 키를 내려받거나 새 평문 파일·dotenv 사본을 만들지 않는다. 파일 입력을
  사용할 수 없으면 실 제공자 설정은 키 미구성으로 남기며 자동으로 mock으로 바꾸지
  않는다. 관련 코드와 시험은 `apps/api/src/core/config.py` 및
  `apps/api/tests/test_provider_key_file.py`에 있다.
- 기존 키체인 전송 도구는 이미 저장된 운영 항목을 메모리에서 읽어 SSH의 stdin으로
  전달한다. 로컬 정리에 전송이나 키체인 갱신은 필요하지 않다.
  `provider_key_transfer.py`와 `update_openai_keychain_after_probe.py`를 정리 명령처럼
  실행하지 않는다. 후자는 실제 키체인 쓰기와 제공자 확인을 수행할 수 있다.
- `run_live_book_acceptance.py`, `run_live_photo_acceptance.py`는 명시한 dotenv의
  원문 자격 입력을 요구하는 이전 격리 시험 도구다. `run_realtime_narration_review.py`의
  실제 합성도 명시한 `OPENAI_API_KEY`를 요구한다. 이 도구들이 파일 참조나 키체인을
  자동으로 읽는다고 안내하지 않는다. 이번 정리에서는 실행하지 않으며, 기존 키 파일을
  다시 채우거나 새 운영 키를 복사해 시험을 반복하지 않는다.

확인 당시 저장소 GitHub secret 목록은 비어 있었고 추적된 CI의 제공자 설정은 mock이었다.
이는 다른 저장소·조직·외부 실행 환경 전체를 검사했다는 뜻이 아니다. 키 누락 시
실 요청을 막는 동작과 Settings 비밀값 비표시, 비공개 파일 입력은 기존 집중 검사로
확인하며 실제 유료 모델 호출을 하지 않는다.

사고 범위와 과거 검토 한계는
[낭독 작업의 보안 후속](NARRATION_STYLES_2026-11-02.md#테스트-출력에-노출된-자격-정보),
[출시 보안 검토](RELEASE_SECURITY_REVIEW_2026-11-11.md)를 함께 따른다.
