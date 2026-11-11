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
_GOOGLE_PASSWORD_HELP = 'https://support.google.com/accounts/answer/185833?hl=ko'
_GOOGLE_PASSWORD_HINT = (
    'Google 계정의 일반 비밀번호가 아니라 2단계 인증을 사용 설정한 계정의 '
    '16자리 영문 앱 비밀번호가 필요합니다. 앱 비밀번호가 보이지 않으면 '
    f'계정의 지원 조건을 확인해 주세요: {_GOOGLE_PASSWORD_HELP}'
)
_SAFE_HINTS = {
    'INVALID_SMTP_CONFIGURATION': '발송 계정, 서버 주소와 포트를 확인해 주세요.',
    'EXISTING_CONFIGURATION_PRESERVED': '기존 비공개 설정을 보존했습니다. 새 값으로 덮어쓰지 않았습니다.',
    'UNSAFE_OUTPUT_PARENT': '비공개 설정을 저장할 디렉터리 상태를 확인해 주세요.',
    'PRIVATE_TERMINAL_REQUIRED': '입력 내용이 표시되지 않는 터미널에서 실행해 주세요.',
    'GOOGLE_APP_PASSWORD_REQUIRED': _GOOGLE_PASSWORD_HINT,
    'INVALID_SMTP_PASSWORD': '비밀번호 형식이 올바르지 않습니다. 값을 채팅에 보내지 마세요.',
    'PRIVATE_CONFIGURATION_SAVE_FAILED': (
        'SMTP 인증은 통과했지만 비공개 설정을 저장하지 못했습니다. '
        '로컬 저장 위치의 권한과 남은 공간을 확인해 주세요.'
    ),
}


def normalize_password(password, host):
    """Accept copied Google group separators, keeping other providers unchanged."""
    if host.lower() == 'smtp.gmail.com':
        password = ''.join(password.split())
        if not re.fullmatch('[A-Za-z]{16}', password):
            raise RuntimeError('GOOGLE_APP_PASSWORD_REQUIRED')
    if not password or len(password) > 4096 or any(c in password for c in '\r\n\x00'):
        raise RuntimeError('INVALID_SMTP_PASSWORD')
    return password


def failure_result(exc, host):
    """Return fixed diagnostics only; provider messages may contain credentials."""
    result = {'status': 'NOT_CONNECTED', 'error_type': type(exc).__name__, 'reason': None}
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        result['reason'] = 'SMTP_AUTHENTICATION_REJECTED'
        # Never include smtp_error, str(exc), or an untrusted nonnumeric code.
        code = exc.smtp_code
        result['smtp_code'] = code if type(code) is int and 100 <= code <= 599 else None
        result['hint'] = (
            '서버가 인증을 거절했습니다. 이 결과만으로 원인을 확정할 수 없습니다. '
            '발송 계정과 앱 비밀번호의 일치·취소 여부를 확인해 주세요.'
        )
        if host.lower() == 'smtp.gmail.com':
            result['hint'] += ' ' + _GOOGLE_PASSWORD_HINT
    elif isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        result['reason'] = 'SMTP_TLS_CONNECTION_FAILED'
        result['hint'] = (
            '암호화 연결을 완료하지 못했습니다. 비밀번호 오류로 단정할 수 없습니다. '
            '네트워크와 SMTP 서버·포트·보안 설정을 확인해 주세요.'
        )
    elif isinstance(exc, OSError):
        result['reason'] = 'SMTP_CONNECTION_FAILED'
        result['hint'] = (
            'SMTP 연결을 완료하지 못했습니다. 인증 정보 오류로 단정할 수 없습니다. '
            '네트워크와 SMTP 서버 설정을 확인해 주세요.'
        )
    elif (isinstance(exc, RuntimeError) and exc.args
          and isinstance(exc.args[0], str) and exc.args[0] in _SAFE_HINTS):
        result['reason'] = exc.args[0]
        result['hint'] = _SAFE_HINTS[exc.args[0]]
    else:
        result['hint'] = '연결을 완료하지 못했습니다. 비밀번호나 오류 원문을 채팅에 보내지 마세요.'
    return result


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
            prompt = ('Google 계정 비밀번호가 아닌 16자리 영문 앱 비밀번호'
                      if args.host.lower() == 'smtp.gmail.com' else 'SMTP 앱 비밀번호')
            password = getpass.getpass(prompt + ' (화면에 표시되지 않습니다): ')
        password = normalize_password(password, args.host)
        authenticate(args.host, args.port, args.security, args.account, password)
        configuration = {
            'host': args.host, 'port': args.port, 'security': args.security,
            'username': args.account, 'sender': args.account,
            'password_file': str(OUTPUT / 'smtp-password'),
            'public_origin': 'https://asb-https-edge-abvj5xczqa-uc.a.run.app',
        }
        try:
            save_private(OUTPUT, configuration, password)
        except OSError:
            raise RuntimeError('PRIVATE_CONFIGURATION_SAVE_FAILED') from None
        print(json.dumps({'status': 'SMTP_AUTH_VERIFIED', 'saved_privately': True,
                          'email_sent': False, 'production_changed': False}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps(failure_result(exc, args.host), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
