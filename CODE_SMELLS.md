# Code Smells Report

**Date**: 2026-01-21
**Project**: AI Story Book v0.2

---

## Overview

Code smells are indicators of potential problems in the codebase. They don't necessarily indicate bugs but suggest areas where code quality could be improved.

| Category | Count |
|----------|-------|
| Complexity | 4 |
| Duplication | 3 |
| Naming | 2 |
| Design | 5 |
| Maintainability | 4 |
| **Total** | 18 |

---

## 1. Complexity Smells

### CS-1: Long Method - `generate_book()`

**File**: `apps/api/src/services/orchestrator.py`
**Lines**: ~200 lines

```python
async def generate_book(self, spec: BookSpec, job_id: str) -> BookResult:
    # 200+ lines of sequential steps
```

**Problem**: Method is too long, hard to test and maintain.

**Recommendation**: Extract into smaller private methods:
- `_normalize_input()`
- `_moderate_input()`
- `_generate_story()`
- `_generate_images()`
- `_package_result()`

### CS-2: Nested Conditionals - Error Handling

**File**: `apps/api/src/routers/books.py:100-150`

```python
if job:
    if job.status == "done":
        if job.book:
            # deep nesting
```

**Recommendation**: Use early returns or guard clauses.

### CS-3: Complex Boolean Expressions

**File**: `apps/api/src/services/llm.py`

```python
if (not response or not response.choices or
    not response.choices[0].message or
    not response.choices[0].message.content):
```

**Recommendation**: Extract to helper function `is_valid_response()`.

### CS-4: Multiple Responsibility - `api_client.dart`

**File**: `apps/mobile/lib/services/api_client.dart`

**Problem**: Single class handles all API calls (500+ lines).

**Recommendation**: Split into domain-specific clients:
- `BookApiClient`
- `CharacterApiClient`
- `CreditApiClient`
- `StreakApiClient`

---

## 2. Duplication Smells

### DS-1: Repeated User Key Extraction

**Files**: Multiple routers

```python
# Repeated in every router
user_key = request.headers.get("X-User-Key")
if not user_key:
    raise HTTPException(status_code=401, detail="X-User-Key header required")
```

**Status**: FIXED - Moved to `core/dependencies.py`

### DS-2: Similar Validation Logic

**Files**: `routers/books.py`, `routers/characters.py`

```python
# Same validation pattern repeated
if len(topic) > 100:
    raise HTTPException(status_code=400, detail="Topic too long")
```

**Recommendation**: Create shared validation decorators or Pydantic validators.

### DS-3: Duplicate Error Messages

**Files**: Multiple locations

**Problem**: Same error messages hardcoded in multiple places.

**Recommendation**: Create `constants/messages.py` for centralized error messages.

---

## 3. Naming Smells

### NS-1: Inconsistent Naming Convention

**Examples**:
- `user_key` vs `userKey` (mixed snake_case and camelCase)
- `book_id` vs `bookId` in API responses

**Recommendation**: Standardize on snake_case for Python, camelCase for Dart/JSON.

### NS-2: Vague Variable Names

**File**: `apps/api/src/services/orchestrator.py`

```python
result = await self._call_llm(prompt)
data = json.loads(result)
```

**Recommendation**: Use descriptive names like `llm_response`, `story_data`.

---

## 4. Design Smells

### DES-1: God Class - `Orchestrator`

**File**: `apps/api/src/services/orchestrator.py`

**Problem**: Orchestrator knows too much and does too much.

**Recommendation**: Consider splitting into:
- `StoryGenerator`
- `ImageGenerator`
- `BookPackager`

### DES-2: Missing Abstraction - Storage

**File**: `apps/api/src/services/storage.py`

**Problem**: Direct S3/Minio coupling, no interface abstraction.

**Recommendation**: Create `StorageInterface` for easier testing and provider switching.

### DES-3: Tight Coupling - LLM Provider

**File**: `apps/api/src/services/llm.py`

**Problem**: Provider-specific code mixed with business logic.

**Recommendation**: Use strategy pattern for LLM providers.

### DES-4: Missing Domain Events

**Problem**: State changes not broadcasted, makes extension difficult.

**Recommendation**: Implement event system for job status changes.

### DES-5: Anemic Domain Model

**Problem**: Models are mostly data containers, logic lives in services.

**Recommendation**: Consider moving some behavior into model classes.

---

## 5. Maintainability Smells

### MS-1: Magic Numbers

**Files**: Multiple

```python
pages = 8  # Why 8?
timeout = 90  # Why 90?
max_retries = 3  # Why 3?
```

**Recommendation**: Define named constants in config or constants file.

### MS-2: Missing Type Hints

**Files**: Some service methods

```python
def process_image(self, data):  # Missing types
    pass
```

**Recommendation**: Add type hints for better IDE support and documentation.

### MS-3: Outdated Comments

**Files**: Various

```python
# TODO: implement this  <- But it's implemented
# FIXME: temporary fix <- From 6 months ago
```

**Recommendation**: Clean up or update stale comments.

### MS-4: Test Data Coupling

**File**: `apps/api/tests/`

**Problem**: Tests use production-like data that's hard to maintain.

**Recommendation**: Use factory patterns (e.g., Factory Boy) for test data.

---

## 6. Priority Matrix

| ID | Smell | Impact | Effort | Priority |
|----|-------|--------|--------|----------|
| CS-1 | Long Method | High | Medium | P2 |
| CS-4 | Multiple Responsibility | High | High | P3 |
| DS-1 | Repeated User Key | Medium | Low | DONE |
| DS-2 | Similar Validation | Low | Medium | P4 |
| DES-1 | God Class | High | High | P3 |
| DES-2 | Missing Storage Interface | Medium | Medium | P3 |
| MS-1 | Magic Numbers | Medium | Low | P2 |
| MS-2 | Missing Type Hints | Low | Medium | P4 |

---

## 7. Refactoring Roadmap

### Phase 1 (v0.2.1) - Quick Wins
- [ ] Extract magic numbers to constants
- [ ] Add missing type hints to public APIs
- [ ] Clean up TODO/FIXME comments

### Phase 2 (v0.3) - Structural Improvements
- [ ] Split Orchestrator into smaller services
- [ ] Create storage interface abstraction
- [ ] Implement LLM provider strategy pattern

### Phase 3 (v0.4) - Architecture Enhancements
- [ ] Add domain events system
- [ ] Implement proper dependency injection
- [ ] Split mobile API client

---

## 8. Technical Debt Estimate

| Category | Hours |
|----------|-------|
| Code Cleanup | 8 |
| Refactoring | 24 |
| Architecture | 40 |
| **Total** | 72 |

---

*Note: This report identifies code smells but does not block production release. These are improvement opportunities for future sprints.*

---

*Generated by Code Analysis Script v1.0*
