# AI Story Book - Cost Model

**Date**: 2026-01-21
**Version**: 0.2.0

---

## Executive Summary

이 문서는 AI Story Book 서비스의 비용 구조와 예상 비용을 분석합니다.

---

## 1. Cost Components Per Book

### 1.1 LLM API Costs

| Step | Provider | Model | Tokens (avg) | Cost/1K tokens | Cost/Book |
|------|----------|-------|--------------|----------------|-----------|
| Story Generation | OpenAI | gpt-4o-mini | ~2,500 | $0.00015 | $0.000375 |
| Character Sheet | OpenAI | gpt-4o-mini | ~1,000 | $0.00015 | $0.00015 |
| Image Prompts | OpenAI | gpt-4o-mini | ~2,000 | $0.00015 | $0.0003 |
| Moderation | OpenAI | gpt-4o-mini | ~500 | $0.00015 | $0.000075 |
| **LLM Total** | | | ~6,000 | | **~$0.0009** |

*Note: Using gpt-4o for higher quality increases costs by ~10x*

### 1.2 Image Generation Costs

| Provider | Model | Cost/Image | Images/Book | Cost/Book |
|----------|-------|------------|-------------|-----------|
| Replicate | SDXL | $0.0023 | 9 (1 cover + 8 pages) | $0.0207 |
| FAL.ai | Flux Schnell | $0.003 | 9 | $0.027 |
| **Average** | | | | **~$0.024** |

### 1.3 Storage Costs (S3/R2)

| Item | Size (avg) | Storage/GB/mo | Cost/Book/Month |
|------|------------|---------------|-----------------|
| Images | ~4.5MB | $0.023 | $0.0001 |
| PDF | ~2MB | $0.023 | $0.00005 |
| Audio | ~10MB | $0.023 | $0.0002 |
| **Storage Total** | ~16.5MB | | **~$0.0004** |

### 1.4 TTS Costs (Optional)

| Provider | Cost/Character | Chars/Book (avg) | Cost/Book |
|----------|---------------|------------------|-----------|
| Google TTS | $0.000004 | ~2,000 | $0.008 |
| ElevenLabs | $0.00003 | ~2,000 | $0.06 |
| **TTS Total** | | | **$0.008-$0.06** |

### 1.5 Total Cost Per Book

| Scenario | LLM | Images | Storage | TTS | Total |
|----------|-----|--------|---------|-----|-------|
| Basic (no audio) | $0.001 | $0.024 | $0.0004 | - | **$0.025** |
| With Audio (Google) | $0.001 | $0.024 | $0.0004 | $0.008 | **$0.033** |
| Premium (ElevenLabs) | $0.001 | $0.024 | $0.0004 | $0.06 | **$0.085** |
| Regeneration (×1.5) | | | | | **$0.038-$0.128** |

---

## 2. Infrastructure Costs (Monthly)

### 2.1 Compute (Cloud Run / EC2)

| Tier | Instance | vCPU | RAM | Cost/Month |
|------|----------|------|-----|------------|
| Dev | Small | 1 | 2GB | $15-30 |
| Production | Medium | 2 | 4GB | $50-100 |
| Scale | Large | 4 | 8GB | $150-300 |

### 2.2 Database (PostgreSQL)

| Tier | Size | Cost/Month |
|------|------|------------|
| Dev | 10GB | $10-20 |
| Production | 50GB | $50-100 |
| Scale | 200GB | $150-300 |

### 2.3 Redis

| Tier | Memory | Cost/Month |
|------|--------|------------|
| Dev | 256MB | $5-10 |
| Production | 1GB | $25-50 |
| Scale | 4GB | $100-150 |

### 2.4 Total Infrastructure

| Tier | Monthly Cost |
|------|-------------|
| Development | **$30-60** |
| Production | **$125-250** |
| Scale | **$400-750** |

---

## 3. Usage Scenarios

### 3.1 User Profiles

| User Type | Books/Month | With Audio |
|-----------|-------------|------------|
| Casual | 1-2 | No |
| Regular | 5-10 | Some |
| Power | 20+ | Yes |

### 3.2 Monthly Cost Projections

#### Scenario A: 1,000 Monthly Active Users (Casual)
```
Books generated: 1,500/month
Infrastructure: $125
API costs: 1,500 × $0.025 = $37.50
Total: ~$162.50/month
Cost per user: $0.16/user/month
```

#### Scenario B: 5,000 Monthly Active Users (Mixed)
```
Books generated: 15,000/month
Infrastructure: $250
API costs: 15,000 × $0.033 = $495
Total: ~$745/month
Cost per user: $0.15/user/month
```

#### Scenario C: 20,000 Monthly Active Users (Scale)
```
Books generated: 100,000/month
Infrastructure: $750
API costs: 100,000 × $0.033 = $3,300
Total: ~$4,050/month
Cost per user: $0.20/user/month
```

---

## 4. Cost Control Mechanisms

### 4.1 Implemented Quotas

```python
# Current settings (config.py)
RATE_LIMIT_REQUESTS = 10  # per minute per user
MAX_PAGE_COUNT = 12  # maximum pages per book
IMAGE_MAX_CONCURRENT = 3  # concurrent image generations
JOB_SLA_SECONDS = 600  # 10 minute timeout
```

### 4.2 Recommended Additional Controls

