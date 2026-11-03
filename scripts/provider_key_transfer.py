"""Send a Keychain item through an already-authenticated SSH control socket.

Keys are read only into process memory and sent through SSH stdin. This tool
does not create an SSH connection, install services or start a rotation.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tempfile
import time


class TransferError(RuntimeError):
    pass


def _socket(path):
    try:
        path = Path(path)
        info = path.lstat()
        if (not path.is_absolute() or not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.geteuid()):
            raise ValueError()
        return str(path.resolve(strict=True)), (info.st_dev, info.st_ino)
    except Exception:
        raise TransferError('Authenticated control socket is unavailable') from None


def _known_hosts(path):
    fd = None
    try:
        path = Path(path)
        if not path.is_absolute():
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        info = os.fstat(fd)
        if (not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or info.st_size > 1024 * 1024):
            raise ValueError()
        data = os.read(fd, 1024 * 1024 + 1)
        after = os.fstat(fd)
        if (len(data) != info.st_size or any(getattr(info, field) != getattr(after, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_mode'))):
            raise ValueError()
        return str(path.resolve(strict=True)), (info.st_dev, info.st_ino), hashlib.sha256(data).hexdigest()
    except Exception:
        raise TransferError('Pinned SSH known-hosts file is unavailable') from None
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def _owned_master(*, port, instance_id, known_hosts_file, identity_file):
    """Open a dedicated master with pinned host key; never reuse another one."""
    known, known_identity, known_hash = _known_hosts(known_hosts_file)
    try:
        private = Path(identity_file)
        info = private.lstat()
        if (not private.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise ValueError()
        private = str(private.resolve(strict=True))
    except Exception:
        raise TransferError('Private SSH identity is unavailable') from None
    # OpenSSH appends its own random suffix while creating the control socket.
    # macOS $TMPDIR can make that path exceed the Unix socket length limit.
    with tempfile.TemporaryDirectory(prefix='asb-master-', dir='/tmp') as directory:
        control = str(Path(directory).resolve() / 'control')
        snapshot = Path(directory).resolve() / 'known_hosts'
        data = Path(known).read_bytes()
        _, current_identity, current_hash = _known_hosts(known)
        if (current_identity != known_identity or current_hash != known_hash
                or hashlib.sha256(data).hexdigest() != known_hash):
            raise TransferError('Pinned SSH known-hosts file changed')
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise TransferError('Pinned SSH known-hosts file could not be copied')
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        command = ['ssh', '-N', '-M', '-S', control, '-p', str(port), '-i', private,
                   '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'PasswordAuthentication=no',
                   '-o', 'KbdInteractiveAuthentication=no', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + str(snapshot),
                   '-o', 'HostKeyAlias=compute.' + instance_id, 'jmac@127.0.0.1']
        process = None
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise TransferError('Pinned SSH master could not be established')
                if Path(control).exists():
                    check = subprocess.run(['ssh', '-S', control, '-p', str(port), '-O', 'check',
                                            'jmac@127.0.0.1'], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, timeout=3)
                    if check.returncode == 0:
                        yield control, str(snapshot)
                        return
                time.sleep(.1)
            raise TransferError('Pinned SSH master did not become ready')
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _transfer_on_owned_master(*, control_socket, port, instance_id, transaction_id, receiver_source,
                              receiver_sha256, known_hosts_file, recover=False):
    """Send through a master created by this process with a pinned host key."""
    if (type(port) is not int or not 1 <= port <= 65535
            or not isinstance(instance_id, str) or not re.fullmatch(r'[0-9]{1,32}', instance_id)
            or not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or not isinstance(receiver_source, bytes) or len(receiver_source) > 128 * 1024
            or not isinstance(receiver_sha256, str) or not re.fullmatch('[0-9a-f]{64}', receiver_sha256)
            or hashlib.sha256(receiver_source).hexdigest() != receiver_sha256):
        raise TransferError('Transfer configuration is invalid')
    socket, socket_identity = _socket(control_socket)
    known_hosts, known_identity, known_sha256 = _known_hosts(known_hosts_file)
    check = ['ssh', '-S', socket, '-p', str(port), '-o', 'BatchMode=yes', '-O', 'check', 'jmac@127.0.0.1']
    try:
        existing = subprocess.run(check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if existing.returncode:
            raise TransferError('Authenticated SSH session is unavailable')
        ssh_base = ['ssh', '-S', socket, '-p', str(port), '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
                    '-o', 'IdentitiesOnly=yes', '-o', 'PubkeyAuthentication=no', '-o', 'PasswordAuthentication=no',
                    '-o', 'KbdInteractiveAuthentication=no', '-o', 'PreferredAuthentications=none',
                    '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
                    '-o', 'UserKnownHostsFile=' + known_hosts, '-o', 'HostKeyAlias=compute.' + instance_id,
                    'jmac@127.0.0.1']
        identity_code = ("import urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
                         "q=urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/id',"
                         "headers={'Metadata-Flavor':'Google'}); r=o.open(q,timeout=3); print(r.read(33).decode('ascii').strip())")
        identity = subprocess.run(ssh_base + ['/usr/bin/python3 -c ' + shlex.quote(identity_code)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        if identity.returncode or identity.stdout.decode('ascii').strip() != instance_id:
            raise TransferError('SSH target identity could not be confirmed')
        key = b''
        if not recover:
            item = subprocess.run(['security', 'find-generic-password', '-a', 'ai-story-book', '-s',
                                   'ai-story-book-openai-production-2026-11-03', '-w'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
            if item.returncode or not item.stdout or len(item.stdout) > 4098:
                raise TransferError('Keychain item could not be read')
            key = item.stdout
        # Code contains no key; the key itself is provided solely on stdin.
        encoded = base64.b64encode(receiver_source).decode('ascii')
        code = 'import base64;exec(compile(base64.b64decode(' + repr(encoded) + '),"<receiver>","exec"))'
        flag = '--recover' if recover else '--install'
        remote = ('sudo -n /usr/bin/python3 -c ' + shlex.quote(code) + ' ' + flag + ' ' + transaction_id
                  + ' --expected-instance-id ' + instance_id)
        current = Path(socket).lstat()
        if not stat.S_ISSOCK(current.st_mode) or (current.st_dev, current.st_ino) != socket_identity:
            raise TransferError('Authenticated SSH session changed')
        _, current_known_identity, current_known_sha256 = _known_hosts(known_hosts)
        if current_known_identity != known_identity or current_known_sha256 != known_sha256:
            raise TransferError('Pinned SSH known-hosts file changed')
        command = ssh_base + [remote]
        result = subprocess.run(command, input=key, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90)
        del key
        if len(result.stdout) > 1024:
            raise TransferError('Transfer response is invalid; transaction outcome may be unknown')
        answer = json.loads(result.stdout)
        expected = {'KEY_FILE_PRESENT', 'TRANSFER_CANCELLED'} if recover else {'KEY_FILE_INSTALLED'}
        if (result.returncode or not isinstance(answer, dict) or set(answer) != {'status', 'recovery_required'}
                or answer.get('status') not in expected or answer.get('recovery_required') is not False):
            raise TransferError('Transfer was not confirmed; transaction may require recovery')
        return answer
    except TransferError:
        raise
    except Exception:
        raise TransferError('Transfer was not confirmed; transaction may require recovery') from None


def transfer(*, port, instance_id, transaction_id, receiver_source, receiver_sha256,
             known_hosts_file, identity_file, recover=False, on_master_ready=None):
    if type(port) is not int or not 1 <= port <= 65535 or not re.fullmatch(r'[0-9]{1,32}', instance_id or ''):
        raise TransferError('Transfer configuration is invalid')
    if not callable(on_master_ready):
        raise TransferError('Temporary identity cleanup is invalid')
    with _owned_master(port=port, instance_id=instance_id, known_hosts_file=known_hosts_file,
                       identity_file=identity_file) as (control, pinned_snapshot):
        try:
            if on_master_ready() is not True:
                raise ValueError()
        except Exception:
            raise TransferError('Temporary SSH identity cleanup was not confirmed') from None
        return _transfer_on_owned_master(control_socket=control, port=port, instance_id=instance_id,
                                         transaction_id=transaction_id, receiver_source=receiver_source,
                                         receiver_sha256=receiver_sha256, known_hosts_file=pinned_snapshot,
                                         recover=recover)
