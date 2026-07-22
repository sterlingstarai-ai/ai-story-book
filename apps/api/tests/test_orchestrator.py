"""
Orchestrator Unit Tests
오케스트레이터 핵심 로직 단위 테스트

- run_step: 재시도, 타임아웃, 에러 전파
- moderate_output: 금지 키워드 필터링
- generate_all_images: 실패 임계값
- generate_image_with_retry: 재시도/백오프
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from src.core.errors import StoryBookError, ErrorCode, TransientError


# ==================== run_step Tests ====================


class TestRunStep:
    """run_step 재시도/타임아웃/에러 전파 테스트"""

    @pytest.mark.asyncio
    async def test_run_step_success(self):
        """정상 실행 시 결과 반환"""
        from src.services.orchestrator import run_step

        result_fn = AsyncMock(return_value="success")

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            result = await run_step(
                job_id="test-job",
                step_name="test-step",
                progress=50,
                fn=result_fn,
                retries=0,
                timeout_sec=5,
            )

        assert result == "success"
        result_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_step_retry_on_transient_error(self):
        """TransientError 발생 시 재시도"""
        from src.services.orchestrator import run_step

        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("temporary failure")
            return "recovered"

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await run_step(
                    job_id="test-job",
                    step_name="test-step",
                    progress=50,
                    fn=flaky_fn,
                    retries=2,
                    timeout_sec=5,
                    backoff=[0, 0],
                )

        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_run_step_retry_exhausted(self):
        """재시도 횟수 소진 시 StoryBookError 발생"""
        from src.services.orchestrator import run_step

        fail_fn = AsyncMock(side_effect=TransientError("always fails"))

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(StoryBookError) as exc_info:
                    await run_step(
                        job_id="test-job",
                        step_name="failing-step",
                        progress=50,
                        fn=fail_fn,
                        retries=2,
                        timeout_sec=5,
                        backoff=[0, 0],
                    )

        assert "failing-step" in str(exc_info.value)
        assert fail_fn.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_run_step_storybook_error_no_retry(self):
        """StoryBookError는 재시도 없이 즉시 전파"""
        from src.services.orchestrator import run_step

        safety_error = StoryBookError(
            code=ErrorCode.SAFETY_INPUT, message="unsafe content"
        )
        fail_fn = AsyncMock(side_effect=safety_error)

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with pytest.raises(StoryBookError) as exc_info:
                await run_step(
                    job_id="test-job",
                    step_name="safety-check",
                    progress=50,
                    fn=fail_fn,
                    retries=3,  # 재시도 3회 설정했지만
                    timeout_sec=5,
                )

        assert exc_info.value.code == ErrorCode.SAFETY_INPUT
        fail_fn.assert_called_once()  # 1번만 호출됨 (즉시 중단)

    @pytest.mark.asyncio
    async def test_run_step_retries_retryable_llm_error(self):
        """재시도 가능한 LLMError(LLM_JSON_INVALID)는 재시도한다(H9)."""
        from src.services.orchestrator import run_step

        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise StoryBookError(
                    code=ErrorCode.LLM_JSON_INVALID, message="bad json"
                )
            return "recovered"

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await run_step(
                    job_id="test-job", step_name="story", progress=20,
                    fn=flaky_fn, retries=2, timeout_sec=5, backoff=[0, 0],
                )

        assert result == "recovered"
        assert call_count == 2  # 재시도됨(수정 전엔 1회 후 즉시 raise)

    @pytest.mark.asyncio
    async def test_run_step_preserves_final_error_code(self):
        """소진 후 raise되는 코드가 UNKNOWN이 아니라 원 코드(LLM_TIMEOUT)로 보존된다(H9)."""
        from src.services.orchestrator import run_step

        async def always_timeout():
            raise StoryBookError(code=ErrorCode.LLM_TIMEOUT, message="llm timeout")

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(StoryBookError) as exc_info:
                    await run_step(
                        job_id="test-job", step_name="story", progress=20,
                        fn=always_timeout, retries=2, timeout_sec=5, backoff=[0, 0],
                    )

        assert exc_info.value.code == ErrorCode.LLM_TIMEOUT  # UNKNOWN 아님

    @pytest.mark.asyncio
    async def test_run_step_timeout(self):
        """타임아웃 발생 시 재시도 후 실패"""
        from src.services.orchestrator import run_step

        async def slow_fn():
            await asyncio.sleep(100)  # 매우 느린 함수

        with patch("src.services.orchestrator.update_job_status", new_callable=AsyncMock):
            with pytest.raises(StoryBookError):
                await run_step(
                    job_id="test-job",
                    step_name="slow-step",
                    progress=50,
                    fn=slow_fn,
                    retries=1,
                    timeout_sec=0.01,  # 매우 짧은 타임아웃
                    backoff=[0],
                )


# ==================== moderate_output Tests ====================


class TestModerateOutput:
    """출력 안전성 검사 테스트"""

    def _make_story(self, title="Test Story", page_texts=None, language=None):
        """테스트용 StoryDraft 생성 헬퍼"""
        from src.models.dto import (
            StoryDraft,
            StoryPage,
            StoryCover,
            StoryCharacter,
            StoryContinuity,
            Language,
            TargetAge,
        )

        if page_texts is None:
            page_texts = ["안녕하세요!", "즐거운 하루!"]
        if len(page_texts) < 4:
            page_texts = page_texts + [page_texts[-1]] * (4 - len(page_texts))

        return StoryDraft(
            title=title,
            language=language or Language.ko,
            target_age=TargetAge.a5_7,
            theme="friendship",
            moral="Be kind",
            characters=[
                StoryCharacter(
                    id="char1", name="Tori", role="main", brief="A bunny"
                )
            ],
            cover=StoryCover(
                cover_text=title,
                scene="Meadow",
                mood="happy",
                camera="wide shot",
            ),
            pages=[
                StoryPage(
                    page=i + 1,
                    text=text,
                    scene="Scene",
                    mood="happy",
                    camera="medium shot",
                    characters_present=["Tori"],
                )
                for i, text in enumerate(page_texts)
            ],
            continuity=StoryContinuity(
                character_consistency_notes="Notes",
                style_notes_for_images="Style",
            ),
        )

    @pytest.mark.asyncio
    async def test_safe_content_passes(self):
        """안전한 콘텐츠는 통과"""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            title="토리의 즐거운 하루",
            page_texts=["토리는 친구들과 놀았어요.", "정말 즐거운 하루였어요!"],
        )
        result = await moderate_output(story, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_forbidden_word_in_title(self):
        """제목에 금지 키워드 포함 시 차단"""
        from src.services.orchestrator import moderate_output

        story = self._make_story(title="폭력적인 이야기")
        result = await moderate_output(story, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_forbidden_word_in_page(self):
        """페이지 텍스트에 금지 키워드 포함 시 차단"""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            page_texts=["좋은 아침이에요.", "누군가를 죽이려고 했어요."]
        )
        result = await moderate_output(story, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_english_forbidden_words(self):
        """영어 금지 키워드도 차단"""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            page_texts=["There was a gun on the table.", "Hello world!"]
        )
        result = await moderate_output(story, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_safe_words_with_forbidden_syllables_pass(self):
        """금칙 음절을 포함한 정상 단어는 통과해야 한다 (피자/예술/총총 등 오탐 방지)."""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            title="피자와 피아노",
            page_texts=[
                "오늘은 커피와 피자를 먹었어요.",
                "예술 작품을 만들고 총총 뛰어갔어요.",
                "반죽을 하고 미술 시간에 그림을 그렸어요.",
                "기술 시간에 술래잡기를 했어요.",
            ],
        )
        result = await moderate_output(story, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_specific_korean_forbidden_still_blocked(self):
        """구체적 한국어 금칙 표현은 여전히 차단."""
        from src.services.orchestrator import moderate_output

        for bad in [
            "권총을 들었어요",
            "술을 마시기 시작했어요",
            "마약을 팔았어요",
            "칼로 찔렀어요",
        ]:
            story = self._make_story(page_texts=["좋은 아침이에요.", bad])
            result = await moderate_output(story, {})
            assert result is False, f"차단되어야 함: {bad}"

    @pytest.mark.asyncio
    async def test_english_word_boundary_no_false_positive(self):
        """영어 단어 경계: 'begun'의 'gun'은 오탐하지 않는다."""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            page_texts=["The day had begun happily.", "We had so much fun!"]
        )
        result = await moderate_output(story, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_case_insensitive_check(self):
        """대소문자 구분 없이 검사"""
        from src.services.orchestrator import moderate_output

        story = self._make_story(
            page_texts=["MURDER scene described", "Normal text"]
        )
        result = await moderate_output(story, {})
        assert result is False

    # ---- H24: ko/en 키워드망 밖 언어(ja/zh/es) LLM 출력 모더레이션 폴백 ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lang_code", ["ja", "zh", "es"])
    async def test_uncovered_language_unsafe_blocked_via_llm(
        self, lang_code, monkeypatch
    ):
        """ja/zh/es는 키워드망 밖 → LLM 폴백이 unsafe면 차단(fail-open 금지)."""
        from src.services import llm as llm_module
        from src.services.orchestrator import moderate_output
        from src.models.dto import Language, ModerationResult

        called = {}

        async def fake_output_mod(text, language):
            called["language"] = language
            return ModerationResult(is_safe=False, reasons=["violence"], suggestions=[])

        monkeypatch.setattr(
            llm_module, "call_output_moderation", fake_output_mod, raising=False
        )

        # 키워드망(ko/en)에 안 걸리는 텍스트지만 LLM은 unsafe로 판정.
        story = self._make_story(
            title="物語",
            page_texts=["殺す", "銃"],
            language=Language(lang_code),
        )
        result = await moderate_output(story, {})
        assert result is False
        assert called["language"] == Language(lang_code)

    @pytest.mark.asyncio
    async def test_uncovered_language_safe_passes_via_mock_default(self):
        """ja 정상 동화: mock 프로바이더 출력 모더레이션 기본 safe → 통과(오탐 없음)."""
        from src.services.orchestrator import moderate_output
        from src.models.dto import Language

        story = self._make_story(
            title="ともだち",
            page_texts=["ともだちとあそびました", "たのしいいちにち"],
            language=Language.ja,
        )
        result = await moderate_output(story, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_covered_language_skips_llm_fallback(self, monkeypatch):
        """ko/en은 키워드망으로 충분 → LLM 폴백을 호출하지 않는다(비용·지연)."""
        from src.services import llm as llm_module
        from src.services.orchestrator import moderate_output
        from src.models.dto import Language

        async def boom(text, language):  # 호출되면 실패
            raise AssertionError("covered language must not call LLM fallback")

        monkeypatch.setattr(
            llm_module, "call_output_moderation", boom, raising=False
        )

        story = self._make_story(
            page_texts=["The day had begun happily.", "We had fun!"],
            language=Language.en,
        )
        result = await moderate_output(story, {})
        assert result is True


# ==================== generate_image_with_retry Tests ====================


class TestGenerateImageWithRetry:
    """이미지 생성 재시도 테스트"""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        """첫 시도에서 성공"""
        from src.services.orchestrator import generate_image_with_retry

        mock_prompt = MagicMock()

        with patch("src.services.orchestrator.generate_image", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "https://example.com/image.png"
            with patch("src.services.orchestrator.settings") as mock_settings:
                mock_settings.image_max_retries = 3
                mock_settings.image_timeout = 90

                result = await generate_image_with_retry(mock_prompt, "test-job", 1)

        assert result == "https://example.com/image.png"
        mock_gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_after_failure(self):
        """실패 후 재시도에서 성공"""
        from src.services.orchestrator import generate_image_with_retry

        mock_prompt = MagicMock()
        call_count = 0

        async def flaky_generate(_prompt, reference_image_url=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("API error")
            return "https://example.com/recovered.png"

        with patch("src.services.orchestrator.generate_image", side_effect=flaky_generate):
            with patch("src.services.orchestrator.settings") as mock_settings:
                mock_settings.image_max_retries = 3
                mock_settings.image_timeout = 90
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_image_with_retry(mock_prompt, "test-job", 1)

        assert result == "https://example.com/recovered.png"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """모든 재시도 실패 시 StoryBookError 발생"""
        from src.services.orchestrator import generate_image_with_retry

        mock_prompt = MagicMock()

        with patch("src.services.orchestrator.generate_image", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = RuntimeError("permanent failure")
            with patch("src.services.orchestrator.settings") as mock_settings:
                mock_settings.image_max_retries = 2
                mock_settings.image_timeout = 90
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(StoryBookError) as exc_info:
                        await generate_image_with_retry(mock_prompt, "test-job", 3)

        assert exc_info.value.code == ErrorCode.IMAGE_FAILED
        assert "3" in exc_info.value.message  # page number in message


# ==================== generate_all_images Tests ====================


class TestGenerateAllImages:
    """이미지 전체 생성 로직 테스트"""

    def _make_image_prompts(self, page_count=4):
        """테스트용 ImagePrompts 생성"""
        from src.models.dto import ImagePrompts, ImagePrompt

        return ImagePrompts(
            style="watercolor",
            cover=ImagePrompt(
                page=0,
                positive_prompt="A beautiful cover illustration of a bunny adventure",
                negative_prompt="ugly, blurry, distorted, low quality",
                seed=12345,
            ),
            pages=[
                ImagePrompt(
                    page=i + 1,
                    positive_prompt=f"Page {i + 1} illustration of a bunny adventure scene",
                    negative_prompt="ugly, blurry, distorted, low quality",
                    seed=12345 + i + 1,
                )
                for i in range(page_count)
            ],
        )

    @pytest.mark.asyncio
    async def test_all_images_success(self):
        """모든 이미지 성공"""
        from src.services.orchestrator import generate_all_images

        prompts = self._make_image_prompts(4)

        with patch(
            "src.services.orchestrator.generate_image_with_retry",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = "https://example.com/img.png"
            with patch(
                "src.services.orchestrator.update_job_status", new_callable=AsyncMock
            ):
                urls = await generate_all_images("test-job", prompts, 5)

        assert len(urls) == 5  # cover + 4 pages
        assert 0 in urls  # cover
        for i in range(1, 5):
            assert i in urls

    @pytest.mark.asyncio
    async def test_partial_failure_within_threshold(self):
        """절반 미만 실패 시 계속 진행 (빈 URL 포함)"""
        from src.services.orchestrator import generate_all_images

        prompts = self._make_image_prompts(4)
        call_count = 0

        async def partial_failure(prompt, job_id, page, reference_image_url=None):
            nonlocal call_count
            call_count += 1
            if page == 2:  # 1개만 실패 (4개 중)
                raise RuntimeError("Image gen failed")
            return f"https://example.com/page_{page}.png"

        with patch(
            "src.services.orchestrator.generate_image_with_retry",
            side_effect=partial_failure,
        ):
            with patch(
                "src.services.orchestrator.update_job_status", new_callable=AsyncMock
            ):
                urls = await generate_all_images("test-job", prompts, 5)

        assert urls[0] == "https://example.com/page_0.png"  # cover ok
        assert urls[1] == "https://example.com/page_1.png"  # page 1 ok
        assert urls[2] == ""  # page 2 failed
        assert urls[3] == "https://example.com/page_3.png"  # page 3 ok

    @pytest.mark.asyncio
    async def test_majority_failure_raises_error(self):
        """절반 이상 실패 시 StoryBookError 발생"""
        from src.services.orchestrator import generate_all_images

        prompts = self._make_image_prompts(4)

        async def mostly_fail(prompt, job_id, page, reference_image_url=None):
            if page == 0:  # cover만 성공
                return "https://example.com/cover.png"
            raise RuntimeError("Image gen failed")

        with patch(
            "src.services.orchestrator.generate_image_with_retry",
            side_effect=mostly_fail,
        ):
            with patch(
                "src.services.orchestrator.update_job_status", new_callable=AsyncMock
            ):
                with pytest.raises(StoryBookError) as exc_info:
                    await generate_all_images("test-job", prompts, 5)

        assert exc_info.value.code == ErrorCode.IMAGE_FAILED


# ==================== normalize_input Tests ====================


class TestNormalizeInput:
    """입력 정규화 테스트"""

    @pytest.mark.asyncio
    async def test_passthrough(self):
        """BookSpec을 그대로 반환 (현재 구현)"""
        from src.services.orchestrator import normalize_input
        from src.models.dto import BookSpec

        spec = BookSpec(
            topic="토끼 이야기",
            language="ko",
            target_age="5-7",
            style="watercolor",
        )

        result = await normalize_input(spec)
        assert result.topic == spec.topic
        assert result.language == spec.language


# ==================== M31: rewrite 검증 ====================
class TestRewriteValidation:
    def test_rewrite_result_parses_fenced_json(self):
        """마크다운 펜스로 감싼 응답도 파싱된다(anthropic 흔한 출력, M31)."""
        from src.models.dto import RewriteResult
        from src.services.llm import parse_json_response

        fenced = '```json\n{"page": 1, "revised_text": "고친 문장"}\n```'
        result = parse_json_response(fenced, RewriteResult)
        assert result.revised_text == "고친 문장"

    def test_rewrite_result_missing_field_raises(self):
        """revised_text 누락 응답은 조용한 성공이 아니라 LLM_JSON_INVALID로 실패(M31)."""
        from src.core.errors import ErrorCode, LLMError
        from src.models.dto import RewriteResult
        from src.services.llm import parse_json_response

        with pytest.raises(LLMError) as exc:
            parse_json_response('{"page": 1}', RewriteResult)
        assert exc.value.code == ErrorCode.LLM_JSON_INVALID

    def test_call_text_rewrite_uses_parse_and_field_access(self):
        """call_text_rewrite가 raw json.loads 대신 parse_json_response(RewriteResult)를 쓰고
        orchestrator가 .revised_text로 접근(조용한 no-op 제거) — 소스 확인(M31)."""
        import inspect

        from src.services import llm as llm_module
        from src.services import orchestrator as orch_module

        rewrite_src = inspect.getsource(llm_module.call_text_rewrite)
        assert "parse_json_response(response, RewriteResult)" in rewrite_src
        assert "json.loads(response)" not in rewrite_src

        regen_src = inspect.getsource(orch_module.regenerate_page)
        assert "rewrite_result.revised_text" in regen_src
        assert 'rewrite_result.get("revised_text"' not in regen_src


# ==================== M29: 안전 차단 메시지 언어 ====================


@pytest.mark.asyncio
async def test_safety_input_error_message_no_korean_prefix(monkeypatch):
    """M29: SAFETY_INPUT 실패 메시지에 한국어 접두어 없이 reasons 원문만 담긴다.

    한국어 접두어('입력이 안전하지 않습니다: ')는 클라이언트가 코드 기반 l10n으로
    붙이므로, 서버 error_message는 사용자 언어로 생성된 reasons만 담아야 한다.
    """
    from src.services import orchestrator as orch
    from src.models.dto import BookSpec, ModerationResult

    captured = {}

    async def fake_mark_failed(job_id, error_code, message):
        captured["code"] = error_code
        captured["message"] = message

    monkeypatch.setattr(orch, "update_job_status", AsyncMock())
    monkeypatch.setattr(orch, "mark_job_failed", fake_mark_failed)
    monkeypatch.setattr(
        orch,
        "moderate_input",
        AsyncMock(
            return_value=ModerationResult(
                is_safe=False, reasons=["unsafe topic"], suggestions=[]
            )
        ),
    )

    spec = BookSpec(topic="x", language="en", target_age="5-7", style="watercolor")
    await orch.start_book_generation(job_id="j1", spec=spec, user_key="u1")

    assert captured["code"] == ErrorCode.SAFETY_INPUT
    assert "입력이 안전하지 않습니다" not in captured["message"]
    assert "unsafe topic" in captured["message"]


# ==================== M12: 재생성/리텔/인페인트 모더레이션 재사용 ====================


def test_moderate_text_pure_helper():
    """M12: _moderate_text 순수 헬퍼 — 금칙 표현은 False, 정상은 True."""
    from src.services.orchestrator import _moderate_text

    assert _moderate_text("토리는 친구들과 즐겁게 놀았어요") is True
    assert _moderate_text("늑대가 토끼를 잔혹하게 살해했다") is False
    assert _moderate_text("a happy day with murder scene") is False


def test_regenerate_request_requires_feedback_for_text_mode():
    """M12: mode=text/both는 feedback 필수(없으면 검증 실패) — no-op done 위장 차단."""
    import pytest as _pytest
    from pydantic import ValidationError

    from src.models.dto import RegeneratePageRequest

    # image 모드는 feedback 없이 허용
    RegeneratePageRequest(mode="image")
    # text/both는 feedback 없으면 거부
    with _pytest.raises(ValidationError):
        RegeneratePageRequest(mode="text")
    with _pytest.raises(ValidationError):
        RegeneratePageRequest(mode="both", feedback="   ")
    # feedback 있으면 통과
    RegeneratePageRequest(mode="text", feedback="더 밝게 해줘")


class _RegenRes:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return self._v


class _RegenSession:
    """regenerate_page용 최소 fake 세션 — execute가 순서대로 book/page/draft 반환."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._i = 0
        self.committed = False

    async def execute(self, _q):
        row = self._rows[self._i]
        self._i += 1
        return _RegenRes(row)

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_regenerate_rejects_forbidden_feedback(monkeypatch):
    """M12: 금칙 feedback은 SAFETY_INPUT으로 차단되고 page.text는 불변."""
    from types import SimpleNamespace

    from src.core.errors import SafetyError
    from src.services import orchestrator as orch

    book = SimpleNamespace(
        id="b1", title="t", language="ko", target_age="5-7", style="watercolor"
    )
    page = SimpleNamespace(id="p1", text="원래 본문", page_number=1)
    monkeypatch.setattr(
        "src.core.database.AsyncSessionLocal",
        lambda: _RegenSession([book, page]),
    )

    with pytest.raises(SafetyError) as ei:
        await orch.regenerate_page(
            "job1", "b1", 1, "text", feedback="늑대가 토끼를 잔혹하게 살해하는 장면"
        )
    assert ei.value.code == ErrorCode.SAFETY_INPUT
    assert page.text == "원래 본문"  # 무검사 커밋 없음


