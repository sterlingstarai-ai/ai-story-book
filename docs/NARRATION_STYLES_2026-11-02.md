# 낭독 스타일 검증 및 보안 후속 — 2026-11-02

2026-11-03 로컬 보완: 새 음성 합성 시 본문 맨 앞의 명백한 `페이지 1`·`Page 1`·`ページ 1` 단독 줄이나 `장면 2의 이야기입니다.` 안내를 제외한다. 인용된 대사와 `페이지 1의 비밀`처럼 이야기의 일부인 문구는 유지하며, 안내만 남은 빈 본문에는 공급자 호출을 하지 않는다. 집중 시험은 모의 공급자로 통과했다. 이미 생성·캐시된 오디오는 자동으로 교체하지 않았고, 이 변경은 아직 운영 배포 또는 실기기 검증되지 않았다.

기존 낭독 및 목소리별 캐시를 보존하면서 자연스러운 이야기, 애니메이션 느낌, 잠자리 세 스타일을 OpenAI mini TTS 명시적 지시로 분리했다. 애니메이션은 하나의 음색으로 대사 억양을 달리하도록 요청하는 것이며 독립 성우를 자동 배정하거나 표현 품질을 보증하지 않는다. 저장 값은 legacy/natural/animated/bedtime이며, 과거 녹음은 legacy로 유지한다. 스타일과 목소리별 캐시와 중복 합성 방지 잠금을 분리한다. 새 스타일 녹음이 존재할 때 데이터 손실을 피하기 위해 DB downgrade를 차단한다. 변경은 운영에 적용되지 않았다.

동일한 가상 한국어 대본·동일 voice·1.0 속도로 실제 OpenAI TTS 세 요청이 성공했고 세 음성을 테스트용 미리듣기 자산으로 보존했다. 제공자 비용은 확인하지 않았고 품질에 대한 사람의 청취 평가는 별도다. `gpt-4o-mini-tts`는 OpenAI가 2027-01-06 종료를 공지했으므로 장기 운영 전 제공자·모델 전환 및 검증이 필요하다.

## 테스트 출력에 노출된 자격 정보

새 테스트 실패에서 Settings 객체의 repr에 로컬 .env의 LLM_API_KEY와 PHOTO_ANALYSIS_API_KEY 값이 출력됐다. 결과가 중간에서 잘려 다른 설정 비밀이 출력되었는지는 확인할 수 없다. 같은 로컬 환경의 IMAGE_API_KEY, ELEVENLABS_API_KEY, S3 자격 등도 영향 범위 확인 대상이다. 에이전트가 별도 파일 로그를 생성하지는 않았으며 기존 기록은 삭제하지 않았다. LLM_API_KEY는 위 샘플 생성에 사용됐다.

사용자는 키 교체를 마지막 보안 점검으로 보류했다. **교체 전 노출된 키로 추가 외부 호출을 하지 않는다.** 테스트의 로컬 .env 자동 로딩을 격리하고 Settings repr/str에서 모든 필드 값을 숨기는 보완을 추가했지만 이는 이미 노출된 비밀의 폐기·교체를 대체하지 않는다. 사용자의 지시에 따라 최종 보안 점검 시 실제 키 상태와 영향 범위를 확인하고 키 교체·기존 배포 설정의 안전한 갱신·폐기를 수행한다.

## Realtime 전환 시제품

`TTS_PROVIDER=openai_realtime`을 명시적으로 선택할 때만 새 WebSocket 어댑터를 사용한다. 기존 제공자 기본값은 바꾸지 않았다. 제공자의 24kHz PCM 결과를 WAV로 감싸 해당 Content-Type과 파일 확장자로 저장하고, 응답 완료·오디오 크기·제한 시간 및 원문과 전사의 NFC/공백 정규화 후 일치를 요구한다. 구두점만 달라도 거절될 수 있는 엄격한 실패 정책이다. 음성 캐시는 provider까지 분리하므로 구식 제공자 결과가 Realtime 결과로 오인되지 않는다. 실패·취소 시 남는 동시 요청 잠금과 재시도 제한을 유지한다.

