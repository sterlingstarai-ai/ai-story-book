#!/usr/bin/env python3
"""Explicit paid 15-book synthetic matrix, two isolated books at a time.

The existing live-book guard enforces per-run request limits. Stops launching new
books after any failure or estimated matrix spend reaches its $11.50 image
threshold or explicit text threshold ($2 by default, at most $10). Estimates are
not a provider-enforced dollar cap or an invoice.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import math
from pathlib import Path
import subprocess
import sys

from run_runtime_e2e import ROOT, require, clean_environment
from run_live_book_acceptance import (
    load_runtime_config, load_reader_profile, data_scope, quality_gate_environment,
)
from live_acceptance_guard import IMAGE_MODELS, LLM_MODELS, JOURNAL_VERSION, request_limits

# Standard USD per million tokens, verified 2026-09-06. OpenAI estimates
# conservatively charge cached input at the base rate; these are not invoices.
# https://platform.claude.com/docs/en/about-claude/pricing
# https://developers.openai.com/api/docs/models/gpt-6-astra
# https://developers.openai.com/api/docs/models/gpt-5.6-sol
# https://ai.google.dev/gemini-api/docs/pricing
TEXT_PRICES = {
    ("anthropic", "claude-sonnet-5"): (2, 10),
    ("anthropic", "claude-opus-5"): (5, 25),
    ("openai", "gpt-6-astra"): (10, 50),
    ("openai", "gpt-5.6-sol"): (4, 20),
}
IMAGE_PRICES = {
    ("gemini", "gemini-3-pro-image"): (2, 12, 120),
    ("gemini", "gemini-3.1-flash-image"): (0.5, 3, 60),
}
ESTIMATE_BASIS = {
    "pricing_checked_at": "2026-09-06",
    "text": "Selected model standard token prices; cached input charged at base rate",
    "image": "Every response image, including rejected/replaced candidates, uses recorded dimensions; verified 896x1200 = 1120 output tokens each; legacy final-file fallback only for old journals",
    "limit": "Estimated completed usage, not an invoice or provider-enforced dollar cap; concurrent in-flight work can exceed thresholds",
}


def text_spend_threshold(value):
    """Require a finite, explicitly bounded threshold before any paid work."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Text threshold must be greater than $0 and at most $10") from None
    if not math.isfinite(amount) or not 0 < amount <= 10:
        raise argparse.ArgumentTypeError("Text threshold must be greater than $0 and at most $10")
    return amount


def selected_prices(result):
    models = result.get("models", {})
    providers = result.get("providers", {})
    # Older acceptance reports predate the provider field. Only exact known
    # model identities may supply that missing value, never a default price.
    llm_model, image_model = models.get("llm"), models.get("image")
    llm = (providers.get("llm", LLM_MODELS.get(llm_model)), llm_model)
    image = (providers.get("image", "gemini" if image_model in IMAGE_MODELS else None), image_model)
    require(llm in TEXT_PRICES and image in IMAGE_PRICES, "COST_MODEL_UNSUPPORTED")
    return {"llm": llm, "image": image}


def token_count(usage, name, *, required=False):
    value = usage.get(name, None if required else 0)
    require(type(value) is int and value >= 0, "COST_USAGE_UNAVAILABLE")
    return value


