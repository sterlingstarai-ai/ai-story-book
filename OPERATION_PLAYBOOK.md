# Operation Playbook

**Date**: 2026-01-21
**Version**: 0.2.0
**Audience**: Operations Team, On-call Engineers

---

## 1. Quick Reference

### 1.1 Service URLs

| Service | Development | Production |
|---------|-------------|------------|
| API | http://localhost:8000 | https://api.aistorybook.com |
| API Docs | http://localhost:8000/docs | https://api.aistorybook.com/docs |
| Health | http://localhost:8000/health | https://api.aistorybook.com/health |

### 1.2 Key Contacts

| Role | Contact |
|------|---------|
| Dev Lead | - |
| DevOps | - |
| Vendor (OpenAI) | support@openai.com |
| Vendor (Replicate) | support@replicate.com |

### 1.3 Monitoring Links

| Dashboard | Purpose |
|-----------|---------|
| Grafana | Metrics & Alerts |
| CloudWatch | Logs |
| GitHub Actions | CI/CD |

---

## 2. Common Incidents

### 2.1 High Job Failure Rate

**Symptoms**:
- Job failure rate > 10%
- User complaints about book generation failing

**Diagnosis**:
```bash
# Check recent failures
curl -s https://api.aistorybook.com/health/detailed | jq '.jobs'

# Check logs for errors
docker logs api-server --tail 100 | grep ERROR
```

**Resolution**:
1. Check external API status (OpenAI, Replicate)
2. If external API down, wait for recovery
3. If internal error, check recent deployments
4. Consider rollback if needed

**Escalation**: If not resolved in 30 minutes

---

### 2.2 API Response Time High

**Symptoms**:
- p99 latency > 5s
- User complaints about slow response

**Diagnosis**:
```bash
# Check detailed health
curl -s https://api.aistorybook.com/health/detailed

# Check DB connections
docker exec -it postgres psql -U storybook -c "SELECT count(*) FROM pg_stat_activity;"

# Check Redis
docker exec -it redis redis-cli INFO clients
```

**Resolution**:
1. Check if DB connections are exhausted
2. Check if Redis is responding
3. Scale up API servers if needed
4. Check for slow queries

---

### 2.3 Cost Spike Alert

**Symptoms**:
- Daily API cost > $100
- Unusual traffic patterns

**Diagnosis**:
```bash
# Check job count today
curl -s https://api.aistorybook.com/health/detailed | jq '.jobs'

# Check for suspicious users
psql -c "SELECT user_key, count(*) FROM jobs WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY user_key ORDER BY count DESC LIMIT 10;"
```

**Resolution**:
1. Identify source of high usage
2. If abuse, block user
3. If legitimate, monitor and notify business
4. Consider emergency rate limit reduction

**Emergency Action**:
```bash
# Reduce rate limit temporarily
export RATE_LIMIT_REQUESTS=5
docker-compose restart api
```

---

### 2.4 Stuck Jobs Detected

**Symptoms**:
- Jobs in 'running' state for > 15 minutes
- Job monitor alerts

**Diagnosis**:
```bash
# Check stuck jobs count
curl -s https://api.aistorybook.com/health/detailed | jq '.jobs.stuck'

# Check specific stuck jobs
psql -c "SELECT id, current_step, updated_at FROM jobs WHERE status = 'running' AND updated_at < NOW() - INTERVAL '15 minutes';"
```

**Resolution**:
1. Job monitor should auto-recover (check logs)
2. If auto-recovery failing, check worker health
3. Manual recovery if needed:
```bash
psql -c "UPDATE jobs SET status = 'failed', error_code = 'MANUAL_RECOVERY' WHERE status = 'running' AND updated_at < NOW() - INTERVAL '30 minutes';"
```

---

### 2.5 Database Connection Exhaustion

**Symptoms**:
- "too many connections" errors
- API requests timing out

**Diagnosis**:
```bash
# Check connection count
psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'storybook';"

# Check connection by state
psql -c "SELECT state, count(*) FROM pg_stat_activity WHERE datname = 'storybook' GROUP BY state;"
```

**Resolution**:
1. Kill idle connections:
```bash
psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'storybook' AND state = 'idle' AND query_start < NOW() - INTERVAL '10 minutes';"
```
2. Increase pool size if needed
3. Scale DB instance

---

## 3. Deployment Procedures

### 3.1 Standard Deployment

```bash
# 1. Create deployment branch
git checkout main
git pull
git checkout -b deploy/$(date +%Y%m%d)

# 2. Run pre-deploy checks
./scripts/check-env.sh
./scripts/smoke.sh --dry-run

# 3. Push and create PR
git push origin deploy/$(date +%Y%m%d)
gh pr create --title "Deploy $(date +%Y-%m-%d)"

# 4. Merge PR (triggers CI/CD)
gh pr merge --auto

# 5. Monitor deployment
gh run watch

# 6. Verify deployment
curl -s https://api.aistorybook.com/health
```

### 3.2 Hotfix Deployment

