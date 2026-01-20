# AI Story Book - 배포 가이드

## 목차

1. [사전 요구사항](#사전-요구사항)
2. [빠른 시작](#빠른-시작)
3. [환경 설정](#환경-설정)
4. [배포 방법](#배포-방법)
5. [모니터링](#모니터링)
6. [문제 해결](#문제-해결)

---

## 사전 요구사항

### 서버 요구사항

- **OS**: Ubuntu 22.04 LTS 권장
- **CPU**: 4 cores 이상
- **RAM**: 8GB 이상
- **Storage**: 50GB 이상 SSD
- **Network**: 고정 IP, 도메인 (선택)

### 소프트웨어

```bash
# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Docker Compose 설치
sudo apt-get install docker-compose-plugin

# Git 설치
sudo apt-get install git
```

---

## 빠른 시작

```bash
# 1. 프로젝트 클론
git clone https://github.com/your-org/ai-story-book.git
cd ai-story-book

# 2. 환경 변수 설정
cp infra/.env.example .env
nano .env  # API 키 등 설정

# 3. 배포
./scripts/deploy.sh deploy
```

---

## 환경 설정

### 필수 환경 변수

| 변수 | 설명 | 예시 |
|------|------|------|
| `DB_USER` | PostgreSQL 사용자 | `aistorybook` |
| `DB_PASSWORD` | PostgreSQL 비밀번호 | `secure_password` |
| `DB_NAME` | 데이터베이스 이름 | `aistorybook` |
| `LLM_PROVIDER` | LLM 제공자 | `openai`, `anthropic` |
| `LLM_API_KEY` | LLM API 키 | `sk-...` |
| `IMAGE_PROVIDER` | 이미지 제공자 | `replicate`, `fal` |
| `IMAGE_API_KEY` | 이미지 API 키 | `r8_...` |

### S3 스토리지 설정

#### MinIO (자체 호스팅)

```env
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=your_secret_key
S3_BUCKET=ai-story-book
```

#### AWS S3

```env
S3_ENDPOINT=https://s3.amazonaws.com
S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
S3_SECRET_KEY=your_secret_key
S3_BUCKET=ai-story-book
S3_REGION=ap-northeast-2
```

#### Cloudflare R2

```env
S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key
S3_BUCKET=ai-story-book
```

---

## 배포 방법

### 수동 배포

```bash
# 전체 배포
./scripts/deploy.sh deploy

# 개별 명령
./scripts/deploy.sh build    # 이미지 빌드
./scripts/deploy.sh start    # 서비스 시작
./scripts/deploy.sh migrate  # DB 마이그레이션
./scripts/deploy.sh status   # 상태 확인
./scripts/deploy.sh logs     # 로그 확인
```

### GitHub Actions 자동 배포

1. GitHub Secrets 설정:
   - `DEPLOY_HOST`: 서버 IP
   - `DEPLOY_USER`: SSH 사용자
   - `DEPLOY_KEY`: SSH 개인키

2. `main` 브랜치에 푸시하면 자동 배포

---

## 서비스 구조

```
┌─────────────┐     ┌─────────────┐
│   Nginx     │────▶│   API (x2)  │
│  (Reverse   │     │  FastAPI    │
│   Proxy)    │     └──────┬──────┘
└─────────────┘            │
                           ▼
┌─────────────┐     ┌─────────────┐
│  PostgreSQL │◀───▶│  Worker(x2) │
└─────────────┘     │   Celery    │
                    └──────┬──────┘
┌─────────────┐            │
│    Redis    │◀───────────┘
└─────────────┘

┌─────────────┐
│  MinIO/S3   │  (이미지 저장소)
└─────────────┘
```

---

## SSL 설정 (HTTPS)

### Let's Encrypt 사용

```bash
# Certbot 설치
sudo apt-get install certbot

# 인증서 발급
sudo certbot certonly --standalone -d yourdomain.com

# 인증서 위치
# /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

### Nginx SSL 설정

`infra/nginx/nginx.conf`에서 SSL 관련 주석 해제 후:

```bash
# SSL 인증서 복사
cp /etc/letsencrypt/live/yourdomain.com/*.pem infra/nginx/ssl/

# 서비스 재시작
./scripts/deploy.sh restart
```

---

## 모니터링

### 헬스 체크

```bash
# API 헬스 체크
curl http://localhost/health

# 전체 서비스 상태
./scripts/deploy.sh health
```

### 로그 확인

```bash
# 전체 로그
./scripts/deploy.sh logs

# 특정 서비스 로그
docker-compose -f infra/docker-compose.prod.yml logs -f api
docker-compose -f infra/docker-compose.prod.yml logs -f worker
```

### 리소스 모니터링

```bash
# 컨테이너 리소스 사용량
docker stats
```

---

## 백업 및 복구

### 데이터베이스 백업

```bash
# 백업
./scripts/deploy.sh backup

# 수동 백업
docker-compose -f infra/docker-compose.prod.yml exec postgres \
    pg_dump -U $DB_USER $DB_NAME > backup_$(date +%Y%m%d).sql
```

### 데이터베이스 복구

```bash
# 복구
docker-compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U $DB_USER $DB_NAME < backup_20240101.sql
```

---

## 스케일링

### API/Worker 스케일링

```bash
# API 서버 3대로 스케일
docker-compose -f infra/docker-compose.prod.yml up -d --scale api=3

# Worker 4대로 스케일
docker-compose -f infra/docker-compose.prod.yml up -d --scale worker=4
```

---

## 문제 해결

### 서비스가 시작되지 않음

```bash
# 로그 확인
docker-compose -f infra/docker-compose.prod.yml logs

# 컨테이너 상태 확인
docker ps -a
```

### 데이터베이스 연결 실패

```bash
# PostgreSQL 상태 확인
docker-compose -f infra/docker-compose.prod.yml exec postgres pg_isready

# 연결 테스트
docker-compose -f infra/docker-compose.prod.yml exec postgres \
    psql -U $DB_USER -d $DB_NAME -c "SELECT 1"
```

### 이미지 생성 실패

1. API 키 확인
2. Rate limit 확인
3. Worker 로그 확인: `docker-compose logs worker`

### 메모리 부족

```bash
# 사용되지 않는 리소스 정리
./scripts/deploy.sh cleanup

# Docker 시스템 정리
docker system prune -a
```

---

## 보안 체크리스트

- [ ] 환경 변수에 민감한 정보 설정
- [ ] `.env` 파일 권한 제한 (`chmod 600 .env`)
- [ ] SSL/TLS 인증서 설정
- [ ] 방화벽 설정 (80, 443 포트만 개방)
- [ ] 정기 백업 설정
- [ ] 로그 모니터링 설정

---

## 비용 추정

### 서버 (월간)

| 항목 | 사양 | 예상 비용 |
|------|------|----------|
| VPS | 4 vCPU, 8GB RAM | $40-80 |
| 스토리지 | 100GB SSD | $10-20 |
| 도메인 | .com | $12/년 |

### API 사용량 (1,000권 기준)

| 항목 | 단가 | 월 비용 |
|------|------|---------|
| LLM | ~$0.05/권 | $50 |
| 이미지 | ~$0.27/권 | $270 |
| **합계** | | **~$320** |

---

## 지원

문제가 발생하면 GitHub Issues에 등록해주세요.
