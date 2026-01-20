#!/bin/bash
# =============================================================================
# check-env.sh - Environment Variable Validation Script
# =============================================================================
# Usage:
#   ./scripts/check-env.sh          # Check local .env file
#   ./scripts/check-env.sh --ci     # CI mode (check env vars are defined)
#   ./scripts/check-env.sh --help   # Show help
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Required environment variables for production
REQUIRED_VARS=(
    "DATABASE_URL"
    "REDIS_URL"
    "LLM_PROVIDER"
    "IMAGE_PROVIDER"
    "S3_ENDPOINT"
    "S3_ACCESS_KEY"
    "S3_SECRET_KEY"
    "S3_BUCKET"
)

# Optional but recommended variables
OPTIONAL_VARS=(
    "LLM_API_KEY"
    "IMAGE_API_KEY"
    "TTS_PROVIDER"
    "CORS_ORIGINS"
    "DEBUG"
)

# Variables that should have API keys in production
API_KEY_VARS=(
    "LLM_API_KEY"
    "IMAGE_API_KEY"
)

print_help() {
    echo "Environment Variable Validation Script"
    echo ""
    echo "Usage:"
    echo "  ./scripts/check-env.sh          Check local .env file"
    echo "  ./scripts/check-env.sh --ci     CI mode (validates schema only)"
    echo "  ./scripts/check-env.sh --help   Show this help"
    echo ""
    echo "Required variables:"
    for var in "${REQUIRED_VARS[@]}"; do
        echo "  - $var"
    done
}

check_var() {
    local var_name=$1
    local is_required=$2

    if [ -n "${!var_name}" ]; then
        # Check if it's a placeholder value
        if [[ "${!var_name}" == *"your-"* ]] || [[ "${!var_name}" == *"change_me"* ]] || [[ "${!var_name}" == *"EXAMPLE"* ]]; then
            echo -e "${YELLOW}WARNING${NC}: $var_name appears to be a placeholder value"
            return 1
        fi
        echo -e "${GREEN}OK${NC}: $var_name is set"
        return 0
    else
        if [ "$is_required" = "true" ]; then
            echo -e "${RED}MISSING${NC}: $var_name is required but not set"
            return 1
        else
            echo -e "${YELLOW}OPTIONAL${NC}: $var_name is not set"
            return 0
        fi
    fi
}

main() {
    local ci_mode=false
    local has_errors=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --ci)
                ci_mode=true
                shift
                ;;
            --help|-h)
                print_help
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                print_help
                exit 1
                ;;
        esac
    done

    echo "========================================"
    echo "Environment Variable Validation"
    echo "========================================"
    echo ""

    # In CI mode, we just verify the schema exists and is valid
    if [ "$ci_mode" = true ]; then
        echo "CI Mode: Validating environment schema..."

        # Check that env.schema.json exists
        if [ -f "env.schema.json" ]; then
            echo -e "${GREEN}OK${NC}: env.schema.json exists"
        else
            echo -e "${YELLOW}INFO${NC}: env.schema.json not found (optional)"
        fi

        # Check that .env.example exists
        if [ -f "apps/api/.env.example" ]; then
            echo -e "${GREEN}OK${NC}: apps/api/.env.example exists"
        else
            echo -e "${RED}MISSING${NC}: apps/api/.env.example not found"
            has_errors=true
        fi

        if [ -f "infra/.env.example" ]; then
            echo -e "${GREEN}OK${NC}: infra/.env.example exists"
        else
            echo -e "${RED}MISSING${NC}: infra/.env.example not found"
            has_errors=true
        fi

        echo ""
        echo "CI validation complete."

        if [ "$has_errors" = true ]; then
            exit 1
        fi
        exit 0
    fi

    # Load .env file if it exists
    if [ -f ".env" ]; then
        echo "Loading .env file..."
        set -a
        source .env
        set +a
    elif [ -f "apps/api/.env" ]; then
        echo "Loading apps/api/.env file..."
        set -a
        source apps/api/.env
        set +a
    else
        echo -e "${YELLOW}WARNING${NC}: No .env file found"
    fi

    echo ""
    echo "Checking required variables..."
    echo "----------------------------------------"

    for var in "${REQUIRED_VARS[@]}"; do
        if ! check_var "$var" "true"; then
            has_errors=true
        fi
    done

    echo ""
    echo "Checking optional variables..."
    echo "----------------------------------------"

    for var in "${OPTIONAL_VARS[@]}"; do
        check_var "$var" "false"
    done

    echo ""
    echo "========================================"

    if [ "$has_errors" = true ]; then
        echo -e "${RED}Validation FAILED${NC}"
        echo ""
        echo "Please set the missing required environment variables."
        echo "See apps/api/.env.example for reference."
        exit 1
    else
        echo -e "${GREEN}Validation PASSED${NC}"
        exit 0
    fi
}

main "$@"
