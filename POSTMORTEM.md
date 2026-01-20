# AI Story Book - Pre-Deploy Postmortem & Risk Assessment

**Date**: 2026-01-21
**Version**: 0.2.0
**Author**: Pre-Deploy Hardening Team

---

## Executive Summary

AI Story Book v0.2 프리-디플로이 하드닝을 완료했습니다. 30개의 코드 리뷰 이슈를 수정하고, 보안 취약점을 점검하고, 테스트 커버리지를 향상시켰습니다. 이 문서는 발견된 이슈, 수정 내용, 그리고 남은 위험 요소를 정리합니다.

---

## TOP 10 Risk Assessment

### 1. [HIGH] External API Dependency - 외부 API 의존성

**Risk**: LLM(OpenAI), Image API(Replicate/FAL), TTS API 장애 시 서비스 전체 불능
**Impact**: 전체 책 생성 불가
**Probability**: Medium (주 1-2회 간헐적 장애 예상)

**Mitigations Implemented**:
- ✅ 재시도 로직 (exponential backoff)
- ✅ 타임아웃 설정 (LLM 30s, Image 90s)
- ✅ Chaos 테스트 추가 (`test_chaos.py`)

**Remaining Actions**:
- [ ] Fallback LLM provider 구현
- [ ] Circuit breaker 패턴 적용
- [ ] Status page 연동

---

### 2. [HIGH] Cost Explosion Risk - 비용 폭주 위험

**Risk**: DDoS, 남용, 또는 버그로 인한 API 비용 급증
**Impact**: 예상치 못한 대규모 비용 ($1000+/day)
**Probability**: Low-Medium

**Mitigations Implemented**:
- ✅ Rate limiting (10 req/min/user)
- ✅ 크레딧 시스템
- ✅ 비용 모델 문서화 (`COST_MODEL.md`)

**Remaining Actions**:
- [ ] Daily cost alert threshold ($100)
- [ ] Hard limit circuit breaker ($500/day)
- [ ] Cost dashboard 구축

---

### 3. [HIGH] SSRF Vulnerability - 서버 측 요청 위조

**Risk**: PDF 이미지 URL을 통한 내부 네트워크 접근
**Impact**: 내부 서비스 접근, 메타데이터 유출 (AWS IMDSv1)
**Probability**: Medium

**Mitigations Implemented**:
- ✅ URL 도메인 화이트리스트
- ✅ HTTP/HTTPS 스킴만 허용
- ✅ 응답 크기 제한 (10MB)
- ✅ SSRF 테스트 추가 (`test_services.py`)

**Remaining Actions**:
- [ ] AWS IMDSv2 강제
- [ ] Internal IP 블록리스트 추가

---

### 4. [MEDIUM] Weak Authentication - 약한 인증

**Risk**: X-User-Key 헤더만으로 인증, 추측/탈취 가능
**Impact**: 계정 탈취, 다른 사용자 데이터 접근
**Probability**: Medium

**Mitigations Implemented**:
- ✅ Rate limiting으로 brute-force 방지
- ✅ User key validation (최소 길이)

**Remaining Actions**:
- [ ] OAuth2/JWT 인증 구현
- [ ] User key 해싱 또는 암호화
- [ ] MFA 지원

---

### 5. [MEDIUM] Database Connection Exhaustion - DB 연결 고갈

**Risk**: 많은 동시 요청으로 DB 연결 풀 고갈
**Impact**: API 응답 지연/실패
**Probability**: Medium (스케일업 시)

**Mitigations Implemented**:
- ✅ Async connection pooling
- ✅ Chaos 테스트로 장애 시나리오 검증

**Remaining Actions**:
- [ ] Connection pool 모니터링
- [ ] Connection leak 탐지
- [ ] PgBouncer 도입 검토

---

### 6. [MEDIUM] Sensitive Data in Logs - 로그의 민감 정보

**Risk**: User key, 에러 메시지에 민감 정보 포함
**Impact**: 로그 유출 시 사용자 데이터 노출
**Probability**: Low

**Mitigations Implemented**:
- ✅ User key 마스킹 (첫 8자만 로깅)
- ✅ 구조화된 로깅 (structlog)

**Remaining Actions**:
- [ ] 로그 보존 정책 설정
- [ ] PII 필터링 강화
- [ ] 로그 암호화

---

### 7. [MEDIUM] Rate Limit Bypass - Rate Limit 우회

**Risk**: Redis 장애 시 fail-open으로 rate limit 무효화
**Impact**: 비용 폭주, DoS 공격 가능
**Probability**: Low

**Mitigations Implemented**:
- ✅ Fail-open with logging
- ✅ Redis health check

**Remaining Actions**:
- [ ] Fail-close 옵션 추가
- [ ] Secondary rate limit (in-memory)
- [ ] Redis 장애 알림

---

### 8. [MEDIUM] Image Generation Quality - 이미지 품질

