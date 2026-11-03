#!/usr/bin/env python3
"""Serve the debug Flutter preview on localhost without stale application code.

The Flutter worker for this origin is unregistered; browser storage and caches
are not deleted. Generated release assets are never modified.
"""

import argparse
from functools import lru_cache
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "apps/mobile/build/web"


@lru_cache(maxsize=4)
def fingerprint(path, modified_ns, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_revision():
    path = BUILD / "main.dart.js"
    info = path.stat()
    return fingerprint(str(path), info.st_mtime_ns, info.st_size)


def preview_bootstrap(revision):
    source = (BUILD / "flutter_bootstrap.js").read_text()
    # Retain Flutter's generated loader and build configuration, replacing only
    # its final invocation so this local preview cannot install an offline SW.
    source, count = re.subn(r"\n_flutter\.loader\.load\([\s\S]*?\);\s*$", "", source)
    if count != 1:
        raise RuntimeError("Unsupported Flutter bootstrap; rebuild the debug preview")
    return source + "\n" + r"""
(async () => {
  const revision = 'REVISION';
  if ('serviceWorker' in navigator) {
    for (const registration of await navigator.serviceWorker.getRegistrations()) {
      const worker = registration.active || registration.waiting || registration.installing;
      const script = worker && new URL(worker.scriptURL);
      if (registration.scope === location.origin + '/' &&
          script && script.origin === location.origin &&
          script.pathname === '/flutter_service_worker.js') {
        await registration.unregister();
      }
    }
  }
  // A previous controller can remain until navigation. A new URL also bypasses
  // its old resource manifest without clearing any local application data.
  for (const build of _flutter.buildConfig.builds) {
    if (build.mainJsPath) build.mainJsPath += '?previewBuild=' + revision;
  }
  console.info('[storybook-preview] build ' + revision);
  await _flutter.loader.load({config: {canvasKitBaseUrl: 'canvaskit/'}});
})();
""".replace("REVISION", revision)


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Storybook-Preview-Build", build_revision())
        super().end_headers()

    def send_head(self):
        # No 304 response may validate an older browser copy during review.
        for header in ("If-Modified-Since", "If-None-Match"):
            if header in self.headers:
                del self.headers[header]
        path = urlsplit(self.path).path
        content_type = "text/javascript; charset=utf-8"
        if path in {"/", "/index.html", "/preview"}:
            content_type = "text/html; charset=utf-8"
            body = (BUILD / "index.html").read_text().replace(
                'src="flutter_bootstrap.js"',
                'src="/__preview_bootstrap.js?build=' + build_revision() + '"')
        elif path == "/__preview_bootstrap.js":
            body = preview_bootstrap(build_revision())
        elif path == "/flutter_service_worker.js":
            # Retire an earlier offline worker on its regular update check.
            # Do not delete CacheStorage, IndexedDB, cookies or localStorage.
            body = ('self.addEventListener("install", () => self.skipWaiting());\n'
                    'self.addEventListener("activate", event => '
                    'event.waitUntil(self.registration.unregister()));\n')
        else:
            return super().send_head()
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return BytesIO(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18281)
    args = parser.parse_args()
    build_revision()
    preview_bootstrap(build_revision())
    with ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler) as server:
        print(f"Local debug preview: http://127.0.0.1:{server.server_port}/preview", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
