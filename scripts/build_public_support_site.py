"""Build app support pages locally or verify their publication over HTTPS."""

import argparse
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = {
    "site_url", "support_email", "support_contact_verified", "legal_copy_approved",
    "privacy_policy_file", "privacy_policy_sha256", "terms_of_service_file", "terms_of_service_sha256",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def public_host(host):
    require(bool(host) and len(host) <= 253 and "." in host and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in host.lower().split(".")), "PUBLIC_HOST_REQUIRED")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("PUBLIC_HOST_REQUIRED")
    require(not any(host == value or host.endswith("." + value) for value in
                    ("localhost", "local", "internal", "test", "invalid", "example", "example.com", "example.net", "example.org")),
            "PUBLIC_HOST_REQUIRED")


class LegalStatusParser(HTMLParser):
    """Each explicit legal-status tag must have one name and one approved value.

    Documents with no legal-status tag remain compatible with externally
    approved copies; the approval flag and matching digest are still required.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.unapproved = False

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        names = [value for key, value in attrs if key == "name"]
        if not any(value and value.strip().lower() == "legal-status" for value in names):
            return
        values = [value for key, value in attrs if key == "content"]
        if len(names) != 1 or len(values) != 1 or not values[0] or values[0].strip().lower() != "approved":
            self.unapproved = True


def production_inputs(config, config_path):
    require(set(config) == CONFIG_KEYS, "CONFIG_FIELDS_INVALID")
    require(config["support_contact_verified"] is True, "VERIFIED_SUPPORT_CONTACT_REQUIRED")
    require(config["legal_copy_approved"] is True, "APPROVED_POLICY_COPY_REQUIRED")
    raw_site = config["site_url"]
    require(isinstance(raw_site, str) and not re.search(r"\s", raw_site), "PUBLIC_HTTPS_SITE_REQUIRED")
    site = urlsplit(raw_site)
    require(site.scheme == "https" and site.netloc == site.hostname and site.path in ("", "/")
            and not site.query and not site.fragment, "PUBLIC_HTTPS_SITE_REQUIRED")
    public_host(site.hostname)
    email = config["support_email"]
    require(isinstance(email, str) and re.fullmatch(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+", email),
            "SUPPORT_EMAIL_INVALID")
    public_host(email.rsplit("@", 1)[1].lower())
    require(not email.lower().startswith(("noreply@", "no-reply@")), "REPLY_CAPABLE_SUPPORT_REQUIRED")
    policies = {}
    for name in ("privacy_policy", "terms_of_service"):
        source = (config_path.parent / config[name + "_file"]).resolve()
        require(source.is_file(), "APPROVED_POLICY_FILE_REQUIRED")
        data = source.read_bytes()
        require(0 < len(data) <= 500_000, "POLICY_FILE_SIZE_INVALID")
        require(hashlib.sha256(data).hexdigest() == config[name + "_sha256"], "POLICY_APPROVAL_HASH_MISMATCH")
        text = data.decode("utf-8")
        decoded = html.unescape(text)
        status = LegalStatusParser()
        status.feed(decoded)
        status.close()
        require(not status.unapproved, "POLICY_STILL_IN_REVIEW")
        compact = re.sub(r"[\x00-\x20]+", "", decoded)
        require(not re.search(r"<(script|iframe|form|object|embed)\b|\bon\w+\s*=", decoded, re.I)
                and not re.search(r"javascript:", compact, re.I),
                "POLICY_ACTIVE_CONTENT_REJECTED")
        policies[name] = data
    return email, policies


def document(title, body, *, preview):
    banner = '<div class="preview">비공개 검토본 · 실제 문의 접수와 정책 게시가 연결되기 전입니다.</div>' if preview else ""
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta name="robots" content="{'noindex,nofollow' if preview else 'index,follow'}"><title>{html.escape(title)} · AI 동화책</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/site.css"></head><body><a class="skip" href="#main">본문으로 건너뛰기</a>{banner}<header><a class="brand" href="/"><span class="mark" aria-hidden="true">✦</span>AI 동화책</a><nav aria-label="도움말"><a href="/support/">고객지원</a><a href="/delete-account/">데이터 삭제</a></nav></header><main id="main">{body}</main><footer><p>아이와 함께 읽는 이야기, 보호자가 관리하는 동화책.</p><a href="/privacy/">개인정보처리방침</a><a href="/terms/">이용약관</a><a href="/support/">고객지원</a></footer></body></html>'''


def build(config_path, output_dir, *, preview=False):
    config_path, output_dir = Path(config_path).resolve(), Path(output_dir).resolve()
    config = json.loads(config_path.read_text())
    email, policies = (None, {}) if preview else production_inputs(config, config_path)
    # Validate everything before creating any deployable output.
    require(not output_dir.exists(), "OUTPUT_ALREADY_EXISTS")
    if preview:
        require(output_dir.is_relative_to(ROOT / "docs/acceptance") or output_dir.is_relative_to(ROOT / "output"),
                "PREVIEW_REQUIRES_PRIVATE_OUTPUT")
    contact = (f'<a class="button" href="mailto:{html.escape(email, quote=True)}">{html.escape(email)}</a>'
               if email else '<p class="notice">지원 연락처 연결 전인 비공개 검토 화면입니다.</p>')
    delete_contact = (f'<a class="button" href="mailto:{html.escape(email, quote=True)}?subject={quote("AI 동화책 데이터 삭제 요청")}">이메일로 삭제 요청하기</a>'
                      if email else '<p class="notice">삭제 요청 연락처 연결 전인 비공개 검토 화면입니다.</p>')
    pages = {
        "": ("보호자 도움말", '''<p class="eyebrow">보호자 도움말</p><h1>아이의 이야기를<br>편안하게 관리하세요.</h1><p class="intro">동화 읽기부터 서재 복구, 데이터 삭제까지.<br>AI 동화책 이용에 필요한 도움을 모았습니다.</p><div class="cards"><a class="card" href="/support/"><h2>이용 중 도움이 필요해요</h2><p>동화 만들기와 계정 복구 방법을 확인하고 문의할 수 있어요.</p><span class="arrow">고객지원 보기 →</span></a><a class="card" href="/delete-account/"><h2>데이터를 삭제하고 싶어요</h2><p>앱 안에서 삭제하는 방법과 앱을 사용할 수 없을 때의 요청 방법을 알려드려요.</p><span class="arrow">삭제 방법 보기 →</span></a></div>'''),
        "support": ("고객지원", f'''<p class="eyebrow">고객지원</p><h1>어떤 도움이 필요하신가요?</h1><p class="intro">먼저 아래 안내를 확인해 주세요.<br>해결되지 않은 문제는 문의로 남길 수 있습니다.</p><section><h2>동화가 만들어지지 않아요</h2><p>앱에 표시된 작업 상태와 인터넷 연결을 확인해 주세요. 작업이 진행 중이라면 기다린 뒤 다시 확인하고, 실패 안내가 표시되면 앱의 다시 시도 버튼을 이용해 주세요.</p></section><section><h2>새 기기에서 서재를 보고 싶어요</h2><p>미리 보관한 복구 코드로 기존 계정을 복구할 수 있습니다. 기기 인증과 복구 코드를 모두 잃으면 기존 서재를 복구할 수 없습니다.</p><p>복구 코드는 계정에 접근할 수 있는 비밀 정보입니다. 문의 이메일에 보내지 마세요.</p></section><section><h2>직접 문의하기</h2><p>어느 화면에서 어떤 문제가 생겼는지, 사용 기종과 앱 버전을 알려주시면 확인에 도움이 됩니다.</p>{contact}<p class="notice">아이 사진, 복구 코드, 비밀번호와 결제 정보는 보내지 마세요. 화면을 첨부할 때는 아이 이름과 사진 등 개인 정보를 가려 주세요.</p></section>'''),
        "delete-account": ("계정 및 데이터 삭제", f'''<p class="eyebrow">개인정보 관리</p><h1>계정과 데이터를<br>삭제하고 싶으신가요?</h1><p class="intro">AI 동화책에서 사용한 계정과 관련 데이터의 삭제를 요청하는 방법입니다.</p><section><h2>앱을 사용할 수 있다면</h2><ol class="steps"><li>앱의 설정을 엽니다.</li><li>‘내 데이터 모두 삭제’를 선택합니다.</li><li>보호자 확인과 최종 확인 후 삭제를 요청합니다.</li></ol><p>파일 정리 대기 안내가 표시되면 정리가 진행 중인 상태입니다. 앱에 표시되는 처리 결과를 확인해 주세요.</p></section><section><h2>앱을 사용할 수 없다면</h2><p>아래 연락처로 삭제 요청을 시작할 수 있습니다. 먼저 AI 동화책 계정과 데이터의 삭제를 원한다는 내용만 보내 주세요. 계정 소유 여부 확인에 필요한 다음 절차는 별도로 안내합니다.</p>{delete_contact}<p class="notice">이메일에 복구 코드, 비밀번호, 아이 사진을 보내지 마세요. 다른 사람의 계정이 잘못 삭제되지 않도록 소유 확인 없이 임의로 삭제하지 않습니다.</p></section><p>처리하는 정보와 보관·삭제 기준은 <a href="/privacy/">개인정보처리방침</a>에서 확인할 수 있습니다.</p>'''),
    }
    output_dir.mkdir(parents=True, mode=0o700)
    for slug, (title, body) in pages.items():
        directory = output_dir / slug
        directory.mkdir(exist_ok=True, mode=0o700)
        (directory / "index.html").write_text(document(title, body, preview=preview))
    for slug, name, title in (("privacy", "privacy_policy", "개인정보처리방침"), ("terms", "terms_of_service", "이용약관")):
        directory = output_dir / slug
        directory.mkdir(mode=0o700)
        data = policies.get(name)
        if data is None:
            data = document(title, f'<p class="eyebrow">게시 준비</p><h1>{title}</h1><p>승인된 정책 문서가 연결되기 전인 비공개 검토 화면입니다.</p><a href="/">도움말로 돌아가기</a>', preview=True).encode()
        (directory / "index.html").write_bytes(data)
    shutil.copyfile(ROOT / "apps/public-site/site.css", output_dir / "site.css")
    (output_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if preview else "User-agent: *\nAllow: /\n")
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(), "mode": "private_preview" if preview else "production_files",
        "publishable": not preview, "deployed": False, "contact_verified": not preview,
        "policy_files_copied_without_edits": not preview,
        "files": {str(p.relative_to(output_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(output_dir.rglob("*")) if p.is_file()},
    }
    if not preview:
        manifest["site_url"] = config["site_url"]
    (output_dir / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for p in output_dir.rglob("*"):
        if p.is_file():
            p.chmod(0o600)
    return manifest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_published(config_path):
    # Regenerate from the approved inputs instead of trusting a stored manifest.
    with TemporaryDirectory(prefix="storybook-public-site-") as temporary:
        output_dir = Path(temporary) / "site"
        manifest = build(config_path, output_dir)
        origin = manifest["site_url"].rstrip("/")
        opener = build_opener(ProxyHandler({}), NoRedirect())
        for filename in manifest["files"]:
            relative_path = filename.removesuffix("index.html")
            media_type = {".css": "text/css", ".txt": "text/plain"}.get(Path(filename).suffix, "text/html")
            expected = (output_dir / filename).read_bytes()
            try:
                with opener.open(f"{origin}/{relative_path}", timeout=10) as response:
                    require(response.status == 200, "PUBLIC_SITE_HTTP_STATUS_INVALID")
                    require("Content-Type" in response.headers and response.headers.get_content_type() == media_type,
                            "PUBLIC_SITE_MEDIA_TYPE_INVALID")
                    require(response.read(len(expected) + 1) == expected, "PUBLIC_SITE_CONTENT_MISMATCH")
            except URLError:
                raise ValueError("PUBLIC_SITE_REQUEST_FAILED") from None
        return len(manifest["files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--private-preview", action="store_true")
    mode.add_argument("--verify-published", action="store_true")
    args = parser.parse_args()
    if args.verify_published == (args.output_dir is not None):
        parser.error("--output-dir is required for builds and unavailable with --verify-published")
    try:
        if args.verify_published:
            print(json.dumps({"status": "verified", "files_checked": verify_published(args.config)}))
            return
        result = build(args.config, args.output_dir, preview=args.private_preview)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Avoid exposing config values or private paths in build logs.
        print(json.dumps({"status": "blocked", "reason": str(exc) if type(exc) is ValueError and re.fullmatch(r"[A-Z_]+", str(exc)) else "INPUT_INVALID"}))
        raise SystemExit(1) from None
    print(json.dumps({"status": "built", "mode": result["mode"], "deployed": False}))


if __name__ == "__main__":
    main()