def costs(directory):
    text_cost = image_cost = 0.0
    result_path = directory / "result.json"
    require(result_path.is_file(), "COST_RESULT_UNAVAILABLE")
    result = json.loads(result_path.read_text())
    identities = selected_prices(result)
    text_input, text_output = TEXT_PRICES[identities["llm"]]
    image_input, image_text, image_output = IMAGE_PRICES[identities["image"]]
    journal = directory / "provider-usage.jsonl"
    if not journal.exists():
        raise RuntimeError("COST_JOURNAL_UNAVAILABLE")
    images = result.get("images", [])
    entries = [json.loads(line) for line in journal.read_text().splitlines()]
    version = result.get("provider_journal_version", 0)
    require(type(version) is int and version >= 0, "COST_JOURNAL_VERSION_UNSUPPORTED")
    response_dimensions = version >= JOURNAL_VERSION or any(
        "image_dimensions" in entry for entry in entries if entry.get("role") == "image")
    image_responses = 0
    for entry in entries:
        if entry["kind"] != "response":
            continue
        role = entry.get("role")
        require(role in identities, "COST_ROLE_UNSUPPORTED")
        provider, model = identities[role]
        require(entry.get("provider", provider) == provider and entry.get("model", model) == model,
                "COST_MODEL_MISMATCH")
        usage = entry.get("usage", {})
        require(isinstance(usage, dict), "COST_USAGE_UNAVAILABLE")
        if role == "llm":
            required = entry.get("http_status") == 200
            text_cost += (token_count(usage, "input_tokens", required=required) * text_input
                          + token_count(usage, "output_tokens", required=required) * text_output) / 1e6
        elif entry.get("http_status") == 200 or (response_dimensions and usage):
            if response_dimensions:
                require(entry.get("image_dimensions_complete") is True,
                        "COST_IMAGE_DIMENSIONS_UNAVAILABLE")
                sizes = entry.get("image_dimensions")
                require(isinstance(sizes, list), "COST_IMAGE_DIMENSIONS_UNAVAILABLE")
            else:
                # Historical runs did not record response dimensions and made
                # no replacement requests. Do not use this for mixed/new journals.
                require(image_responses < len(images), "COST_IMAGE_DIMENSIONS_UNAVAILABLE")
                sizes = [images[image_responses]]
            for size in sizes:
                require(isinstance(size, dict) and set(size) >= {"width", "height"}
                        and type(size["width"]) is int and type(size["height"]) is int
                        and (size["width"], size["height"]) == (896, 1200),
                        "COST_IMAGE_DIMENSIONS_UNSUPPORTED")
            image_responses += 1
            output_tokens = 1120 * len(sizes)
            required = entry.get("http_status") == 200
            image_cost += (token_count(usage, "promptTokenCount", required=required) * image_input
                           + output_tokens * image_output
                           + (max(0, token_count(usage, "candidatesTokenCount", required=required) - output_tokens)
                              + token_count(usage, "thoughtsTokenCount")) * image_text) / 1e6
    return text_cost, image_cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--llm-env-file", type=Path)
    parser.add_argument("--reader-profile-file", type=Path,
                        help="Optional private name/gender profile; exact age must be omitted for a three-age matrix")
    parser.add_argument("--llm-model", choices=tuple(LLM_MODELS))
    parser.add_argument("--image-model", choices=sorted(IMAGE_MODELS), default="gemini-3-pro-image")
    parser.add_argument("--text-spend-threshold-usd", type=text_spend_threshold, default=2.0,
                        help="Stop starting books at this completed text-cost estimate; default $2, max $10. In-flight work can exceed it.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    require(directory.is_relative_to((ROOT / "docs/acceptance").resolve())
            and not directory.exists(), "Use a new acceptance subdirectory")
    config = load_runtime_config(args)
    quality_gate_environment(4, config)
    reader_profile = load_reader_profile(args.reader_profile_file, age=None)
    require(reader_profile is None or reader_profile.get("character_age") is None,
            "Matrix reader profile must omit exact age to preserve all three age bands")
    directory.mkdir(parents=True, mode=0o700)
    cases = [(age, case) for age in ("3-5", "5-7", "7-9") for case in range(1, 6)]
    report = {"status": "running", "planned_books": 15, "pages_per_book": 4,
              "model": config.image_model, "completed": [], "quality_scored": False,
              "models": {"llm": config.llm_model, "image": config.image_model},
              "providers": {"llm": config.llm_provider, "image": config.image_provider},
              "illustration_quality_enabled": True,
              "request_limits_per_book": request_limits(4, True),
              "provider_journal_version": JOURNAL_VERSION,
              **data_scope(reader_profile),
              "spend_thresholds_usd": {"llm": args.text_spend_threshold_usd, "image": 11.5},
              "estimate_basis": ESTIMATE_BASIS}

    def save():
        path = directory / "matrix.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    def execute(age, case):
        label = f"age-{age}-case-{case}"
        output = directory / label
        llm_args = ["--llm-model", config.llm_model]
        if args.llm_env_file is not None:
            llm_args += ["--llm-env-file", str(args.llm_env_file.resolve())]
        if args.reader_profile_file is not None:
            llm_args += ["--reader-profile-file", str(args.reader_profile_file.resolve())]
        log_path = directory / f"{label}.log"
        with log_path.open("w") as log:
            log_path.chmod(0o600)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/run_live_book_acceptance.py"),
                "--live", "--env-file", str(args.env_file.resolve()), "--output-dir", str(output),
                "--age", age, "--case", str(case), "--page-count", "4",
                "--image-model", config.image_model, *llm_args], cwd=ROOT, env=clean_environment(),
                stdout=log, stderr=subprocess.STDOUT, timeout=900)
        text_cost, image_cost = costs(output)
        return {"case": label, "status": "passed" if result.returncode == 0 else "failed",
                "llm_estimate_usd": round(text_cost, 5), "image_estimate_usd": round(image_cost, 5)}

    save()
    failed = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        active = {executor.submit(execute, *cases.pop(0)) for _ in range(2)}
        while active:
            done, active = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    outcome = future.result()
                except Exception as error:
                    outcome = {"status": "failed", "failure": type(error).__name__}
                report["completed"].append(outcome)
                failed = failed or outcome["status"] != "passed"
                print(f"Completed {len(report['completed'])}/15: {outcome.get('case', 'run')} {outcome['status']}", flush=True)
            text_total = sum(item.get("llm_estimate_usd", 0) for item in report["completed"])
            image_total = sum(item.get("image_estimate_usd", 0) for item in report["completed"])
            report["estimates_usd"] = {"llm": round(text_total, 4), "image": round(image_total, 4)}
            if text_total >= args.text_spend_threshold_usd or image_total >= 11.5:
                failed = True
                report["spend_threshold_reached"] = True
            save()
            while cases and len(active) < 2 and not failed:
                active.add(executor.submit(execute, *cases.pop(0)))
    report["status"] = "passed" if not failed and len(report["completed"]) == 15 else "failed"
    report["unstarted_cases"] = len(cases)
    save()
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
