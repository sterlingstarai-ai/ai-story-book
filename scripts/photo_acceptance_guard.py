"""Opt-in photo acceptance HTTP guard; never imported by the product runtime.

The operator supplies estimated per-request reservations as a stop-new-requests
criterion. Neither reservations nor usage estimates guarantee a final billing cap
or replace an invoice. Reported usage settles its request's estimate; unknown or
in-flight usage retains the reservation. All attempted requests retain their count.
Only approved model identifiers, counters and numeric usage enter the journal;
policy evidence, photos, prompts, credentials and provider error bodies never do.
"""

import base64
import binascii
from decimal import Decimal, InvalidOperation
import fcntl
from fractions import Fraction
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import time
import warnings

import httpx
from PIL import Image, UnidentifiedImageError

from live_acceptance_guard import append_event

JOURNAL_VERSION = 3
LLM_MODELS = frozenset({"gpt-6-astra", "gpt-5.6-sol"})
IMAGE_MODEL = "gpt-image-2"
# One avatar + thirteen book illustrations + up to three single-attempt repairs.
# Each request still reserves against the unchanged operator-provided money cap.
REQUEST_LIMITS = {"llm": 16, "image": 17}
IMAGE_SIZES = frozenset({"1024x1024", "768x1024", "1024x768", "720x1280", "1280x720"})
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_IMAGES = 2  # Approved character/current page, then the owned book cover.
MAX_RESPONSE_BYTES = 40 * 1024 * 1024
MAX_PROMPT_CHARS = 5000
RESPONSES_URL = "https://api.openai.com/v1/responses"
IMAGE_URL = "https://api.openai.com/v1/images/edits"
MODEL_FIELDS = ("llm_model", "photo_analysis_model", "image_model")
MONEY_FIELDS = ("max_budget_usd", "llm_request_reservation_usd", "image_request_reservation_usd")
SAFE_ERROR_FIELDS = {
    "code": frozenset({"invalid_api_key", "missing_api_key", "insufficient_permissions", "permission_denied",
                       "organization_verification_required", "model_not_found", "insufficient_quota",
                       "billing_hard_limit_reached", "rate_limit_exceeded", "invalid_parameter", "unsupported_parameter"}),
    "type": frozenset({"authentication_error", "permission_error", "invalid_request_error",
                       "rate_limit_error", "server_error", "insufficient_quota"}),
    "param": frozenset({"model", "image", "image[]", "quality", "size", "n", "input_fidelity", "prompt"}),
}


def safe_provider_error(body):
    """Only exact owned enum values; provider messages may echo credentials."""
    error = body.get("error") if type(body) is dict else None
    if type(error) is not dict:
        return {}
    return {field: error[field] for field, allowed in SAFE_ERROR_FIELDS.items()
            if type(error.get(field)) is str and error[field] in allowed}


def _invalid(code):
    return RuntimeError("LIVE_PHOTO_" + code)


def _money(value):
    if type(value) not in (int, float):
        raise _invalid("INVALID_MONEY")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise _invalid("INVALID_MONEY") from None
    if not amount.is_finite() or amount <= 0 or amount > 10:
        raise _invalid("INVALID_MONEY")
    return Fraction(amount)


def validate_policy(policy):
    """Validate six execution fields; private evidence is owned by the runner."""
    if type(policy) is not dict:
        raise _invalid("INVALID_POLICY")
    if (any(type(policy.get(field)) is not str for field in MODEL_FIELDS)
            or policy.get("llm_model") not in LLM_MODELS
            or policy.get("photo_analysis_model") not in LLM_MODELS
            or policy.get("image_model") != IMAGE_MODEL):
        raise _invalid("INVALID_MODEL_SELECTION")
    budget = _money(policy.get("max_budget_usd"))
    for field in MONEY_FIELDS[1:]:
        if _money(policy.get(field)) > budget:
            raise _invalid("INVALID_MONEY")
    return {field: policy[field] for field in (*MODEL_FIELDS, *MONEY_FIELDS)}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("INVALID_JSON")
        result[key] = value
    return result