외부 실제 Realtime 요청은 하지 않았다. 모의 서버 이벤트·전사 불일치·응답 실패·빈 출력·타임아웃, WAV 생성, 사설 MinIO 서명 URL 다운로드와 미디어 형식 확인을 통과했지만 실제 응답 스키마, 한국어 발화 일치·감정 품질, iOS WAV 재생, 요금과 제공자 가용성은 검증 전이다. 지원 capability는 명시적으로 이 provider를 설정했을 때만 노출되며, 공개 운영 사용 승인이 아니다. 기존 데이터에 대한 PostgreSQL 마이그레이션 시험에서 기존 행은 legacy/openai로 보존되었고 새 provider 녹음이 있을 때 다운그레이드는 거부됐다.

## 2026-11-02 구연동화 후속

사용자는 기존 세 샘플의 차이를 느끼기 어렵다고 평가했고 유아용 구연동화의 대사·감정 표현을 더 강하게 요청했다. 신규 합성 지시를 보강했으나 기존 OpenAI 번들 미리듣기 음원은 이전 지시로 만든 파일이라 개선된 지시의 품질을 보여주지 않는다. 앱에 이를 개선된 샘플로 오인해 반영하지 않는다.

대안 비교로 기존 Google Cloud 프로젝트에 Cloud Text-to-Speech와 Vertex AI API를 활성화하고 Gemini 2.5 Flash TTS에서 동일 가상 한국어 문장으로 세 스타일을 생성했다. 사전 권한 전파 403 세 번과 성공 세 번, 총 여섯 요청이며 청구액은 확인되지 않았다. [시험 결과](acceptance/2026-11-02-google-tts-styles-final-rzi5cjkw/result.json). 음성은 비교용이며 사람의 청취 평가, 본문 완전 일치, 앱 음성 제공자로서의 통합·운영은 검증하지 않았다. Google API는 활성화 상태지만 운영 앱 설정은 바꾸지 않았다.

## Google Gemini TTS 선택적 연결

2026-11-03 로컬 후속: `AUDIO_NARRATION_ONLY_ENABLED=true`를 명시하고 오디오를 활성화하면 STT가 미구성이어도 TTS 설정과 요청 한도가 유효한 경우에만 낭독을 제공한다. 기본값은 false로 기존 배포의 TTS+STT 조건을 유지한다. 구 클라이언트의 `audio_supported`는 계속 두 기능이 모두 가능한 경우에만 true이며, 새 `narration_supported`는 낭독만 표시한다. 발음 API는 기존 STT 게이트를 유지한다. 관련 API 집중 검사 33개 및 환경·OpenAPI 계약 검사를 통과했으며, 운영에 설정하거나 배포하지 않았다. 준비되지 않은 STT의 안전한 우회를 위한 구성이며 Google ADC/IAM, 예산 및 실제 운영 검증을 대신하지 않는다.

추가 로컬 수정: 낭독 전용일 때 미구성 STT가 provider 관측 목록에 포함돼 readiness가 무기한 미확인으로 남는 결함을 고쳤다. 실제 구성된 STT와 낭독 제공자의 미확인·실패는 계속 readiness를 차단한다. 또한 실험용 Realtime TTS는 실제 모델·키에 해당하는 관측 식별자를 사용하고, 오디오·전사가 검증된 성공 후에만 성공 관측을 기록한다. 모의 집중 검사 35개 및 Ruff가 통과했으며 실제 공급자 호출이나 운영 적용은 하지 않았다.

