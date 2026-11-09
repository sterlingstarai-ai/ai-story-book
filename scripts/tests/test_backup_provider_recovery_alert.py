from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_backup_status as status
import publish_backup_health as signal


class ProviderBackupAlertTests(unittest.TestCase):
    def test_marker_and_unreadable_state_are_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'pending'
            self.assertFalse(status.provider_recovery_pending((marker,)))
            marker.write_text('{}')
            self.assertTrue(status.provider_recovery_pending((marker,)))
            unreadable = Mock()
            unreadable.lstat.side_effect = PermissionError()
            self.assertTrue(status.provider_recovery_pending((unreadable,)))

    def test_pending_marker_feeds_existing_binary_health_signal(self):
        now = datetime.now(timezone.utc)
        record = {'version': 1, 'verified_at': now.isoformat(), 'restore_authorized': False}
        result = status.assess(record, now=now, timer_active=True, timer_enabled=True, service_result='success',
                               free_bytes=status.MIN_FREE_BYTES, provider_recovery_pending=True)
        self.assertIn('provider_recovery_pending', result['problems'])
        process = SimpleNamespace(returncode=1, stdout=json.dumps(result))
        self.assertEqual(signal.measurement(process), 0)
        healthy = status.assess(record, now=now, timer_active=True, timer_enabled=True, service_result='success',
                                free_bytes=status.MIN_FREE_BYTES, provider_recovery_pending=False)
        self.assertEqual(signal.measurement(SimpleNamespace(returncode=0, stdout=json.dumps(healthy))), 1)

    def test_unknown_stage_distinguishes_service_timeout_from_missing_state(self):
        problems = ['last_service_failed', 'backup_stale']
        for service, expected in [('timeout', 16), ('oom-kill', 17), ('exit-code', 15), (None, 19)]:
            with self.subTest(service=service):
                self.assertEqual(status.failure_reason_code(problems, service, None), expected)
        self.assertEqual(status.failure_reason_code(problems, 'exit-code', 'journal_preflight'), 6)
        self.assertEqual(status.failure_reason_code(['backup_stale'], 'success', None), 13)
        self.assertEqual(status.failure_reason_code(
            ['backup_recovery_pending', *problems], 'exit-code', 'journal_preflight'
        ), 8)

    def test_wire_diagnosis_preserves_original_codes_and_rejects_free_text(self):
        alert = {'status': 'ALERT', 'restore_authorized': False, 'problems': ['last_service_failed']}
        for fields, expected in [
            ({'failure_stage_code': 6}, 6),
            ({'failure_reason_code': 16}, 16),
            ({'failure_reason_code': 19}, 19),
            ({'failure_reason_code': 'sensitive diagnostic'}, None),
            ({'failure_reason_code': True}, None),
            ({'failure_reason_code': 99}, None),
        ]:
            with self.subTest(fields=fields):
                result = SimpleNamespace(returncode=1, stdout=json.dumps(alert | fields))
                self.assertEqual(signal.failure_stage_code(result), expected)
        self.assertEqual(signal.failure_stage_code(SimpleNamespace(returncode=1, stdout='bad output')), 18)
        self.assertIsNone(signal.failure_stage_code(SimpleNamespace(
            returncode=0, stdout=json.dumps({'status': 'OK', 'restore_authorized': False, 'problems': []})
        )))

    def test_checker_timeout_still_sends_unhealthy_and_numeric_diagnosis(self):
        with patch.object(signal.subprocess, 'run', side_effect=signal.subprocess.TimeoutExpired('check', 45)), \
                patch.object(signal, 'send', return_value=True) as publish, patch('builtins.print'):
            self.assertEqual(signal.main(), 0)
        self.assertEqual(publish.call_args.args[0], 0)
        self.assertEqual(publish.call_args.kwargs, {'stage_code': 18})

    def test_binary_health_is_published_before_optional_diagnostic(self):
        token = Mock()
        token.read.return_value = '{"access_token":"fixture"}'
        health = Mock(status=200)
        opener = Mock()
        first, second = Mock(), Mock()
        first.__enter__ = Mock(return_value=token)
        first.__exit__ = Mock()
        second.__enter__ = Mock(return_value=health)
        second.__exit__ = Mock()
        opener.open.side_effect = [first, second, OSError('optional metric unavailable')]
        self.assertIs(signal.send(0, opener, stage_code=16), False)
        health_request, reason_request = [call.args[0] for call in opener.open.call_args_list[1:]]
        health_series = json.loads(health_request.data)['timeSeries'][0]
        reason_series = json.loads(reason_request.data)['timeSeries'][0]
        self.assertEqual(health_series['metric'], {'type': signal.METRIC})
        self.assertEqual(reason_series['metric'], {'type': signal.FAILURE_METRIC})
        self.assertEqual(health_series['points'][0]['value'], {'int64Value': '0'})
        self.assertEqual(reason_series['points'][0]['value'], {'int64Value': '16'})


if __name__ == '__main__':
    unittest.main()
