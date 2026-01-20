#!/bin/bash
# =============================================================================
# smoke.sh - Smoke Test Script for AI Story Book API
# =============================================================================
# Usage:
#   ./scripts/smoke.sh                    # Run smoke tests against localhost
#   ./scripts/smoke.sh http://api.example.com  # Run against custom URL
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
BASE_URL="${1:-http://localhost:8000}"
TEST_USER_KEY="smoke-test-$(date +%s)"
TIMEOUT=30

# Counters
PASSED=0
FAILED=0

log_pass() {
    echo -e "${GREEN}PASS${NC}: $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}FAIL${NC}: $1"
    ((FAILED++))
}

log_info() {
    echo -e "${YELLOW}INFO${NC}: $1"
}

# =============================================================================
# Test Functions
# =============================================================================

test_health() {
    log_info "Testing health endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "${BASE_URL}/health" 2>/dev/null)
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        # Check if response contains expected fields
        if echo "$body" | grep -q '"status"'; then
            log_pass "Health check returned 200 with valid response"
            return 0
        else
            log_fail "Health check returned 200 but invalid response body"
            return 1
        fi
    else
        log_fail "Health check failed with HTTP $http_code"
        return 1
    fi
}

test_book_creation() {
    log_info "Testing book creation endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT \
        -X POST "${BASE_URL}/v1/books" \
        -H "Content-Type: application/json" \
        -H "X-User-Key: ${TEST_USER_KEY}" \
        -H "X-Idempotency-Key: smoke-test-$(date +%s)" \
        -d '{
            "topic": "Smoke test story",
            "language": "ko",
            "target_age": "5-7",
            "style": "watercolor",
            "page_count": 4
        }' 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    # Accept both 200/201 (success) and 402 (no credits - expected in clean env)
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        if echo "$body" | grep -q '"job_id"'; then
            local job_id=$(echo "$body" | grep -o '"job_id"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
            log_pass "Book creation returned job_id: $job_id"
            echo "$job_id"
            return 0
        else
            log_fail "Book creation returned 200 but no job_id"
            return 1
        fi
    elif [ "$http_code" = "402" ]; then
        # 402 means the endpoint is working but user has no credits
        log_pass "Book creation endpoint working (402 = no credits, expected in clean env)"
        return 0
    elif [ "$http_code" = "422" ]; then
        log_fail "Book creation failed with validation error (422)"
        echo "Response: $body"
        return 1
    else
        log_fail "Book creation failed with HTTP $http_code"
        echo "Response: $body"
        return 1
    fi
}

test_characters_list() {
    log_info "Testing characters list endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT \
        -X GET "${BASE_URL}/v1/characters" \
        -H "X-User-Key: ${TEST_USER_KEY}" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        if echo "$body" | grep -q '"characters"'; then
            log_pass "Characters list returned valid response"
            return 0
        else
            log_fail "Characters list returned 200 but invalid response"
            return 1
        fi
    else
        log_fail "Characters list failed with HTTP $http_code"
        return 1
    fi
}

test_library() {
    log_info "Testing library endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT \
        -X GET "${BASE_URL}/v1/library" \
        -H "X-User-Key: ${TEST_USER_KEY}" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        if echo "$body" | grep -q '"books"' || echo "$body" | grep -q '"total"'; then
            log_pass "Library endpoint returned valid response"
            return 0
        else
            log_fail "Library endpoint returned 200 but invalid response"
            return 1
        fi
    else
        log_fail "Library endpoint failed with HTTP $http_code"
        return 1
    fi
}

test_credits_balance() {
    log_info "Testing credits balance endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT \
        -X GET "${BASE_URL}/v1/credits/balance" \
        -H "X-User-Key: ${TEST_USER_KEY}" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        if echo "$body" | grep -q '"credits"'; then
            log_pass "Credits balance endpoint returned valid response"
            return 0
        else
            log_fail "Credits balance endpoint returned 200 but invalid response"
            return 1
        fi
    else
        log_fail "Credits balance endpoint failed with HTTP $http_code"
        return 1
    fi
}

test_streak_info() {
    log_info "Testing streak info endpoint..."

    local response
    response=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT \
        -X GET "${BASE_URL}/v1/streak/info" \
        -H "X-User-Key: ${TEST_USER_KEY}" 2>/dev/null)

    local http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "200" ]; then
        log_pass "Streak info endpoint returned 200"
        return 0
    else
        log_fail "Streak info endpoint failed with HTTP $http_code"
        return 1
    fi
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo "========================================"
    echo "AI Story Book - Smoke Tests"
    echo "========================================"
    echo "Target: ${BASE_URL}"
    echo "User Key: ${TEST_USER_KEY}"
    echo "========================================"
    echo ""

    # Run tests
    test_health
    test_characters_list
    test_library
    test_credits_balance
    test_streak_info
    test_book_creation

    # Summary
    echo ""
    echo "========================================"
    echo "Smoke Test Summary"
    echo "========================================"
    echo -e "Passed: ${GREEN}${PASSED}${NC}"
    echo -e "Failed: ${RED}${FAILED}${NC}"
    echo "========================================"

    if [ $FAILED -gt 0 ]; then
        echo -e "${RED}Smoke tests FAILED${NC}"
        exit 1
    else
        echo -e "${GREEN}All smoke tests PASSED${NC}"
        exit 0
    fi
}

main