```bash
# 1. Create hotfix branch from main
git checkout main
git pull
git checkout -b hotfix/issue-description

# 2. Make fix, commit
git add .
git commit -m "fix: description"

# 3. Push and fast-track PR
git push origin hotfix/issue-description
gh pr create --title "HOTFIX: description"
gh pr merge --admin --squash

# 4. Monitor
gh run watch
```

### 3.3 Rollback Procedure

```bash
# 1. Identify last good commit
git log --oneline -10

# 2. Revert to last good commit
git revert HEAD~N..HEAD

# 3. Push revert
git push origin main

# 4. Or use Docker image rollback
docker pull ghcr.io/company/ai-story-book/api:$PREVIOUS_SHA
docker-compose up -d

# 5. Verify rollback
curl -s https://api.aistorybook.com/health
```

---

## 4. Maintenance Procedures

### 4.1 Database Maintenance

**Weekly Tasks**:
```bash
# Vacuum and analyze
psql -c "VACUUM ANALYZE;"

# Check table sizes
psql -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC;"
```

**Monthly Tasks**:
```bash
# Full vacuum (schedule during low traffic)
psql -c "VACUUM FULL;"

# Reindex
psql -c "REINDEX DATABASE storybook;"
```

### 4.2 Log Rotation

Logs are automatically rotated by Docker. Manual cleanup if needed:
```bash
# Clean old logs
docker system prune --filter "until=168h"

# Clean dangling images
docker image prune -a --filter "until=720h"
```

### 4.3 Certificate Renewal

Certificates are auto-renewed by cert-manager. Manual renewal:
```bash
# Check expiry
openssl s_client -connect api.aistorybook.com:443 -servername api.aistorybook.com 2>/dev/null | openssl x509 -noout -dates

# Force renewal
kubectl delete secret tls-secret
```

---

## 5. Emergency Procedures

### 5.1 Complete Service Outage

1. **Assess**: Check all components (API, DB, Redis)
2. **Communicate**: Post status update
3. **Restore**: Start with DB, then Redis, then API
4. **Verify**: Run smoke tests
5. **Post-mortem**: Document within 24 hours

### 5.2 Data Breach Suspected

1. **Isolate**: Block external access immediately
2. **Preserve**: Take snapshots of all systems
3. **Investigate**: Check access logs
4. **Report**: Notify security team
5. **Remediate**: Reset credentials, patch vulnerability

### 5.3 Cost Emergency ($500+/day)

1. **Rate limit**: Set to minimum (1 req/min)
```bash
export RATE_LIMIT_REQUESTS=1
docker-compose restart api
```
2. **Disable new jobs**: Temporarily reject all /books POST
3. **Investigate**: Find source of cost
4. **Block**: Block abusive users/IPs
5. **Restore**: Gradually increase limits

---

## 6. Health Check Reference

### 6.1 Basic Health

```bash
curl https://api.aistorybook.com/health
```

Expected:
```json
{"status": "healthy", "version": "0.2.0"}
```

### 6.2 Detailed Health

```bash
curl https://api.aistorybook.com/health/detailed
```

Expected:
```json
{
  "status": "healthy",
  "version": "0.2.0",
  "jobs": {
    "queued": 0,
    "running": 2,
    "stuck": 0,
    "completed_last_hour": 15,
    "failed_last_hour": 1,
    "success_rate": 93.75
  },
  "services": {
    "redis": "healthy",
    "llm_provider": "openai",
    "image_provider": "replicate"
  },
  "config": {
    "rate_limit_requests": 10,
    "rate_limit_window": 60,
    "job_sla_seconds": 600,
    "image_max_concurrent": 3
  }
}
```

### 6.3 Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| `jobs.stuck` | > 0 | > 5 |
| `jobs.success_rate` | < 90% | < 80% |
| `jobs.queued` | > 50 | > 100 |

---

## 7. Useful Commands

### 7.1 Docker

```bash
# View logs
docker-compose logs -f api

# Restart service
docker-compose restart api

# Scale workers
docker-compose up -d --scale worker=3

# Enter container
docker exec -it api-server bash
```

### 7.2 Database

```bash
# Connect to DB
docker exec -it postgres psql -U storybook

# Quick queries
psql -c "SELECT status, count(*) FROM jobs GROUP BY status;"
psql -c "SELECT * FROM jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT 10;"
```

### 7.3 Redis

```bash
# Connect to Redis
docker exec -it redis redis-cli

# Check rate limit keys
KEYS rate_limit:*
TTL rate_limit:user_123
```

---

## 8. Appendix

### 8.1 Error Codes Quick Reference

| Code | Meaning | User Action |
|------|---------|-------------|
| SAFETY_INPUT | Inappropriate content | Revise topic |
| LLM_TIMEOUT | AI service slow | Retry later |
| IMAGE_FAILED | Image generation failed | Retry or regenerate |
| SYS_RATE_LIMIT | Too many requests | Wait and retry |
| SYS_OVERLOADED | System busy | Wait and retry |

### 8.2 SLA Reference

| Metric | Target |
|--------|--------|
| API Availability | 99.5% |
| Book Generation Success | 95% |
| p99 Latency (API) | < 500ms |
| Book Generation Time | < 10 min |

---

*Last Updated: 2026-01-21*
