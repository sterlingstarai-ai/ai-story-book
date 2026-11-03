# Audio implementation and verification — 2026-09-08

Follow-up, 2026-09-08: the owner explicitly approved adding Text-to-speech Request to the existing project key. That one permission was saved and re-opened in the platform UI to confirm persistence. One generic Korean sentence through the actual `OpenAITTSProvider` returned HTTP 200 and an 88,704-byte MP3 (5.544 seconds, mono, 24 kHz). No raw child data, STT request, new key, top-up, or persistent application-setting change was involved. The earlier key-permission blocker below is resolved; full app narration and STT verification remain separate. Private evidence: `docs/acceptance/2026-09-08-tts-permission/result.json`.

Implemented:

- The viewer clears its loading indicator when playback starts. `just_audio.play()` is a playback-lifetime future, so awaiting it previously prevented the normal pause control from becoming available.
- Pause/resume keeps the current position. Completion replays from the beginning. A delayed URL request cannot start an old page after a page/language change or viewer disposal. Repeated taps share the active load.
- Narration files use the existing bounded, erasable media cache. The cache identity includes book/page/language/text, so a refreshed signed URL does not prevent offline playback and a changed story text does not reuse stale speech. The most recent listening position is stored with reading progress and removed by the existing erasure workflow.
- Batch narration reuses existing audio. An English original is no longer synthesized into the Korean audio slot; untranslated languages are rejected before a provider request. Google STT combines all recognition segments. Scoring preserves Japanese, Chinese, and accented Latin characters.
- Narration files use unique object keys with a durable cleanup guard committed before upload. An atomic conditional update adopts only an empty language slot whose current text still matches the synthesized source. Concurrent losers retain their cleanup guards and reuse the winner; changed/deleted pages cannot adopt stale speech. Workers re-read the current book/page and active parental consent rather than trusting queued text or earlier authorization.
- Family-voice sample collection is separate from narration: `voice_profiles_supported` is false for this release. New samples/profiles, replacements, and reactivation return `VOICE_PROFILE_NOT_SUPPORTED` (409), even when narration is enabled. Existing profile listing, consent withdrawal, and deletion remain available. Mobile settings and profile actions use this separate capability.
- Audio uploads and narration require server-side parental consent. The upload read is capped at the limit plus one byte. STT credentials must belong to the selected provider; an unrelated LLM key does not count as an OpenAI STT configuration.
- TTS/STT responses record only numeric usage and sanitized availability observations. Readiness can include the enabled audio providers without letting a speech-only outage block book generation. Key presence/model-list access alone is insufficient evidence of speech permission.

Verification recorded by the audio task:

- Eight new deterministic playback/cache tests passed. Eight existing viewer audio/layout gate tests passed.
- The focused audio backend run passed all 25 tests covering the audio completion suite, existing audio routes, and text-regeneration audio cleanup. Database regressions cover revoked consent before/during synthesis, old queue text, edits during synthesis, and two independently uploaded files racing to publish one page slot. The root task runs the consolidated full suite, including the later family-voice collection restriction and preserved legacy-erasure regressions. An earlier 78-pass focused run exposed one IAP-plan expectation mismatch, handed to the payments task.
- Live OpenAI model lookup returned HTTP 200, while speech requests with both distinct current project keys returned HTTP 401, `missing_scope`. No audio was produced, no successful speech generation was billed, and no recharge was performed. Private backup files contained the same current keys; one obsolete provider key was rejected as invalid.
- The platform UI independently showed the existing runtime key's Text-to-speech permission set to `None`. Saving the single `Audio Request` permission addition was rejected by automatic approval review; the uncommitted edit was canceled. This is an account permission blocker, not an implementation success or a quota failure.
- `integration_test/native_audio_test.dart` passed on a dedicated iPhone 16e simulator running iOS 26.2 (1/1). The generated, disposable silent WAV exercised the real native plugin: load with saved position, playback advancement, pause, resume without a second load, and stop. The test fixture and dedicated simulator were removed afterward. This does not establish voice quality or actual STT accuracy.
- The Korean privacy review source and matching static HTML now describe actual TTS/STT inputs, generated-audio storage/cache/deletion, and transcription/evaluation records. Pronunciation practice currently uploads a user-selected audio file; it does not record through the microphone. The English page continues to point to the Korean review document without claiming an approved translation or provider-processing approval.

