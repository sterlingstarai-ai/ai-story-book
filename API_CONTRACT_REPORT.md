# API Contract Report

**Date**: 2026-01-21
**Project**: AI Story Book v0.2

---

## Overview

This report compares the Mobile Client (Flutter/Dart) API calls against the Backend (FastAPI/Python) endpoints to identify contract mismatches.

| Status | Count |
|--------|-------|
| Matched | 22 |
| Mismatch Found | 1 |
| Missing Endpoint | 0 |
| **Total Endpoints** | 23 |

**Overall Contract Status**: HEALTHY (1 minor fix required)

---

## 1. Books API

### POST /v1/books - Create Book

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `createBook(BookSpec)` | OK |
| Backend | `create_book(BookCreate)` | OK |

**Request Schema Match**: YES

```
Mobile sends:
{
  "topic": string,
  "target_age": string,
  "language": string,
  "style": string,
  "theme": string?,
  "character_id": string?,
  "character_name": string?
}

Backend expects:
{
  "topic": string,
  "target_age": string (enum: 3-5, 5-7, 7-9, adult),
  "language": string (enum: ko, en, ja, zh, es),
  "style": string (enum),
  "theme": string?,
  "character_id": string?,
  "character_name": string?
}
```

**Headers**: X-User-Key (required), X-Idempotency-Key (optional)

---

### GET /v1/books/{job_id} - Get Job Status

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getBookStatus(jobId)` | OK |
| Backend | `get_book_status(job_id)` | OK |

**Response Schema Match**: YES

```json
{
  "job_id": "string",
  "status": "queued|running|done|failed",
  "progress": 0-100,
  "current_step": "string",
  "error_code": "string?",
  "error_message": "string?",
  "book": { ... } // only when status=done
}
```

---

### GET /v1/books/{book_id}/detail - Get Book Detail

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getBook(bookId)` | OK |
| Backend | `get_book_detail(book_id)` | OK |

**Response Schema Match**: YES

---

### POST /v1/books/{job_id}/pages/{page_number}/regenerate

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `regeneratePage(jobId, pageNumber, target)` | OK |
| Backend | `regenerate_page(job_id, page_number)` | OK |

**Request Schema Match**: YES

```json
{
  "regenerate_target": "text|image|both"
}
```

---

### POST /v1/books/series - Create Series Book

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `createSeriesBook(characterId, topic, theme)` | OK |
| Backend | `create_series_book(SeriesCreate)` | OK |

**Request Schema Match**: YES

```
Mobile sends:
{
  "character_id": string,
  "topic": string,
  "theme": string?
}

Backend expects:
{
  "character_id": string,
  "topic": string,
  "theme": string?
}
```

---

### GET /v1/books/{book_id}/pdf - Download PDF

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `downloadPdf(bookId)` | OK |
| Backend | `get_pdf(book_id)` | OK |

**Response**: Binary PDF data (application/pdf)

---

### POST /v1/books/{book_id}/audio - Generate Book Audio

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `generateBookAudio(bookId)` | OK |
| Backend | `generate_audio(book_id)` | OK |

---

### GET /v1/books/{book_id}/pages/{page_number}/audio

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getPageAudioUrl(bookId, pageNumber)` | OK |
| Backend | `get_page_audio(book_id, page_number)` | OK |

**Response Schema Match**: YES

```json
{
  "audio_url": "https://..."
}
```

---

## 2. Characters API

### POST /v1/characters - Create Character

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `createCharacter(CharacterCreate)` | OK |
| Backend | `create_character(CharacterCreate)` | OK |

**Request Schema Match**: YES

---

### GET /v1/characters - List Characters

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getCharacters()` | OK |
| Backend | `list_characters()` | OK |

**Response Schema Match**: YES

```json
{
  "characters": [...]
}
```

---