@pytest.mark.asyncio
async def test_regenerate_missing_draft_no_silent_noop(monkeypatch):
    """M12: draft 없는 책(retell 등)의 텍스트 재생성은 done 위장 대신 명시 실패."""
    from types import SimpleNamespace

    from src.services import orchestrator as orch

    book = SimpleNamespace(
        id="b1", title="t", language="ko", target_age="5-7", style="watercolor"
    )
    page = SimpleNamespace(id="p1", text="원래 본문", page_number=1)
    # 3번째 execute(draft 조회)가 None → draft 부재
    session = _RegenSession([book, page, None])
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", lambda: session)

    with pytest.raises(StoryBookError):
        await orch.regenerate_page(
            "job1", "b1", 1, "text", feedback="더 밝고 따뜻하게 써줘"
        )
    assert page.text == "원래 본문"  # 불변
    assert session.committed is False  # done 위장 커밋 없음


# ==================== H23: 재작성 언어 전달 + 이중언어 컬럼 동기화 ====================


@pytest.mark.asyncio
async def test_rewrite_prompt_includes_target_language(monkeypatch):
    """H23: call_text_rewrite가 책 언어(language_name)를 프롬프트에 전달(한국어 회귀 차단)."""
    from src.services import llm as llm_module
    from src.models.dto import BookSpec

    captured = {}

    async def fake_call_llm(system_prompt, user_prompt, **kw):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return '{"page":1,"revised_text":"x"}'

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    story = TestModerateOutput()._make_story(
        page_texts=["a story page", "another"],
    )
    spec = BookSpec(topic="t", language="en", target_age="5-7", style="watercolor")
    await llm_module.call_text_rewrite(spec, story, 1, "make it shorter")

    assert "English" in captured["system"]  # language_name 지시 존재
    assert "language: en" in captured["user"]


