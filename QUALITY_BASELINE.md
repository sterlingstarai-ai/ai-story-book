# Quality Baseline

**Date**: 2026-01-21
**Purpose**: 모델/프롬프트 변경 시 품질 저하 방지

---

## 1. Story Quality Metrics

### 1.1 Text Length Requirements (by Age Group)

| Age Group | Pages | Sentences/Page | Words/Page | Total Words |
|-----------|-------|----------------|------------|-------------|
| 3-5세 | 8 | 1-2 | 15-25 | 120-200 |
| 5-7세 | 8 | 2-3 | 25-40 | 200-320 |
| 7-9세 | 8 | 2-4 | 35-60 | 280-480 |
| adult | 8 | 3-6 | 50-100 | 400-800 |

### 1.2 Quality Thresholds

| Metric | Min | Max | Description |
|--------|-----|-----|-------------|
| `title_length` | 3 | 30 | Title character count |
| `page_count` | 6 | 12 | Number of pages |
| `avg_sentence_length` | 5 | 30 | Words per sentence |
| `vocabulary_diversity` | 0.4 | 1.0 | Unique words / total words |
| `repetition_ratio` | 0 | 0.15 | Repeated sentence ratio |

### 1.3 Forbidden Elements (아동 부적절 콘텐츠)

```python
FORBIDDEN_PATTERNS = [
    # Violence
    "죽이", "살인", "폭력", "피", "때리", "찌르",
    "kill", "murder", "blood", "violence", "weapon",

    # Adult content
    "술", "담배", "마약", "섹스", "성인",
    "alcohol", "drug", "sex", "adult",

    # Scary content
    "귀신", "악마", "지옥", "저주",
    "ghost", "demon", "hell", "curse",

    # Discrimination
    "바보", "멍청", "장애", "차별",
    "stupid", "idiot", "discrimination",
]
```

---

## 2. Image Prompt Consistency

### 2.1 Character Appearance Keywords

When generating image prompts, the following character attributes MUST be preserved across all pages:

| Attribute | Required | Example |
|-----------|----------|---------|
| `hair_color` | Yes | "brown hair", "black hair" |
| `hair_style` | Yes | "long curly", "short straight" |
| `eye_color` | Yes | "blue eyes", "brown eyes" |
| `skin_tone` | Yes | "fair skin", "tan skin" |
| `clothing_main` | Yes | "red dress", "blue overalls" |
| `distinctive_features` | If any | "freckles", "glasses" |

### 2.2 Style Consistency

All page images MUST include the same style tokens:

```python
STYLE_TOKENS = {
    "watercolor": "soft watercolor painting, gentle brush strokes, pastel colors",
    "cartoon": "vibrant cartoon, bold outlines, bright colors, playful",
    "3d": "3D rendered, Pixar-like, cute proportions, soft lighting",
    "pixel": "pixel art, 16-bit retro, limited palette",
    "oil_painting": "oil painting illustration, rich texture, warm tones",
    "claymation": "claymation, stop-motion look, textured clay figures",
}
```

### 2.3 Safety Negative Prompts

All image generations MUST include:

```python
NEGATIVE_PROMPTS = [
    "text", "watermark", "signature", "logo",
    "scary", "horror", "dark", "violent", "blood",
    "adult", "nsfw", "nude", "sexual",
    "deformed", "ugly", "bad anatomy", "extra limbs",
]
```

---

## 3. Quality Check Script

### 3.1 Usage

```bash
# Run quality check on a generated book
python scripts/quality_check.py --book-id <book_id>

# Run quality check on all recent books
python scripts/quality_check.py --recent 10

# Run as CI step (fails on quality issues)
python scripts/quality_check.py --ci --threshold 0.8
```

### 3.2 Output Format

```json
{
  "book_id": "book_20260121_abc123",
  "score": 0.92,
  "passed": true,
  "checks": {
    "text_length": {"passed": true, "score": 1.0, "details": "..."},
    "forbidden_content": {"passed": true, "score": 1.0, "details": "..."},
    "character_consistency": {"passed": true, "score": 0.85, "details": "..."},
    "style_consistency": {"passed": true, "score": 0.9, "details": "..."},
    "repetition": {"passed": true, "score": 0.95, "details": "..."}
  },
  "warnings": [],
  "errors": []
}
```

---

## 4. Regression Test Cases

### 4.1 Golden Test Cases

| ID | Topic | Age | Style | Expected Outcome |
|----|-------|-----|-------|------------------|
| G001 | "숲속 친구들" | 3-5 | watercolor | 8 pages, simple vocab |
| G002 | "용감한 토끼" | 5-7 | cartoon | 8 pages, dialogue present |
| G003 | "마법 학교" | 7-9 | 3d | 8 pages, cause-effect |
| G004 | "우주 탐험" | adult | oil_painting | 8 pages, narrative depth |

### 4.2 Edge Cases

| ID | Scenario | Expected Handling |
|----|----------|-------------------|
| E001 | Topic with forbidden words | Input moderation rejects |
| E002 | Very short topic (1 word) | Story generation succeeds |
| E003 | Topic in mixed language | Detects language, generates accordingly |
| E004 | Existing character reference | Character consistency maintained |

### 4.3 Failure Cases

| ID | Scenario | Expected Behavior |
|----|----------|-------------------|
| F001 | LLM returns invalid JSON | Retry up to 2 times |
| F002 | Image generation fails | Use placeholder image |
| F003 | Character description missing | Generate new character |
| F004 | Output contains forbidden content | Flag and report |

---

## 5. Quality Monitoring

### 5.1 Metrics to Track

| Metric | Frequency | Alert Threshold |
|--------|-----------|-----------------|
| Average quality score | Daily | < 0.85 |
| Forbidden content rate | Hourly | > 0.5% |
| Character consistency | Daily | < 0.80 |
| Image generation success | Hourly | < 95% |
| User regeneration rate | Daily | > 30% |

### 5.2 Quality Dashboard

Track and visualize:
- Quality score distribution
- Most common quality issues
- Quality by style/age group
- Quality trend over time
- Correlation with model changes

---

## 6. CI Integration

### 6.1 GitHub Actions Step

```yaml
quality-check:
  name: Quality Regression
  runs-on: ubuntu-latest
  needs: [api-test]
  if: github.event_name == 'pull_request'

  steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: pip install -r apps/api/requirements.txt

    - name: Run quality baseline tests
      run: |
        python scripts/quality_check.py --ci --threshold 0.85
      env:
        DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}
        TESTING: true
```

### 6.2 PR Check Requirements

- [ ] Quality score >= 85%
- [ ] No forbidden content detected
- [ ] Character consistency >= 80%
- [ ] No new quality regressions

---

## 7. Improvement Process

### 7.1 When Quality Drops

1. **Identify**: Which metric dropped?
2. **Isolate**: Which change caused it? (model, prompt, code)
3. **Test**: Create regression test for the case
4. **Fix**: Update prompt/code
5. **Verify**: Run quality check again
6. **Document**: Add to known issues

### 7.2 Quality Review Checklist

Before merging prompt/model changes:

- [ ] Run quality check on 10+ sample generations
- [ ] Compare quality scores with baseline
- [ ] Check character consistency in series
- [ ] Verify forbidden content filtering
- [ ] Review user feedback correlation

---

*Generated: 2026-01-21*