낭독 배포 어댑터는 낭독 전용 여부를 명시적 boolean으로 받아 API와 worker의 설정을 각각 고정하고 서로 다르거나 예상과 다르면 거부한다. 기본값 false와 무관한 환경변수 변경 차단을 유지한다. 합성 검사 27개가 통과했으나 기존 운영 preflight의 복원·쓰기 펜스·재부팅 미검증 차단은 그대로다. v6 이미지의 코드와 수정된 호스트 어댑터의 해시는 [v7 매니페스트](../infra/gcp-pilot/narration-receipt-candidate-v7-manifest.json)와 [대조 기록](acceptance/privacy-final-synthetic-2026-11-03/candidate-v7-host-attestation.json)에 고정했다. 운영 적용 또는 복원 승인은 아니다.

이후 체크포인트 및 그림 검수·수정 변경을 포함한 [v8 로컬 후보](acceptance/privacy-final-synthetic-2026-11-03/candidate-v8-build.json)를 별도로 만들었다. 이미지 소스는 빌드 시점 작업본과 일치하고, 그림 관련 두 파일만 명시적 allowlist에 추가했다. 후보 빌더 집중 검사 7개 통과. 기준 이미지는 여전히 운영 이미지와 동일하다고 확인되지 않았으며 배포는 승인되지 않았다.

개인정보 게시 재시도 공정성을 위한 migration `4c2d8f71b906`을 포함한 [v9 로컬 이미지](acceptance/privacy-final-synthetic-2026-11-03/candidate-v9-build.json)를 빌드하고, 해당 head까지 배포 migration 및 transaction fence 체인을 갱신했다. 이 호스트 스크립트는 [v10 매니페스트](../infra/gcp-pilot/narration-receipt-candidate-v10-manifest.json)에 별도 고정했다. 격리 PostgreSQL의 [커밋과 SIGKILL 롤백](acceptance/privacy-final-synthetic-2026-11-03/candidate-v10-migration-rehearsal.json), 집중 검사 15개와 Ruff가 통과했다. 실제 운영 DB·미디어 및 재부팅은 검증하지 않았고 운영 배포도 여전히 차단된다.

개인정보 기록 설정 누락 차단과 intent·commit 저장 후 읽기 확인을 반영해 [v11 로컬 후보](acceptance/privacy-final-synthetic-2026-11-03/candidate-v11-build.json)를 별도로 만들었다. API·worker 각각 네트워크가 차단된 읽기 전용 컨테이너에서 단일 migration head `4c2d8f71b906`을 확인했다. 이미지의 기준 기반은 실제 운영 이미지와 다르며, 생산 배포나 최신 개인정보 기록의 독립적 완전성은 확인되지 않았다.

사용자는 위 세 샘플을 선택했다. `TTS_PROVIDER=google_gemini`와 `GOOGLE_GEMINI_TTS_PROJECT`를 명시할 경우에만 Gemini 2.5 Flash TTS 어댑터를 선택하고 Google Application Default Credentials를 사용한다. warm/default는 Kore, deep은 Puck이며 기존 제공자와 스타일별 캐시는 분리한다. 모델의 무료 할당량은 없고 새 음성 생성은 실제 비용이 들 수 있다. 기존 음성, 서비스 설정, 데이터베이스 및 운영 배포는 수정하지 않았다. Google Cloud API가 활성화되어도 서비스 계정의 권한·ADC·요금 제한과 실제 준비 상태를 별도로 확인해야 한다.

동화 맥락과 무관하게 원래 표본의 놀람과 마지막 미소를 강제하지 않도록 구연 지시를 일반화했으므로 실제 책의 표현이 샘플과 같다는 보장은 없다. 부모 동의·소유권, 스타일·음색 캐시 분리, 잘못된 오디오 거부 등을 모의 테스트했고, 임시 SDK 인증을 주입한 가상 한 문장으로 실제 어댑터의 Puck 음성 1회 HTTP 200 및 MP3 재생 길이 12.192초를 확인했다. [결과](acceptance/2026-11-02-gemini-adapter-live/result.json). 실제 운영 ADC/IAM, 이용자 기기 전체 여정, 생성 음성의 본문 일치 및 품질은 별도 검증이 필요하다.
