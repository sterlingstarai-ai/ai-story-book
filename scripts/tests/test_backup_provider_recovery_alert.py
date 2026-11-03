from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

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
        result = status.assess(record, now=now, timer_active=True, service_result='success',
                               free_bytes=status.MIN_FREE_BYTES, provider_recovery_pending=True)
        self.assertIn('provider_recovery_pending', result['problems'])
        process = SimpleNamespace(returncode=1, stdout=json.dumps(result))
        self.assertEqual(signal.measurement(process), 0)
        healthy = status.assess(record, now=now, timer_active=True, service_result='success',
                                free_bytes=status.MIN_FREE_BYTES, provider_recovery_pending=False)
        self.assertEqual(signal.measurement(SimpleNamespace(returncode=0, stdout=json.dumps(healthy))), 1)


if __name__ == '__main__':
    unittest.main()
