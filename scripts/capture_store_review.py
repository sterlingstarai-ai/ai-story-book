"""Capture native-size review JPEGs from one already-booted temporary simulator.

The existing final_product_flow_test.dart sends local stage notifications here.
The supplied PNG is discarded: simctl captures the actual native display without
resizing, recoloring, framing or changing the app. Never boots a device or opens
Simulator.app. These mock-fixture review captures are not approved store assets.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
from threading import Lock

from PIL import Image

SIZES = {"iphone-69": {(1260, 2736), (1290, 2796), (1320, 2868)},
         "ipad-13": {(2064, 2752), (2048, 2732)}}
ROOT = Path(__file__).resolve().parents[1]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verify_device(device_id):
    require(bool(re.fullmatch(r"[A-Fa-f0-9-]{36}", device_id)), "DEVICE_ID_INVALID")
    result = subprocess.run(["xcrun", "simctl", "list", "devices", "-j"],
                            check=True, capture_output=True, timeout=20)
    matches = [d for devices in json.loads(result.stdout)["devices"].values()
               for d in devices if d["udid"] == device_id]
    require(len(matches) == 1 and matches[0]["state"] == "Booted"
            and matches[0]["name"].startswith("AIStoryBookReview-"), "OWNED_BOOTED_REVIEW_DEVICE_REQUIRED")


def capture(device_id, family, target):
    subprocess.run(["xcrun", "simctl", "io", device_id, "screenshot", "--type=jpeg", str(target)],
                   check=True, capture_output=True, timeout=30)
    target.chmod(0o600)
    with Image.open(target) as image:
        require(image.format == "JPEG" and image.size in SIZES[family], "NATIVE_STORE_DIMENSIONS_MISMATCH")
        size = image.size
    return {"file": target.name, "width": size[0], "height": size[1],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--family", required=True, choices=SIZES)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--fictional-fixture", action="store_true", required=True)
    args = parser.parse_args()
    verify_device(args.device_id)
    root = args.output_dir.resolve()
    require(root.is_relative_to(ROOT / "docs/acceptance") and not root.exists(), "NEW_PRIVATE_OUTPUT_REQUIRED")
    root.mkdir(parents=True, mode=0o700)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "family": args.family,
                "fixture": "synthetic local HTTP journey; mock AI", "real_child_photos": False,
                "store_upload_approved": False, "native_capture": True, "resized": False, "captures": []}
    lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            if not re.fullmatch(r"/ios/[a-z0-9-]{1,60}\.png", self.path):
                self.send_error(400)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < size <= 12_000_000:
                self.send_error(413)
                return
            data = self.rfile.read(size)
            if len(data) != size or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                self.send_error(400)
                return
            target = root / (Path(self.path).stem + ".jpg")
            with lock:
                if target.exists() or len(manifest["captures"]) >= 24:
                    self.send_error(409)
                    return
                try:
                    record = capture(args.device_id, args.family, target)
                    manifest["captures"].append(record)
                    report = root / "capture-manifest.json"
                    report.write_text(json.dumps(manifest, indent=2) + "\n")
                    report.chmod(0o600)
                except (ValueError, OSError, subprocess.SubprocessError):
                    self.send_error(500)
                    return
            self.send_response(201)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"port": server.server_port, "family": args.family, "status": "ready"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
