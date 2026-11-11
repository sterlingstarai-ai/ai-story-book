"""SMTP input and error handling must preserve credentials and existing files."""

import importlib.util
import json
from pathlib import Path
import stat
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('connect_guardian_smtp', Path(__file__).resolve().parents[3] / 'scripts/connect_guardian_smtp.py')
smtp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smtp)


@pytest.mark.parametrize('separator', [' ', '\t', '\n', '\r\n', '\u00a0', '\u202f', '\u3000'])
def test_google_password_normalizes_unicode_whitespace(separator):
    grouped = separator.join(['abcd', 'efgh', 'ijkl', 'mnop'])
    assert smtp.normalize_password(grouped, 'SMTP.GMAIL.COM') == 'abcdefghijklmnop'


@pytest.mark.parametrize('password', [
    'ordinary-password', 'abcdefghijklmno1', 'abcdefghijklmnopq',
    'abcd\u200befghijklmnop', 'abcdefghijklmnop\x00', '',
])
def test_google_password_still_requires_exactly_sixteen_ascii_letters(password):
    with pytest.raises(RuntimeError, match='GOOGLE_APP_PASSWORD_REQUIRED'):
        smtp.normalize_password(password, 'smtp.gmail.com')


def test_other_provider_password_spaces_are_not_removed():
    assert smtp.normalize_password('secret with spaces', 'smtp.example.org') == 'secret with spaces'
    with pytest.raises(RuntimeError, match='INVALID_SMTP_PASSWORD'):
        smtp.normalize_password('secret\nvalue', 'smtp.example.org')


@pytest.mark.parametrize('security', ['implicit_tls', 'starttls'])
def test_login_only_after_tls_without_sending(monkeypatch, security):
    connection = Mock()
    context = Mock()
    monkeypatch.setattr(smtp.ssl, 'create_default_context', lambda: context)
    methods = Mock()
    connection.__enter__ = Mock(return_value=methods)
    connection.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(smtp.smtplib, 'SMTP_SSL' if security == 'implicit_tls' else 'SMTP', constructor)
    smtp.authenticate('smtp.example.org', 465, security, 'owner@example.org', 'fictional-secret')
    if security == 'starttls':
        assert methods.method_calls == [
            ('starttls', (), {'context': context}), ('login', ('owner@example.org', 'fictional-secret'), {})]
    else:
        assert constructor.call_args.kwargs['context'] is context
        methods.starttls.assert_not_called()
        methods.login.assert_called_once()
    methods.send_message.assert_not_called()


def test_failed_tls_never_authenticates(monkeypatch):
    methods = Mock()
    methods.starttls.side_effect = OSError('TLS unavailable')
    connection = Mock()
    connection.__enter__ = Mock(return_value=methods)
    connection.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(smtp.smtplib, 'SMTP', Mock(return_value=connection))
    with pytest.raises(OSError):
        smtp.authenticate('smtp.example.org', 587, 'starttls', 'owner@example.org', 'fictional-secret')
    methods.login.assert_not_called()


def test_saved_material_is_private_and_never_overwrites(tmp_path):
    output = tmp_path / 'private'
    smtp.save_private(output, {'sender': 'owner@example.org'}, 'fictional-secret')
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    for p in output.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert json.loads((output / 'configuration.json').read_text()) == {'sender': 'owner@example.org'}
    with pytest.raises(RuntimeError, match='EXISTING_CONFIGURATION_PRESERVED'):
        smtp.save_private(output, {}, 'replacement')
    assert (output / 'smtp-password').read_text() == 'fictional-secret'


def test_non_terminal_never_prompts_or_saves(monkeypatch, tmp_path, capsys):
    output = tmp_path / 'private'
    monkeypatch.setattr(smtp, 'OUTPUT', output)
    monkeypatch.setattr(smtp.sys, 'argv', ['connect_guardian_smtp.py', '--execute', '--account', 'owner@example.org'])
    monkeypatch.setattr(smtp.sys, 'stdin', Mock(isatty=Mock(return_value=False)))
    monkeypatch.setattr(smtp.subprocess, 'run', Mock(return_value=Mock(returncode=0)))
    hidden = Mock(side_effect=AssertionError('must not prompt'))
    monkeypatch.setattr(smtp.getpass, 'getpass', hidden)
    assert smtp.main() == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'PRIVATE_TERMINAL_REQUIRED'
    assert not output.exists()
    hidden.assert_not_called()


