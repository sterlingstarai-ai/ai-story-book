"""Validate and stage a Neon read-only media credential on the pilot VM.

Read exactly two newline-separated values from a private SSH stdin. The
currently running API supplies the pinned source settings. Only an owned
random test object is written and removed. Active config is never changed.
"""

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from uuid import uuid4

from backup_external import storage_client
from media_cutover_preflight import _require_denied


PRIVATE = Path('/etc/ai-story-book/pilot/private')
STAGED = PRIVATE / 'media-neon-reader.stage.env'
RUNNING_API_IMAGE = 'sha256:47dcb13c52033638740a93463cded3d61c28bc9c85ccfd7ce4932e681be139b1'


def _live_values():
    result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
                             'inspect', 'asb-pilot-api'], capture_output=True, check=True, timeout=15)
    item, = json.loads(result.stdout)
    if (item['Name'] != '/asb-pilot-api' or item['Image'] != RUNNING_API_IMAGE
            or item['State']['Running'] is not True):
        raise ValueError('Unexpected source container')
    entries = [line.split('=', 1) for line in item['Config']['Env']]
    values = dict(entries)
    if len(values) != len(entries) or values['S3_BUCKET'] != 'storybook-private':
        raise ValueError('Unexpected source bucket')
    return values


def _publish(data):
    directory = PRIVATE.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or directory.st_mode & 0o022:
        raise ValueError('Unsafe stage directory')
    with tempfile.NamedTemporaryFile(dir=PRIVATE) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        os.link(temp.name, STAGED, follow_symlinks=False)
    fd = os.open(PRIVATE, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    try:
        if os.geteuid() != 0 or os.path.lexists(STAGED):
            raise ValueError('Stage unavailable')
        data = sys.stdin.buffer.read(4097)
        match = re.fullmatch(rb'(nak_live_[a-f0-9]{32})\n([A-Za-z0-9_+/=-]{16,512})\n', data)
        if not match:
            raise ValueError('Invalid credential format')
        access, secret = (part.decode('ascii') for part in match.groups())
        values = _live_values()
        if access == values['S3_ACCESS_KEY'] or secret == values['S3_SECRET_KEY']:
            raise ValueError('Existing writer credential is not a read-only replacement')
        reader_values = {**values, 'S3_ACCESS_KEY': access, 'S3_SECRET_KEY': secret}
        writer, reader = storage_client(values), storage_client(reader_values)
        args = {'Bucket': values['S3_BUCKET'], 'Key': 'asb-read-scope-probe-' + uuid4().hex}
        payload = b'AI Story Book synthetic storage permission test'
        created = False
        try:
            writer.put_object(**args, Body=payload, IfNoneMatch='*')
            created = True
            with reader.get_object(**args)['Body'] as source:
                if source.read(len(payload) + 1) != payload:
                    raise ValueError('Read-only download did not match')
            _require_denied(lambda: reader.put_object(**args, Body=payload), {403})
            _require_denied(lambda: reader.delete_object(**args), {403})
        finally:
            try:
                if created:
                    writer.delete_object(**args)
                    _require_denied(lambda: writer.head_object(**args), {404})
            finally:
                reader.close()
                writer.close()
        _publish(b'S3_ACCESS_KEY=' + match[1] + b'\nS3_SECRET_KEY=' + match[2] + b'\n')
        print('NEON_READER_VERIFIED_AND_STAGED')
        return 0
    except Exception:
        print('NEON_READER_NOT_STAGED')
        return 1


if __name__ == '__main__':
    sys.exit(main())