@pytest.mark.asyncio
async def test_regenerate_page_syncs_and_invalidates_bilingual(monkeypatch):
    """H23/G18: en 책 재작성 시 text_en 갱신·text_ko 무효화·오디오 무효화(최소안)."""
    from types import SimpleNamespace

    from src.services import orchestrator as orch
    from src.services import llm as llm_module
    from src.models.dto import Language, RewriteResult

    book = SimpleNamespace(
        id="b1", title="t", language="en", target_age="5-7", style="watercolor"
    )
    page = SimpleNamespace(
        id="p1", text="en old", text_ko="ko stale", text_en="en old",
        audio_url="a", audio_url_ko="ak", audio_url_en="ae",
        page_number=1, image_prompt=None,
    )
    draft = TestModerateOutput()._make_story(language=Language.en)
    draft_db = SimpleNamespace(draft=draft.model_dump())
    session = _RegenSession([book, page, draft_db])
    monkeypatch.setattr("src.core.database.AsyncSessionLocal", lambda: session)

    async def fake_rewrite(spec, story, page_number, feedback):
        return RewriteResult(page=1, revised_text="shorter en text")

    monkeypatch.setattr(llm_module, "call_text_rewrite", fake_rewrite)

    await orch.regenerate_page("job1", "b1", 1, "text", feedback="make it shorter")

    assert page.text == "shorter en text"
    assert page.text_en == "shorter en text"  # 책 언어 컬럼 동기화
    assert page.text_ko is None  # 반대 언어 컬럼 무효화
    # 본문과 어긋난 오디오 캐시 전부 무효화
    assert page.audio_url is None
    assert page.audio_url_ko is None
    assert page.audio_url_en is None