The feature remains disabled pending deployment credential wiring and the remaining STT/application checks. The generic TTS adapter probe now passes as recorded above. Real child voice uploads and any required processing-policy approval remain distinct from that probe.

Sources: [OpenAI speech API](https://developers.openai.com/api/reference/cli/resources/audio/subresources/speech/methods/create), [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text). No custom child voice cloning is implemented.

## 2026-10-22 실제 공급자와 iOS 재생 재검증

기존 로컬 OpenAI 글 생성 키를 단일 시험 프로세스에서만 낭독 어댑터에 연결해 일반 한국어 문장1회를 요청했다. HTTP200, 112,128바이트 MP3, 7.008초/24kHz/mono이며 MP3→PCM 디코딩도 통과했다. 새 키·권한 변경·충전·구독·영구 환경 설정 변경은 없고, 기존 API 사용의 정확한 청구액은 미확인이다. 아동 사진/음성/개인정보를 전송하지 않았다.

해당 실제 MP3를 전용 iPhone17 / iOS27 시뮬레이터에서 기존 `PageAudioPlayback`/`just_audio`로 로드·1초 이동·재생·일시정지·위치 유지 재개·정지했다. `native_audio_test.dart` 1개 PASS(exit0). 테스트에 선택적인 `NATIVE_AUDIO_SAMPLE_BASE64` 입력만 추가했으며 기본 무음 WAV/외부 API 없는 시험은 유지한다. 시험용 시뮬레이터는 삭제했다.

**아직 앱 전체 책 낭독·운영 서버 연결·스토어 출시를 검증한 것은 아니다.** 저장된 음성 플래그는 off, TTS 공급자 설정은 기존값을 유지한다. 다음은 격리된 합성 책에서 서버 생성→비공개 저장소→서명 URL→실제 viewer 페이지 전환까지 연결 검증이다. 운영 환경·공개 정책 차단은 별도로 유지하며, 검증 없이 기능을 켜거나 제출하지 않는다.

증거: `docs/acceptance/2026-10-22-tts-recheck/{result.json,generic-korean.mp3,native-audio.log,native-exit.txt}`. 테스트 입력/디코딩 파일은 Git 제외 경로에 보관한다.

## 2026-10-22 18:40 KST 서버→비공개 저장소 낭독 검증

별도 임시 PostgreSQL/Redis/Celery/MinIO/API에서 가상 부모 동의와 시험용4쪽 책을 만들고, 실제 기존 OpenAI 키로 네 페이지의 낭독을 생성했다. 글·그림은 mock이며 실제 AI 책 품질 검증이 아니다. TTS만 실제 공급자 HTTP200 4회, STT 호출0회다. 이 시험은 기존 runtime 도구의 소유 자원 생성/정리 코드를 재사용한 비공개 실험 driver로 수행했으며 공통 mock 게이트나 제품 설정은 변경하지 않았다.

35개 확인 항목 통과: 네 페이지 각각 음성 생성/DB 반영, S3 서명 URL 다운로드, 익명 저장소 접근 차단, 다른 계정의 음성 접근 차단, 재조회 시 같은 저장 객체 재사용. 네 MP3 모두 PCM 디코딩 통과. 재조회 포함 공급자 성공 기록은 총4회라 페이지 캐시 조회가 추가 음성을 생성하지 않은 것도 확인했다. 마지막 동의 철회 후 음성 요청은 차단됐다. 전용 컨테이너/볼륨/프로세스/소스 복사본 정리 완료.

기존 키의 제한적 사용이며 새 충전·구독·권한 변경 없음. 실제 청구액은 미확인. 아동 자료·운영 DB를 사용하지 않았다. **iOS 전체 viewer의 페이지 전환/서명 URL 만료 후 재조회는 아직 미검증이며 스토어 제출0**이다. 다음은 이 서버 여정을 iOS viewer와 연결하되, 이미 생성한 일반 시험 음성을 재사용해 불필요한 추가 과금을 줄이는 것이다.

증거: `docs/acceptance/2026-10-22-narration-runtime/{run.py,result.json,run.log,api.log,cleanup.log,page-1.mp3,page-2.mp3,page-3.mp3,page-4.mp3}`. 사적 로그와 음성은 Git 제외 보관.

## 2026-10-22 iOS 전체 읽기 화면과 격리 서버 연결

새 opt-in `integration_test/live_narration_viewer_test.dart`를 iPhone17/iOS27 전용 시뮬레이터에서 실행해 1개 PASS(exit0). 실제 `ApiClient`와 `ViewerScreen`을 격리 PostgreSQL/Redis/Celery/MinIO/API에 연결했다. 책/기능 조회를 대역으로 바꾸지 않았으며 네 페이지 각각 이동→재생→일시정지→재개와 다음 페이지 이동 시 이전 낭독 중단, 화면 종료 시 예외 없음까지 확인했다.

이전 실제 TTS 시험에서 생성한 일반 음성4개를 전용 비공개 저장소에 넣어 재사용했다. 글·그림은 합성이며 새 공급자 호출0회, API 사용기록0개 확인. 운영 서버/실제 사용자 자료는 사용하지 않았다. API 사전 확인33개도 통과. 최초 실행은 시험 선택자가 실제 Semantics/Icon 버튼을 Tooltip으로 찾은 오류로 실패했으며 선택자만 수정한 후 통과했다. 제품 결함으로 분류하지 않는다.

전용 시뮬레이터·서버·DB·볼륨 정리 completed, 일반 main.dart 무서명 debug 앱 재빌드 성공. **실제 신규 글·그림 생성 품질, 서명 URL 만료 후 viewer 재조회, 공개 운영 API/정책 및 물리 기기 검증은 별도 미완료**다. 따라서 스토어 제출0. 증거: `docs/acceptance/2026-10-22-viewer-runtime/{result.json,viewer.log,viewer-first-selector-failure.log,cleanup.log,main-build.log}`.

## 2026-10-23 06:44 KST 만료된 낭독 URL 복구 검증

격리 비공개 MinIO에서 실제 1초 서명 URL 네 개를 만들고 만료 후 모두 HTTP403임을 확인했다. opt-in iOS 시험은 실제 API에서 받은 책의 음성 URL만 이 만료 URL로 바꾸고 실제 ViewerScreen을 실행했다. 네 페이지 각각 서버에서 새 URL을 조회한 순서가 [1,2,3,4]임을 단언하고 재생·일시정지·재개·페이지 이동 및 종료 시험 1개 PASS(exit0). 기존 복구 코드가 동작해 제품 코드 수정은 없으며 시험 입력/검증만 확장했다.

이전 일반 시험 음성을 재사용했고 새 공급자 사용 로그0개다. 합성 글/그림과 격리 서버를 사용했으므로 실제 전권 생성 품질·운영 서버·물리 기기 증거로 확대하지 않는다. 소유 서버/DB/볼륨/시뮬레이터 정리 완료, 일반 main.dart 무서명 debug 재빌드 PASS. 스토어 제출0. 증거: `docs/acceptance/2026-10-23-expired-narration/{result.json,viewer.log,run.py,cleanup.log,main-build.log}`.

다음은 실제 전권 글·그림 생성/검수 경로 및 공개 운영 API/정책 준비다. 이미 통과한 낭독 시험을 반복하는 것으로 이를 대체하지 않는다.

## 2026-10-23 실제 생성 동화의 iOS 전 페이지 끝까지 낭독

현재 실제 생성·검수한 「하루와 반짝반짝 작은 숲」 본문4쪽/그림5장을 새 격리 서버에 복원했다. 원본 본문/그림 일치 확인 후 실제 TTS4회로 네 파일(총54.84초)을 생성해 디코딩 PASS. 실제 iOS27 ViewerScreen에서 각 페이지 재생·일시정지·재개·자연종료와 화면종료까지 opt-in 시험1개 PASS. 이번 입력만 wait_for_completion=true이며 기존 페이지전환 중단 시험은 유지. 서버38항목 PASS, 재조회 추가합성0. 청각적 발음 정밀 평가·운영 서버·물리기기는 별도 미검증.

소유 서버/DB/볼륨/시뮬레이터 정리completed, 일반 main.dart 무서명 debug 재빌드PASS. 영구 키/음성 플래그변경0, 새 구독/충전0, 제출0. 현재 실제 생성 증거는 `2026-10-23-current-live-book-v3`, 이번 전체 낭독 증거는 `docs/acceptance/2026-10-23-real-book-narration/{REPORT.md,result.json,viewer.log,audio-decode.json}`. 다음은 공개 운영API/정책 차단 해소이며 동일 낭독 QA 반복 불필요.
