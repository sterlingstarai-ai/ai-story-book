"""Verify operator-supplied SMTP credentials and save them in an ignored private directory.

No email is sent, no cloud resource is changed, and existing files are never
overwritten. The password is read from a terminal only, never argv or chat.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import subprocess
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/acceptance/guardian-smtp-connection'
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_HOST = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?')


def authenticate(host, port, security, username, password):
    context = ssl.create_default_context()
    connection = (smtplib.SMTP_SSL(host, port, timeout=15, context=context)
                  if security == 'implicit_tls' else smtplib.SMTP(host, port, timeout=15))
    with connection as smtp:
        if security == 'starttls':
            smtp.starttls(context=context)
        smtp.login(username, password)


def save_private(directory, configuration, password):
    if directory.exists() or directory.is_symlink():
        raise RuntimeError('EXISTING_CONFIGURATION_PRESERVED')
    if directory.parent.is_symlink() or not directory.parent.is_dir():
        raise RuntimeError('UNSAFE_OUTPUT_PARENT')
    directory.mkdir(mode=0o700)
    created = []
    try:
        for name, data in [('smtp-password', password),
                           ('configuration.json', json.dumps(configuration, indent=2) + '\n')]:
            target = directory / name
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            created.append(target)
            with os.fdopen(fd, 'w') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
    except BaseException:
        for target in created:
            target.unlink()
        directory.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--account', required=True, help='SMTP login and sender email')
    parser.add_argument('--host', default='smtp.gmail.com')
    parser.add_argument('--port', type=int, default=465)
    parser.add_argument('--security', choices=['implicit_tls', 'starttls'], default='implicit_tls')
    args = parser.parse_args()
    try:
        if not (_EMAIL.fullmatch(args.account) and len(args.account) <= 254
                and _HOST.fullmatch(args.host) and 1 <= args.port <= 65535):
            raise RuntimeError('INVALID_SMTP_CONFIGURATION')
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise RuntimeError('EXISTING_CONFIGURATION_PRESERVED')
        ignored = subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '--quiet', str(OUTPUT / 'smtp-password')],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ignored.returncode or not sys.stdin.isatty():
            raise RuntimeError('PRIVATE_TERMINAL_REQUIRED')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('SMTP 앱 비밀번호 (화면에 표시되지 않습니다): ')
        # Google displays app passwords in four groups for readability.
        if args.host.lower() == 'smtp.gmail.com':
            password = password.replace(' ', '')
            if not re.fullmatch('[A-Za-z]{16}', password):
                raise RuntimeError('GOOGLE_APP_PASSWORD_REQUIRED')
        if not password or len(password) > 4096 or any(c in password for c in '\r\n\x00'):
            raise RuntimeError('INVALID_SMTP_PASSWORD')
        authenticate(args.host, args.port, args.security, args.account, password)
        configuration = {
            'host': args.host, 'port': args.port, 'security': args.security,
            'username': args.account, 'sender': args.account,
            'password_file': str(OUTPUT / 'smtp-password'),
            'public_origin': 'https://asb-https-edge-abvj5xczqa-uc.a.run.app',
        }
        save_private(OUTPUT, configuration, password)
        print(json.dumps({'status': 'SMTP_AUTH_VERIFIED', 'saved_privately': True,
                          'email_sent': False, 'production_changed': False}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'status': 'NOT_CONNECTED', 'error_type': type(exc).__name__,
                          'reason': str(exc) if isinstance(exc, RuntimeError) else None}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