def _private_stream(path, *, create=False):
    flags = (os.O_RDWR | os.O_APPEND if create else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT
    try:
        fd = os.open(path, flags, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            os.close(fd)
            raise _invalid("PRIVATE_FILE_REQUIRED")
        return os.fdopen(fd, "a+" if create else "r", encoding="utf-8")
    except OSError:
        raise _invalid("PRIVATE_FILE_REQUIRED") from None


def load_policy(path):
    try:
        with _private_stream(path) as stream:
            raw = stream.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise _invalid("INVALID_POLICY")
        return validate_policy(json.loads(raw, object_pairs_hook=_unique_object))
    except (ValueError, UnicodeError):
        raise _invalid("INVALID_POLICY") from None


def _fingerprint(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _read_ledger(stream, policy, fingerprint):
    requests, responses, settlements = {}, [], {}
    counts = {role: 0 for role in REQUEST_LIMITS}
    try:
        for line in stream:
            event = json.loads(line, object_pairs_hook=_unique_object)
            if type(event) is not dict or event.get("kind") not in {"request", "response"}:
                raise _invalid("INVALID_JOURNAL")
            if event["kind"] == "response":
                responses.append(event)
                continue
            role, index = event.get("role"), event.get("request_index")
            if (type(role) is not str or role not in REQUEST_LIMITS
                    or type(index) is not int or index != counts[role] + 1
                    or event.get("journal_version") != JOURNAL_VERSION
                    or event.get("policy_fingerprint") != fingerprint
                    or event.get("provider") != "openai"):
                raise _invalid("INVALID_JOURNAL")
            expected = ({policy["llm_model"], policy["photo_analysis_model"]}
                        if role == "llm" else {policy["image_model"]})
            if type(event.get("model")) is not str or event["model"] not in expected:
                raise _invalid("INVALID_JOURNAL")
            reservation = _money(event.get("reservation_usd"))
            if reservation != _money(policy[f"{role}_request_reservation_usd"]):
                raise _invalid("INVALID_JOURNAL")
            requests[role, index] = event
            counts[role] += 1
        for event in responses:
            role, index = event.get("role"), event.get("request_index")
            if type(role) is not str or type(index) is not int:
                raise _invalid("INVALID_JOURNAL")
            key = role, index
            if (key not in requests or event.get("journal_version") != JOURNAL_VERSION
                    or event.get("provider") != "openai"
                    or event.get("model") != requests[key]["model"]):
                raise _invalid("INVALID_JOURNAL")
            # One terminal response per attempted request. Duplicate delivery
            # cannot reduce its estimate or count its usage a second time.
            if key in settlements:
                continue
            estimate = event.get("estimated_usage_usd")
            if estimate is None:
                settlements[key] = None
                continue
            if type(estimate) not in (int, float):
                raise _invalid("INVALID_JOURNAL")
            value = Decimal(str(estimate))
            if (not value.is_finite() or value < 0
                    or estimate != estimate_usage_usd(event["model"], event.get("usage"))):
                raise _invalid("INVALID_JOURNAL")
            settlements[key] = Fraction(value)
    except (ValueError, UnicodeError):
        raise _invalid("INVALID_JOURNAL") from None
    completed, unsettled = Fraction(0), Fraction(0)
    for key, event in requests.items():
        estimate = settlements.get(key)
        if estimate is None:
            unsettled += _money(event["reservation_usd"])
        else:
            completed += estimate
    return counts, completed, unsettled


def reserve_request(path, policy, role, model):
    """One durable flock critical section covers both shared counts and money."""
    policy = validate_policy(policy)
    expected = ({policy["llm_model"], policy["photo_analysis_model"]}
                if role == "llm" else {policy["image_model"]})
    if type(role) is not str or role not in REQUEST_LIMITS or type(model) is not str or model not in expected:
        raise _invalid("MODEL_MISMATCH")
    fingerprint = _fingerprint(policy)
    amount = _money(policy[f"{role}_request_reservation_usd"])
    budget = _money(policy["max_budget_usd"])
    with _private_stream(path, create=True) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        counts, completed_estimate, unsettled = _read_ledger(stream, policy, fingerprint)
        total = completed_estimate + unsettled
        if counts[role] >= REQUEST_LIMITS[role]:
            raise _invalid("REQUEST_LIMIT")
        if completed_estimate >= budget:
            raise _invalid("USAGE_ESTIMATE_LIMIT")
        if total + amount > budget:
            raise _invalid("BUDGET_LIMIT")
        event = {
            "kind": "request", "journal_version": JOURNAL_VERSION,
            "role": role, "provider": "openai", "model": model,
            "request_index": counts[role] + 1, "reservation_usd": float(amount),
            "reserved_total_usd": float(total + amount), "max_budget_usd": float(budget),
            "completed_estimated_usd": float(completed_estimate),
            "unsettled_reserved_usd": float(unsettled + amount),
            "policy_fingerprint": fingerprint,
        }
        stream.write(json.dumps(event, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return event


def _image_size(raw, mime=None):
    formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if (image.format not in formats.values()
                        or (mime is not None and image.format != formats.get(mime))
                        or getattr(image, "is_animated", False)
                        or min(image.size) < 1 or max(image.size) > 8192
                        or image.width * image.height > 16_777_216):
                    raise _invalid("INVALID_IMAGE")
                size = {"width": image.width, "height": image.height}
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image.load()
        return size
    except (ValueError, UnidentifiedImageError, OSError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _invalid("INVALID_IMAGE") from None


def image_dimensions(body):
    """Only decode inline output; never fetch a provider-supplied URL."""
    if type(body) is not dict or type(body.get("data")) is not list or len(body["data"]) != 1:
        return [], False
    try:
        encoded = body["data"][0].get("b64_json")
        if not isinstance(encoded, str) or not encoded or len(encoded) > 32 * 1024 * 1024:
            return [], False
        return [_image_size(base64.b64decode(encoded, validate=True))], True
    except (AttributeError, TypeError, ValueError, binascii.Error, RuntimeError):
        return [], False


def _validate_request(client, url, kwargs, policy):
    if (str(url) not in {RESPONSES_URL, IMAGE_URL}
            or kwargs.get("params") or client.params
            or kwargs.get("follow_redirects", client.follow_redirects) is not False):
        raise _invalid("UNEXPECTED_POST")
    if str(url) == RESPONSES_URL:
        payload = kwargs.get("json")
        if type(payload) is not dict or any(kwargs.get(field) is not None for field in ("data", "files", "content")):
            raise _invalid("INVALID_PAYLOAD")
        if (type(payload.get("model")) is not str
                or payload.get("model") not in {policy["llm_model"], policy["photo_analysis_model"]}):
            raise _invalid("MODEL_MISMATCH")
        tokens = payload.get("max_output_tokens")
        if type(tokens) is not int or not 1 <= tokens <= 16000:
            raise _invalid("TOKEN_LIMIT")
        if (payload.get("store") is not False
                or payload.get("background", False) is not False
                or payload.get("stream", False) is not False
                or payload.get("tools") not in (None, [])
                or payload.get("service_tier", "default") != "default"):
            raise _invalid("OPENAI_OPTIONS")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        except (TypeError, ValueError, UnicodeError):
            raise _invalid("INVALID_PAYLOAD") from None
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise _invalid("PAYLOAD_LIMIT")
        return "llm", payload["model"]
    payload, files = kwargs.get("data"), kwargs.get("files")
    if (type(payload) is not dict or set(payload) != {"model", "prompt", "n", "size", "quality"}
            or any(kwargs.get(field) is not None for field in ("json", "content"))):
        raise _invalid("INVALID_PAYLOAD")
    if type(files) is dict and set(files) == {"image[]"}:
        references = [files["image[]"]]
    elif (type(files) is list and 1 <= len(files) <= MAX_REFERENCE_IMAGES
          and all(type(entry) is tuple and len(entry) == 2 and entry[0] == "image[]" for entry in files)):
        references = [entry[1] for entry in files]
    else:
        raise _invalid("INVALID_PAYLOAD")
    if payload["model"] != policy["image_model"]:
        raise _invalid("MODEL_MISMATCH")
    if ((type(payload["n"]) is not int or payload["n"] != 1) and payload["n"] != "1"):
        raise _invalid("IMAGE_COUNT")
    if type(payload["size"]) is not str or payload["size"] not in IMAGE_SIZES:
        raise _invalid("IMAGE_SIZE")
    if payload["quality"] != "medium":
        raise _invalid("IMAGE_QUALITY")
    prompt = payload["prompt"]
    if type(prompt) is not str or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise _invalid("PROMPT_LIMIT")
    for file in references:
        if type(file) is not tuple or len(file) != 3:
            raise _invalid("INVALID_IMAGE")
        filename, raw, mime = file
        if (type(filename) is not str or not 1 <= len(filename) <= 120
                or any(c in filename for c in ("/", "\\", "\r", "\n", "\x00"))
                or type(raw) is not bytes or not 0 < len(raw) < MAX_IMAGE_BYTES
                or type(mime) is not str or mime not in {"image/png", "image/jpeg", "image/webp"}):
            raise _invalid("INVALID_IMAGE")
        _image_size(raw, mime)
    return "image", payload["model"]


def estimate_usage_usd(model, usage):
    """Operator-provided reference rates; missing/other-model usage stays unknown.

Sol: input 4 / output 20 USD per million tokens. GPT Image 2: estimate all
input at 8 and output at 30 USD per million, without guessing its input split.
This ignores possible discounts and is not a statement about billed charges.
"""
    rates = {"gpt-5.6-sol": (4, 20), "gpt-image-2": (8, 30)}
    if model not in rates or type(usage) is not dict:
        return None
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
        return None
    input_rate, output_rate = rates[model]
    return float(Fraction(usage["input_tokens"] * input_rate + usage["output_tokens"] * output_rate, 1_000_000))


def _response_event(reservation, response, started):
    event = {key: reservation[key] for key in ("journal_version", "role", "provider", "model", "request_index")}
    event.update(kind="response", seconds=round(time.monotonic() - started, 3),
                 failed=response is None or response.status_code >= 400,
                 estimated_usage_usd=None)
    if reservation["role"] == "image":
        event.update(image_dimensions=[], image_dimensions_complete=False)
    if response is None:
        return event
    event["http_status"] = response.status_code
    try:
        body = response.json()
        if response.status_code >= 400:
            diagnostic = safe_provider_error(body)
            if diagnostic:
                event["provider_error"] = diagnostic
        usage = body.get("usage", {})
        if type(usage) is not dict:
            usage = {}
        names = ("input_tokens", "output_tokens", "total_tokens")
        event["usage"] = {key: usage[key] for key in names if type(usage.get(key)) is int and usage[key] >= 0}
        for detail in ("input_tokens_details", "output_tokens_details"):
            values = usage.get(detail, {})
            if type(values) is dict:
                clean = {key: values[key] for key in ("cached_tokens", "text_tokens", "image_tokens", "reasoning_tokens")
                         if type(values.get(key)) is int and values[key] >= 0}
                if clean:
                    event["usage"][detail] = clean
        event["estimated_usage_usd"] = estimate_usage_usd(reservation["model"], event["usage"])
        if reservation["role"] == "image":
            sizes, complete = image_dimensions(body)
            event.update(image_dimensions=sizes, image_dimensions_complete=complete)
    except (ValueError, AttributeError, TypeError):
        pass
    return event


def install():
    """Fail before patching either client if policy/runtime selection is invalid."""
    try:
        journal = Path(os.environ["LIVE_ACCEPTANCE_JOURNAL"])
        policy = load_policy(os.environ["LIVE_PHOTO_POLICY_FILE"])
    except KeyError:
        raise _invalid("MISSING_CONFIGURATION") from None
    required = {
        "LLM_PROVIDER": "openai", "LLM_MODEL": policy["llm_model"],
        "PHOTO_ANALYSIS_PROVIDER": "openai", "PHOTO_ANALYSIS_MODEL": policy["photo_analysis_model"],
        "IMAGE_PROVIDER": "openai", "IMAGE_MODEL": policy["image_model"],
        "OPENAI_IMAGE_QUALITY": "medium",
        "PHOTO_PROCESSING_ENABLED": "true", "ILLUSTRATION_QUALITY_ENABLED": "true",
        "LIVE_ACCEPTANCE_PAGE_COUNT": "12",
    }
    if any(os.environ.get(key) != value for key, value in required.items()):
        raise _invalid("CONFIGURATION_MISMATCH")
    with _private_stream(journal, create=True):
        pass
    identity = (str(journal.resolve()), _fingerprint(policy))
    existing = getattr(httpx.AsyncClient.post, "_photo_acceptance_guard", None)
    if existing is not None:
        if existing != identity or getattr(httpx.Client.post, "_photo_acceptance_guard", None) != identity:
            raise _invalid("GUARD_ALREADY_INSTALLED")
        return
    original_async, original_sync = httpx.AsyncClient.post, httpx.Client.post

    async def measured_async(self, url, **kwargs):
        role, model = _validate_request(self, url, kwargs, policy)
        reservation = reserve_request(journal, policy, role, model)
        response, started = None, time.monotonic()
        try:
            response = await original_async(self, url, **kwargs)
            return response
        finally:
            append_event(journal, _response_event(reservation, response, started))

    def measured_sync(self, url, **kwargs):
        role, model = _validate_request(self, url, kwargs, policy)
        reservation = reserve_request(journal, policy, role, model)
        response, started = None, time.monotonic()
        try:
            response = original_sync(self, url, **kwargs)
            return response
        finally:
            append_event(journal, _response_event(reservation, response, started))

    measured_async._photo_acceptance_guard = identity
    measured_sync._photo_acceptance_guard = identity
    httpx.AsyncClient.post, httpx.Client.post = measured_async, measured_sync
