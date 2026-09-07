"""Render bundled policy sources to static HTML without changing review status.

The public support builder still requires reviewed files and matching hashes.
"""

from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]


def render(data: dict) -> str:
    escape = html.escape
    sections = ''.join(
        '<section><h2>' + escape(section['heading']) + '</h2>'
        + ''.join('<p>' + escape(p) + '</p>' for p in section['paragraphs'])
        + '</section>' for section in data['sections']
    )
    review = data['publication_status'] != 'approved'
    banner = ('<aside>출시 전 검토본 · 시행일과 운영 계약의 미확정 사항을 확인한 뒤 공개합니다.</aside>'
              if review else '')
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="robots" content="{'noindex,nofollow' if review else 'index,follow'}">
<meta name="legal-status" content="{escape(data['publication_status'])}">
<title>{escape(data['title'])} · AI 동화책</title>
<style>body{{margin:0;background:#f8f9fc;color:#202938;font:17px/1.85 system-ui,sans-serif}}main{{max-width:760px;margin:auto;padding:36px 24px 80px;overflow-wrap:anywhere}}h1{{font-size:2rem;line-height:1.4}}h2{{font-size:1.2rem;line-height:1.5;margin-top:2.2rem}}a{{color:#4f46e5}}aside{{background:#eceafe;padding:16px;border-radius:12px}}p{{margin:12px 0}}nav{{display:flex;gap:20px;flex-wrap:wrap}}a:focus-visible{{outline:3px solid #4f46e5;outline-offset:4px}}@media(prefers-color-scheme:dark){{body{{background:#171922;color:#eceefa}}aside{{background:#292542}}a{{color:#b6acff}}}}</style></head>
<body><main>{banner}<h1>{escape(data['title'])}</h1><p>{escape(data['version_label'])}</p>
<p>{escape(data['introduction'])}</p>{sections}
<nav aria-label="정책 문의"><a href="mailto:{escape(data['contact_email'], quote=True)}">문의하기</a></nav>
</main></body></html>'''


def main() -> None:
    for slug, filename in [('privacy', 'privacy-policy'), ('terms', 'terms-of-service')]:
        data = json.loads((ROOT / f'apps/mobile/assets/legal/{slug}.ko.json').read_text())
        (ROOT / f'docs/{filename}.ko.html').write_text(render(data) + '\n')
        # No unapproved translation is represented as the full policy.
        (ROOT / f'docs/{filename}.en.html').write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><title>AI Story Book policy</title>'
            '</head><body><main><h1>AI Story Book policy</h1>'
            '<p>The full review document is currently provided in Korean.</p>'
            f'<a href="{filename}.ko.html" lang="ko">{html.escape(data["title"])} — 한국어 원문</a>'
            '</main></body></html>\n')


if __name__ == '__main__':
    main()