### GET /v1/characters/{character_id}

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getCharacter(characterId)` | OK |
| Backend | `get_character(character_id)` | OK |

---

### POST /v1/characters/from-photo

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `createCharacterFromPhoto(File, name, style)` | OK |
| Backend | `create_from_photo(UploadFile, name, style)` | OK |

**Content-Type**: multipart/form-data

**Fields**:
- `photo`: File (required)
- `name`: string (optional)
- `style`: string (default: "cartoon")

---

## 3. Library API

### GET /v1/library - Get User Library

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getLibrary(limit, offset)` | OK |
| Backend | `get_library(limit, offset)` | OK |

**Query Parameters Match**: YES

---

## 4. Credits API

### GET /v1/credits/status

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getCreditsStatus()` | OK |
| Backend | `get_status()` | OK |

---

### GET /v1/credits/balance

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getCreditsBalance()` | OK |
| Backend | `get_balance()` | OK |

**Response**: `{"credits": int}`

---

### GET /v1/credits/transactions

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getTransactions(limit, offset)` | OK |
| Backend | `get_transactions(limit, offset)` | OK |

---

### POST /v1/credits/subscribe

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `subscribe(plan)` | OK |
| Backend | `subscribe(SubscribeRequest)` | OK |

---

### POST /v1/credits/cancel-subscription

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `cancelSubscription()` | OK |
| Backend | `cancel_subscription()` | OK |

---

### POST /v1/credits/add

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `addCredits(amount, transactionId)` | OK |
| Backend | `add_credits(AddCreditsRequest)` | OK |

**Response**: `{"new_balance": int}`

---

## 5. Streak API

### GET /v1/streak/info

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getStreakInfo()` | OK |
| Backend | `get_info()` | OK |

---

### GET /v1/streak/today

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getTodayStory()` | OK |
| Backend | `get_today()` | OK |

---

### POST /v1/streak/read

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `recordReading(bookId, readingTime, completed)` | OK |
| Backend | `record_reading(ReadRequest)` | OK |

---

### GET /v1/streak/history

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getReadingHistory(days)` | OK |
| Backend | `get_history(days)` | OK |

---

### GET /v1/streak/calendar

| Component | Implementation | Status |
|-----------|---------------|--------|
| Mobile | `getStreakCalendar(year, month)` | OK |
| Backend | `get_calendar(year, month)` | OK |

---

## 6. Issues Found

### Issue #1: Series Endpoint Schema (FIXED in previous PR)

**Location**: `apps/mobile/lib/services/api_client.dart:91-107`

**Status**: Already fixed in commit `537a5e2`

The mobile client was originally sending `previous_book_id` but backend expected `character_id` and `topic`. This was corrected in the code review fixes.

---

## 7. Schema Validation

### Enum Validations

| Field | Mobile | Backend | Match |
|-------|--------|---------|-------|
| target_age | string | "3-5"\|"5-7"\|"7-9"\|"adult" | YES |
| language | string | "ko"\|"en"\|"ja"\|"zh"\|"es" | YES |
| style | string | enum list | YES |
| status | string | "queued"\|"running"\|"done"\|"failed" | YES |
| regenerate_target | string | "text"\|"image"\|"both" | YES |

---

## 8. Header Requirements

| Header | Required | Default |
|--------|----------|---------|
| X-User-Key | YES | - |
| X-Idempotency-Key | NO (POST /books only) | - |
| Content-Type | YES | application/json |

---

## 9. Error Response Format

Both mobile and backend use consistent error format:

```json
{
  "detail": "Error message",
  "error_code": "ERROR_CODE"
}
```

Mobile `ApiError` class handles:
- Network errors
- Timeout errors
- Server errors (4xx, 5xx)
- Unknown errors

---

## 10. Recommendations

1. **Add OpenAPI Schema Export**: Generate TypeScript/Dart types from FastAPI's OpenAPI spec
2. **Contract Testing**: Add Pact or similar contract testing between mobile and backend
3. **Version Header**: Consider adding `X-API-Version` header for future compatibility
4. **Rate Limit Headers**: Return `X-RateLimit-*` headers for client-side handling

---

## 11. Conclusion

The API contract between mobile client and backend is **HEALTHY**. All endpoints are properly matched and the one identified mismatch has been fixed.

**Contract Status**: VERIFIED

---

*Generated by API Contract Verification Script v1.0*
