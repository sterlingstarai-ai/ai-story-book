# 생성 글 문자·언어 검사

`src/services/story_integrity.py`는 LLM의 스토리 JSON 스키마 검사 직후, 캐릭터 시트·이미지 프롬프트·이미지 생성 전에 실행된다. 2026-09-06 실제 합성 표본에서 나온 깨진 문자와 한국어 본문의 외국어 혼입을 재발 방지 대상으로 삼았다.

- StoryDraft의 모든 문자열에서 대체 문자 U+FFFD, 고립 서로게이트, Unicode 비문자 및 허용하지 않은 제어문자를 거절한다. 일반 줄바꿈·탭과 이름·이모지에 쓰이는 ZWNJ/ZWJ는 허용한다. 고립 서로게이트는 앞단 Pydantic 스키마 검사에서도 거절된다.
- 요청 언어와 StoryDraft의 language가 다르면 거절한다.
- 한국어 제목·표지 문구·교훈·페이지 본문·학습 포인트·다음 이야기 훅에 불쑥 들어온 Latin 문자 토큰을 거절한다. 사용자 주제·주인공 이름·직접 입력하거나 선택한 저장 캐릭터 이름의 표기는 허용한다. 모델이 새로 지은 이름을 자체 허용 목록으로 사용하지 않는다. 장면·카메라 등 내부 이미지 지시 필드는 이 Latin 제한 대상에서 제외한다.
- 별도 영어 학습 옵션은 현재 BookSpec에 없다. 주제에서 영어 학습 의도가 명시된 경우에만 따옴표로 구분된 순수 Latin 문장을 학습 인용문으로 허용한다. 한국어 문장 중간의 외국어 혼입은 인용문 안에서도 거절한다.
- 별도 LearningAssets의 번역·어휘·질문·퀴즈·부모 안내, 페이지 재작성과 연령별 다시쓰기에는 Unicode 검사만 적용한다. 해당 출력의 영어와 다른 지원 언어를 막지 않는다.

실패는 `LLM_JSON_INVALID`로 전달해 기존 스토리 단계의 재시도 2회를 재사용한다. 연속 3회 불합격이면 실패 상태로 끝나며 초안 저장·캐릭터 시트·이미지 단계로 진행하지 않는다. 원문을 자동 삭제·치환·정규화하여 통과시키지 않는다. 허용 이름 비교에만 정규화와 대소문자 비교를 사용하고 반환 문자열은 유지한다. 진단에는 소유한 DTO 필드 경로와 고정 규칙명만 기록하며, 생성 원문·이름·토큰·위치 정보는 기록하지 않는다.

## 검증과 한계

`tests/test_story_integrity.py`의 18건은 중첩 필드와 로그 비밀값 차단, 제공된 영문 이름·악센트·이모지 보존, 영어 학습 예외, 다른 언어와 번역, 저장 캐릭터 이름 전달, 기존 재시도 회복 및 반복 실패 시 이미지 호출 0회를 검증한다. 관련 schema·orchestrator·chaos·learning·golden 테스트도 함께 확인한다.

저장된 합성 표본 `age-3-5-case-2/book.json`의 제목과 각 페이지 본문을 유효한 시험 StoryDraft에 넣어 읽기 전용 재검사했다. 1쪽은 `invalid_unicode`, 4쪽은 `unexpected_latin_in_korean_narrative`로 거절되고 2·3쪽은 통과했다. 원본을 수정하거나 공급자·이미지 호출을 추가하지 않았다. 증거는 `docs/acceptance/2026-09-06-release-ops/story-integrity-replay.json`에 있다. 저장 책의 전체 파이프라인을 다시 실행한 결과와 구분한다.

이 검사는 의미 품질 평가가 아니다. 영어 학습 인용문이 실제로 영어인지, 문장이 자연스러운지, 다른 문자권의 혼입인지, 그림이 본문과 일치하는지, 장면의 인과관계가 맞는지는 별도 실생성 검토가 필요하다. 이전 저장 책을 자동 수정하지 않는다.