def test_auth_failure_does_not_echo_provider_text_or_save(monkeypatch, tmp_path, capsys):
    output = tmp_path / 'private'
    secret = 'abcdefghijklmnop'
    monkeypatch.setattr(smtp, 'OUTPUT', output)
    monkeypatch.setattr(smtp.sys, 'argv', ['connect_guardian_smtp.py', '--execute', '--account', 'owner@example.org'])
    monkeypatch.setattr(smtp.sys, 'stdin', Mock(isatty=Mock(return_value=True)))
    monkeypatch.setattr(smtp.subprocess, 'run', Mock(return_value=Mock(returncode=0)))
    monkeypatch.setattr(smtp.getpass, 'getpass', lambda _: secret)
    monkeypatch.setattr(smtp, 'authenticate', Mock(side_effect=smtp.smtplib.SMTPAuthenticationError(535, secret.encode())))
    assert smtp.main() == 1
    logged = capsys.readouterr().out
    result = json.loads(logged)
    assert secret not in logged and result['error_type'] == 'SMTPAuthenticationError'
    assert result['reason'] == 'SMTP_AUTHENTICATION_REJECTED'
    assert result['smtp_code'] == 535
    assert '원인을 확정할 수 없습니다' in result['hint']
    assert smtp._GOOGLE_PASSWORD_HELP in result['hint']
    assert not output.exists()


@pytest.mark.parametrize('error', [
    PermissionError('dummy-private-path'), OSError(28, 'dummy-disk-full'),
])
def test_authenticated_save_failure_is_not_reported_as_network_error(monkeypatch, tmp_path, capsys, error):
    output = tmp_path / 'private'
    secret = 'abcdefghijklmnop'
    monkeypatch.setattr(smtp, 'OUTPUT', output)
    monkeypatch.setattr(smtp.sys, 'argv', ['connect_guardian_smtp.py', '--execute', '--account', 'owner@example.org'])
    monkeypatch.setattr(smtp.sys, 'stdin', Mock(isatty=Mock(return_value=True)))
    monkeypatch.setattr(smtp.subprocess, 'run', Mock(return_value=Mock(returncode=0)))
    monkeypatch.setattr(smtp.getpass, 'getpass', lambda _: secret)
    authenticate = Mock()
    monkeypatch.setattr(smtp, 'authenticate', authenticate)
    monkeypatch.setattr(smtp, 'save_private', Mock(side_effect=error))
    assert smtp.main() == 1
    logged = capsys.readouterr().out
    result = json.loads(logged)
    authenticate.assert_called_once()
    assert result['reason'] == 'PRIVATE_CONFIGURATION_SAVE_FAILED'
    assert '인증은 통과' in result['hint']
    assert 'dummy-' not in logged and secret not in logged
    assert not output.exists()


@pytest.mark.parametrize('error,reason', [
    (smtp.ssl.SSLError('dummy-secret-must-not-appear'), 'SMTP_TLS_CONNECTION_FAILED'),
    (smtp.smtplib.SMTPNotSupportedError('dummy-secret-must-not-appear'), 'SMTP_TLS_CONNECTION_FAILED'),
    (ConnectionError('dummy-secret-must-not-appear'), 'SMTP_CONNECTION_FAILED'),
    (RuntimeError('dummy-secret-must-not-appear'), None),
])
def test_failure_json_never_echoes_untrusted_exception_text(error, reason):
    result = smtp.failure_result(error, 'smtp.gmail.com')
    assert result['reason'] == reason
    assert 'dummy-secret-must-not-appear' not in json.dumps(result)


def test_auth_failure_never_echoes_untrusted_smtp_code():
    result = smtp.failure_result(
        smtp.smtplib.SMTPAuthenticationError('dummy-secret-code', b'dummy-secret-body'), 'smtp.gmail.com',
    )
    assert result['smtp_code'] is None
    assert 'dummy-secret' not in json.dumps(result)


def test_bad_google_format_has_safe_help_without_authentication(monkeypatch, tmp_path, capsys):
    output = tmp_path / 'private'
    monkeypatch.setattr(smtp, 'OUTPUT', output)
    monkeypatch.setattr(smtp.sys, 'argv', ['connect_guardian_smtp.py', '--execute', '--account', 'owner@example.org'])
    monkeypatch.setattr(smtp.sys, 'stdin', Mock(isatty=Mock(return_value=True)))
    monkeypatch.setattr(smtp.subprocess, 'run', Mock(return_value=Mock(returncode=0)))
    monkeypatch.setattr(smtp.getpass, 'getpass', lambda _: 'dummy-general-google-password')
    authenticate = Mock()
    monkeypatch.setattr(smtp, 'authenticate', authenticate)
    assert smtp.main() == 1
    logged = capsys.readouterr().out
    result = json.loads(logged)
    assert result['reason'] == 'GOOGLE_APP_PASSWORD_REQUIRED'
    assert '2단계 인증' in result['hint'] and smtp._GOOGLE_PASSWORD_HELP in result['hint']
    assert 'dummy-general-google-password' not in logged
    assert not output.exists()
    authenticate.assert_not_called()
