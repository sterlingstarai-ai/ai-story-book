# API 키 설정 가이드

이 가이드는 AI Story Book 앱을 실제 AI 서비스와 연동하기 위한 API 키 설정 방법을 설명합니다.

## 필요한 API 키

| Provider | 용도 | 필수 | 예상 비용 (1권당) |
|----------|------|------|------------------|
| OpenAI 또는 Anthropic | 스토리/캐릭터 생성 | ✅ | ~$0.05 |
| Replicate 또는 FAL | 이미지 생성 | ✅ | ~$0.27 (9장) |
| Google TTS 또는 ElevenLabs | 오디오 생성 | ❌ | ~$0.02 |

## 1. LLM API 키 설정

### OpenAI (추천)
1. https://platform.openai.com/api-keys 접속
2. "Create new secret key" 클릭
3. 키 복사 후 설정:
```bash
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-openai-api-key
LLM_MODEL=gpt-4o-mini  # 또는 gpt-4o (더 좋은 품질)
```

### Anthropic
1. https://console.anthropic.com/settings/keys 접속
2. "Create Key" 클릭
3. 키 복사 후 설정:
```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-your-anthropic-key
LLM_MODEL=claude-3-5-sonnet-20241022
```

## 2. Image API 키 설정

### Replicate (추천)
1. https://replicate.com/account/api-tokens 접속
2. "Create Token" 클릭
3. 키 복사 후 설정:
```bash
IMAGE_PROVIDER=replicate
IMAGE_API_KEY=r8_your-replicate-key
```

### FAL.ai
1. https://fal.ai/dashboard/keys 접속
2. "Create Key" 클릭
3. 키 복사 후 설정:
```bash
IMAGE_PROVIDER=fal
IMAGE_API_KEY=your-fal-key
```

## 3. TTS API 키 설정 (선택사항)

### Google Cloud TTS
1. https://console.cloud.google.com 접속
2. "Cloud Text-to-Speech API" 활성화
3. API 키 생성
4. 설정:
```bash
TTS_PROVIDER=google
GOOGLE_TTS_API_KEY=your-google-key
```

### ElevenLabs
1. https://elevenlabs.io/api 접속
2. Profile Settings에서 API Key 복사
3. 설정:
```bash
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM  # 기본: Rachel 음성
```

## 4. 로컬 개발 환경에서 설정

### 방법 1: .env 파일 사용
```bash
cd apps/api
cp .env.example .env
# .env 파일을 편집하여 API 키 설정
```

### 방법 2: 환경 변수 직접 설정 (Docker)
```bash
cd infra

# .env 파일 생성
cat > .env << 'EOF'
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-key
IMAGE_PROVIDER=replicate
IMAGE_API_KEY=r8_your-key
EOF

# Docker 재시작
docker-compose down
docker-compose up -d
```

## 5. 설정 확인

API가 올바르게 설정되었는지 확인:
```bash
# 헬스 체크
curl http://localhost:8000/health

# 책 생성 테스트
curl -X POST http://localhost:8000/v1/books \
  -H "Content-Type: application/json" \
  -H "X-User-Key: test-user" \
  -d '{
    "topic": "마법의 숲에서 친구를 사귀는 토끼",
    "target_age": "5-7",
    "style": "watercolor",
    "page_count": 8
  }'
```

## 6. 비용 관리 팁

1. **개발 시**: `LLM_PROVIDER=mock`, `IMAGE_PROVIDER=mock` 사용
2. **테스트 시**: `gpt-4o-mini` 모델 사용 (gpt-4o보다 저렴)
3. **프로덕션**:
   - Rate Limit 설정 (`RATE_LIMIT_REQUESTS=10`)
   - 일일 한도 설정 (`DAILY_JOB_LIMIT_PER_USER=20`)

## 7. 트러블슈팅

### "API 키가 설정되지 않았습니다" 오류
- 환경 변수가 올바르게 설정되었는지 확인
- Docker를 사용하는 경우 컨테이너 재시작 필요

### "401 Unauthorized" 오류
- API 키가 유효한지 확인
- API 키에 필요한 권한이 있는지 확인

### 이미지 생성 실패
- Replicate 계정에 크레딧이 있는지 확인
- Rate Limit에 도달했는지 확인

## 8. 빠른 시작 체크리스트

- [ ] OpenAI 또는 Anthropic API 키 발급
- [ ] Replicate 또는 FAL API 키 발급
- [ ] .env 파일에 키 설정
- [ ] Docker 컨테이너 재시작
- [ ] 헬스 체크 확인
- [ ] 테스트 책 생성
