"""Run branch graph race tests against an owned, network-isolated PostgreSQL."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from build_narration_candidate import ROOT, checkout_hashes, docker, ensure_local_daemon


def main():
    ensure_local_daemon()
    docker('image', 'inspect', 'postgres:16')
    image = 'sha256:28fb224ab8ea5fafa0e515370e64d3488560657b0f21776c05629f09eb618836'
    docker('image', 'inspect', image)
    name = 'asb-branch-race-fixture-' + uuid.uuid4().hex[:12]
    owned = None
    try:
        with tempfile.TemporaryDirectory(prefix='asb-branch-race-') as directory:
            root = Path(directory)
            root.chmod(0o755)  # synthetic fixture source; app runs as non-root
            before = checkout_hashes()
            source = root / 'src'
            shutil.copytree(ROOT / 'apps/api/src', source,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            if checkout_hashes() != before:
                raise RuntimeError('Source changed while taking fixture snapshot')
            owned = docker('run', '-d', '--rm', '--name', name, '--network=none',
                           '--tmpfs', '/var/lib/postgresql/data:rw,size=128m',
                           '-e', 'POSTGRES_USER=fixture', '-e', 'POSTGRES_PASSWORD=fixture',
                           '-e', 'POSTGRES_DB=fixture', 'postgres:16').decode().strip()
            for _ in range(60):
                result = subprocess.run(['docker', 'exec', owned, 'pg_isready', '-U', 'fixture'],
                                        capture_output=True, timeout=5)
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Fixture PostgreSQL did not start')
            probe = ROOT / 'scripts/branch_race_probe.py'
            result = subprocess.run(['docker', 'run', '--rm', '--network=container:' + owned,
                                     '--read-only', '--tmpfs', '/tmp:rw,size=32m',
                                     '--mount', f'type=bind,src={source},dst=/app/src,readonly',
                                     '--mount', f'type=bind,src={probe},dst=/tmp/probe.py,readonly',
                                     '-e', 'TESTING=true', '-e', 'ASB_TEST_ISOLATED_SETTINGS=1',
                                     '-e', 'ASB_BRANCH_RACE_FIXTURE=1',
                                     '-e', 'DATABASE_URL=postgresql://fixture:fixture@127.0.0.1:5432/fixture',
                                     '--entrypoint', 'python', image, '/tmp/probe.py'],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise RuntimeError('Synthetic branch race failed: ' + result.stderr[-2000:])
            if checkout_hashes() != before:
                raise RuntimeError('Source changed during fixture; rerun after editing completes')
            if 'BRANCH_POSTGRES_RACE_PASSED' not in result.stdout:
                raise RuntimeError('Synthetic branch race result missing')
    finally:
        if owned:
            docker('rm', '-f', owned)
    print(json.dumps({'status': 'BRANCH_POSTGRES_RACE_PASSED', 'synthetic_data_only': True,
                      'real_storage_verified': False, 'production_authorized': False}))


if __name__ == '__main__':
    main()
