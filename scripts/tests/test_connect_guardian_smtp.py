import importlib.util
import json
from pathlib import Path
import stat
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('connect_guardian_smtp', Path(__file__).parents[1] / 'connect_guardian_smtp.py')
smtp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smtp)


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
    assert secret not in logged and json.loads(logged)['error_type'] == 'SMTPAuthenticationError'
    assert not output.exists()