**Risk**: 부적절한 이미지 생성 (아동 콘텐츠에 부적합)
**Impact**: 사용자 불만, 브랜드 이미지 손상
**Probability**: Low-Medium

**Mitigations Implemented**:
- ✅ Negative prompts
- ✅ Output moderation (텍스트)
- ✅ Forbidden elements 리스트

**Remaining Actions**:
- [ ] 이미지 NSFW 탐지
- [ ] Human-in-the-loop 검수
- [ ] 사용자 신고 기능

---

### 9. [LOW] Memory Leak in Mobile App - 모바일 메모리 누수

**Risk**: Stream subscription 미해제로 메모리 누수
**Impact**: 앱 성능 저하, 크래시
**Probability**: 수정 전 High → 수정 후 Low

**Mitigations Implemented**:
- ✅ StreamSubscription cancel in dispose
- ✅ Navigation guard (double navigation 방지)
- ✅ Color constant 최적화

**Remaining Actions**:
- [ ] Memory profiling
- [ ] Leak detection CI

---

### 10. [LOW] Deployment Rollback - 배포 롤백

**Risk**: 배포 실패 시 빠른 롤백 불가
**Impact**: 서비스 다운타임
**Probability**: Low

**Mitigations Implemented**:
- ✅ Git SHA 태그 이미지
- ✅ Health check
- ✅ Smoke test

**Remaining Actions**:
- [ ] Blue-green deployment
- [ ] Automatic rollback on health check failure
- [ ] Database migration rollback script

---

## Issues Fixed in This Session

### P0 Critical (7)
| Issue | File | Fix |
|-------|------|-----|
| Credit deduction missing | `books.py` | Added `use_credit()` call |
| Book detail endpoint missing | `books.py` | Added `/v1/books/{book_id}/detail` |
| Character ID not saved | `orchestrator.py` | Save `character_id=spec.character_id` |
| Series generation TODO | `orchestrator.py` | Implemented `generate_series_book()` |
| Page regeneration TODO | `orchestrator.py` | Implemented `regenerate_page()` |
| init-db.sql reference | `docker-compose.prod.yml` | Removed invalid reference |
| Sync/async URL split | `database.py` | Added URL conversion function |

### P1 Runtime Risk (8)
| Issue | File | Fix |
|-------|------|-----|
| From-photo schema | `characters.py` | Normalized schema |
| Rate limiter missing | `rate_limit.py` | Redis-based rate limiter |
| S3 bucket check | `storage.py` | Added `_bucket_verified` caching |
| Environment config | `env_config.dart` | Environment-specific baseUrl |
| Null safety | `api_client.dart` | Safe `response.data` handling |
| CORS hardcoded | `main.py` | Environment variable CORS_ORIGINS |
| Output moderation | `orchestrator.py` | Implemented moderation |
| Celery task wrapper | `tasks.py` | Added task wrapper |

### P2 Code Quality (9)
- Common dependencies module
- Print → logger replacement
- Security warning in .env.example
- Git-tracked asset folders
- Test fixtures for credits

### P3 Improvements (6)
- Standardized error responses
- UniqueConstraint on Page
- Image retry configuration
- TTS provider configuration
- Mobile API error handling

---

## New Test Coverage

| File | Tests Added |
|------|-------------|
| `test_security.py` | Security headers, input validation, CORS |
| `test_services.py` | PDF SSRF, credits, streak, moderation |
| `test_routers.py` | All router endpoints |
| `test_chaos.py` | LLM/Image failures, DB/Redis failures |
| `test_fuzzing.py` | Abnormal inputs, injection attempts |

---

## Recommendations for v0.3

1. **Authentication Overhaul**: Replace X-User-Key with OAuth2/JWT
2. **Cost Management**: Implement cost alerts and circuit breakers
3. **Image Safety**: Add NSFW detection for generated images
4. **Observability**: Implement distributed tracing (OpenTelemetry)
5. **Caching**: Add Redis caching for frequent queries
6. **CDN**: Add CloudFront/CloudFlare for static assets
7. **Mobile Performance**: Profile and optimize memory usage
8. **A/B Testing**: Framework for testing new features
9. **Analytics**: User behavior tracking (privacy-compliant)
10. **Disaster Recovery**: Multi-region deployment

---

## Conclusion

이번 프리-디플로이 하드닝을 통해 30개의 코드 이슈를 수정하고, 보안 취약점을 개선하고, 테스트 커버리지를 향상시켰습니다. TOP 10 위험 요소 중 대부분에 대해 기본적인 완화 조치를 구현했으며, 나머지는 v0.3에서 추가 개선이 필요합니다.

**Production Readiness**: ✅ Ready with monitoring
**Confidence Level**: 75%
**Critical Blockers**: None
**Recommended Actions Before Launch**:
1. Set up cost monitoring alerts
2. Configure production environment variables
3. Run full E2E test suite
4. Prepare rollback procedure

---

*Last Updated: 2026-01-21*