## StoryDraft·ImagePrompts 네이티브 스키마

스토리와 이미지 지시 생성 호출이 각각 `response_schema`를 명시한다. `claude-sonnet-5`·`claude-opus-5`는 `output_config.format`, 현재 확인된 `gpt-6-astra`·`gpt-5.6-sol`·`gpt-5.6`는 Responses의 `text.format`에 네이티브 JSON Schema를 전달한다. 날짜 접미사나 유사 모델명으로 지원을 추정하지 않는다. 다른 모델·mock·Gemini와 모더레이션·캐릭터 생성의 요청 형식은 유지한다. 이 변경은 이미지 지시를 작성하는 LLM에만 적용되며, 실제 이미지 공급자 요청 본문은 바꾸지 않는다.

스키마는 사용자 이름·주제·사진과 무관하게 각각 `StoryDraft.model_json_schema()`와 `ImagePrompts.model_json_schema()`에서 만들며 원본을 변경하지 않는다. OpenAI 형식 이름은 이 두 DTO에 대응하는 고정값 `story_draft`·`image_prompts`만 허용한다. Anthropic 전송 사본에서는 지원하지 않는 문자열 길이·숫자 범위·배열 상한 및 1보다 큰 배열 하한을 제거한다. OpenAI strict 사본은 모든 필드의 존재를 필수로 하고 모든 `default` 주석을 제거하지만, 기존 선택 필드의 null 허용은 유지한다. 이미지 지시의 `guidance_notes`·`base_image_url`·`mask_url`도 null을 허용하며, 원본 DTO의 null 기본값과 `aspect_ratio` 기본값은 그대로다. 객체의 추가 필드는 허용하지 않는다. [Anthropic 공식 계약](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [OpenAI 공식 계약](https://developers.openai.com/api/docs/guides/structured-outputs)을 따른다.

이미지 지시 시스템 프롬프트에도 원래 DTO의 제한인 `positive_prompt` 10–1200자, `negative_prompt` 10–600자, `guidance_notes` 최대 200자를 명시한다. 인물 특징·장면·안전 지시를 보존하면서 중복을 없애고 완결된 문장으로 간결하게 작성하도록 요구한다. 신규 책의 `base_image_url`·`mask_url`은 null로 지정한다. 반환된 원문을 잘라 통과시키지 않으며, 토큰 예산도 유지한다. 8쪽 책의 표지 포함 9개 지시는 기존 5400토큰, OpenAI는 추론 여유를 포함한 10800토큰이다.

이는 필수 키 누락과 길이 초과 등을 줄이기 위한 전송 계약이다. 원래 DTO의 전체 길이·범위 검사와 문자·언어·안전 검사는 계속 적용한다. 공급자 거절·출력 잘림·잘못된 스키마 요청을 정상 응답으로 바꾸지 않고, 일반 JSON으로 조용히 되돌리거나 새 재시도 루프를 추가하지 않는다. 네이티브 스키마 적용 전 모델 비교는 기존 기준선으로 보존하고, 이후 실생성 품질은 별도 표본으로 평가한다.

`tests/test_story_structured_output.py`와 `tests/test_image_prompt_structured_output.py`는 요청 형식·정확한 모델 범위·스키마 내 사용자 정보 배제·후검증·폴백 부재를 검증한다. 이미지 지시 검사는 길이 경계, 거절·출력 잘림, 선택 필드의 null, 8쪽 토큰 예산과 기존 mock·Gemini 호출 경계도 포함한다. 관련 OpenAI·Anthropic 호환성, 생성 개선, 비공개 진단 검사까지 6개 모듈에서 184건이 통과했다. 외부 공급자 호출을 대체한 검사이므로 실제 책 생성의 성공이나 이미지 품질을 증명하지는 않는다.
