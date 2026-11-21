"""Run all native integration suites with one APK and one Flutter VM connection."""

from pathlib import Path
import subprocess
import tempfile


def main() -> int:
    mobile = Path(__file__).resolve().parents[1] / "apps/mobile"
    suite_dir = mobile / "integration_test"
    # The secure-credential migration tests exercise real platform preferences
    # before other suites install in-memory SharedPreferences implementations.
    files = sorted(
        suite_dir.glob("*_test.dart"),
        key=lambda path: (path.name != "security_credentials_native_test.dart", path.name),
    )
    if not files:
        raise RuntimeError("No native integration tests found")

    with tempfile.TemporaryDirectory(prefix="ci_native_", dir=suite_dir) as work:
        entry = Path(work) / "suite_test.dart"
        imports = ["import 'package:flutter_test/flutter_test.dart';"]
        groups = []
        for path in files:
            alias = path.stem
            imports.append(f"import '../{path.name}' as {alias};")
            groups.append(f"  group('{alias}', {alias}.main);")
        entry.write_text("\n".join([*imports, "", "void main() {", *groups, "}", ""]))

        # This script is used by the disposable GitHub Actions emulator. Leave
        # the suites' live-service and synthetic credential opt-ins unchanged.
        result = subprocess.run(
            [
                "flutter", "test", "--no-pub", "--reporter", "expanded",
                "-d", "emulator-5554", str(entry.relative_to(mobile)),
            ],
            cwd=mobile,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