#### Daily/Monthly Limits Per User
```python
# Recommended implementation
class CostQuotas:
    FREE_TIER_BOOKS_PER_DAY = 1
    FREE_TIER_BOOKS_PER_MONTH = 10
    BASIC_TIER_BOOKS_PER_DAY = 5
    BASIC_TIER_BOOKS_PER_MONTH = 50
    PREMIUM_TIER_BOOKS_PER_DAY = 20
    PREMIUM_TIER_BOOKS_PER_MONTH = 200
```

#### Cost Circuit Breaker
```python
# Alert thresholds
DAILY_COST_ALERT_THRESHOLD = 100  # USD
DAILY_COST_HARD_LIMIT = 500  # USD
MONTHLY_COST_ALERT_THRESHOLD = 2000  # USD
MONTHLY_COST_HARD_LIMIT = 5000  # USD
```

### 4.3 Cost Explosion Prevention

| Scenario | Risk | Mitigation |
|----------|------|------------|
| DDoS on book creation | High API costs | Rate limiting, CAPTCHA |
| Image regeneration abuse | High image costs | Regeneration limits (3/page) |
| Large page counts | Higher costs | Cap at 12 pages |
| Audio for all books | TTS costs | Audio as premium feature |

---

## 5. Pricing Recommendations

### 5.1 Subscription Tiers

| Tier | Price/Month | Credits | Cost Margin |
|------|-------------|---------|-------------|
| Free | $0 | 3 books | -$0.10 (acquisition) |
| Basic | $4.99 | 30 books | $4.00 (80%) |
| Premium | $9.99 | 100 books | $6.69 (67%) |

### 5.2 Credit Packs

| Pack | Price | Credits | Cost/Book | Margin |
|------|-------|---------|-----------|--------|
| Starter | $2.99 | 10 | $0.299 | $0.266 (89%) |
| Value | $7.99 | 30 | $0.266 | $0.233 (88%) |
| Bulk | $14.99 | 60 | $0.250 | $0.217 (87%) |

---

## 6. Monitoring & Alerts

### 6.1 Key Metrics to Track

| Metric | Alert Threshold | Critical Threshold |
|--------|-----------------|-------------------|
| Books/hour | > 500 | > 1000 |
| API cost/hour | > $10 | > $50 |
| Image failures | > 5% | > 15% |
| LLM errors | > 2% | > 10% |

### 6.2 Cost Dashboard Requirements

- Real-time API cost tracking
- Daily/weekly/monthly cost reports
- Per-user cost analysis
- Cost by feature breakdown
- Anomaly detection alerts

---

## 7. Optimization Opportunities

### 7.1 Short-term (0-3 months)

| Optimization | Potential Savings |
|--------------|-------------------|
| Image caching for common styles | 10-15% |
| Batch LLM requests | 5-10% |
| Optimize prompts (fewer tokens) | 10-20% |

### 7.2 Medium-term (3-6 months)

| Optimization | Potential Savings |
|--------------|-------------------|
| Self-hosted image generation | 50-70% |
| Fine-tuned smaller LLM | 30-50% |
| CDN for image delivery | 20-30% |

### 7.3 Long-term (6+ months)

| Optimization | Potential Savings |
|--------------|-------------------|
| Custom image model | 70-80% |
| On-device TTS | 90%+ |
| Hybrid cloud/edge | 30-40% |

---

## Appendix: Cost Calculation Code

```python
# Cost calculator utility
class CostCalculator:
    LLM_COST_PER_1K_TOKENS = 0.00015
    IMAGE_COST_PER_IMAGE = 0.024
    TTS_COST_PER_CHAR = 0.000004
    STORAGE_COST_PER_GB_MONTH = 0.023

    @staticmethod
    def calculate_book_cost(
        page_count: int = 8,
        include_audio: bool = False,
        regenerations: int = 0
    ) -> float:
        # LLM costs
        llm_cost = 6000 * CostCalculator.LLM_COST_PER_1K_TOKENS / 1000

        # Image costs (cover + pages)
        images = page_count + 1 + regenerations
        image_cost = images * CostCalculator.IMAGE_COST_PER_IMAGE

        # TTS costs
        tts_cost = 0
        if include_audio:
            avg_chars_per_page = 250
            total_chars = page_count * avg_chars_per_page
            tts_cost = total_chars * CostCalculator.TTS_COST_PER_CHAR

        # Storage (negligible per book)
        storage_cost = 0.0004

        return llm_cost + image_cost + tts_cost + storage_cost

    @staticmethod
    def estimate_monthly_cost(
        active_users: int,
        books_per_user: float = 3,
        audio_ratio: float = 0.3,
        infrastructure_tier: str = "production"
    ) -> dict:
        infra_costs = {
            "development": 45,
            "production": 187.5,
            "scale": 575
        }

        total_books = int(active_users * books_per_user)
        books_with_audio = int(total_books * audio_ratio)
        books_without_audio = total_books - books_with_audio

        api_cost = (
            books_without_audio * CostCalculator.calculate_book_cost(include_audio=False) +
            books_with_audio * CostCalculator.calculate_book_cost(include_audio=True)
        )

        infra_cost = infra_costs.get(infrastructure_tier, 187.5)

        return {
            "total_books": total_books,
            "api_cost": round(api_cost, 2),
            "infrastructure_cost": infra_cost,
            "total_cost": round(api_cost + infra_cost, 2),
            "cost_per_user": round((api_cost + infra_cost) / active_users, 2)
        }
```

---

*Last Updated: 2026-01-21*
