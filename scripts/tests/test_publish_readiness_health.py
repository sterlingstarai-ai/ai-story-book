import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_readiness_health as monitor


class Handler(BaseHTTPRequestHandler):
    mode = 'healthy'
    redirected = False

    def do_GET(self):
        if self.path == '/redirect-target':
            Handler.redirected = True
        if self.mode == 'redirect':
            self.send_response(302)
            self.send_header('Location', '/redirect-target')
            self.end_headers()
            return
        if self.mode == 'unverified':
            self.send_response(503)
            body = b'{"status":"unhealthy","services":{"provider_runtime":"unverified"}}'
        elif self.mode == 'malformed':
            self.send_response(200)
            body = b'{bad'
        elif self.mode == 'oversized':
            self.send_response(200)
            body = b'x' * 65537
        else:
            self.send_response(200)
            body = (b'{"status":"alive"}' if self.path == '/health/live' else
                    b'{"status":"healthy","services":{"provider_runtime":"healthy"}}')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class ReadinessSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/health/ready'
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), monitor.NoRedirect())

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_real_http_ready_unverified_malformed_and_large(self):
        with patch.object(monitor, 'READINESS', self.url):
            for mode, expected in (('healthy', 1), ('unverified', 0), ('malformed', 0), ('oversized', 0)):
                with self.subTest(mode=mode):
                    Handler.mode = mode
                    self.assertEqual(monitor.readiness(self.opener), expected)

    def test_redirect_not_followed(self):
        Handler.mode = 'redirect'
        Handler.redirected = False
        with patch.object(monitor, 'READINESS', self.url):
            self.assertEqual(monitor.readiness(self.opener), 0)
        self.assertFalse(Handler.redirected)

    def test_missing_provider_status_and_unreachable_are_unhealthy(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, _): return b'{"status":"healthy","services":{}}'
        class Opener:
            def open(self, *_args, **_kwargs): return Response()
        self.assertEqual(monitor.readiness(Opener()), 0)
        with patch.object(monitor, 'READINESS', 'http://127.0.0.1:1/health/ready'):
            self.assertEqual(monitor.readiness(self.opener), 0)

    def test_only_binary_safe_metric_payload(self):
        now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        point = monitor.payload(0, now)['timeSeries'][0]
        self.assertEqual(point['metric'], {'type': monitor.METRIC})
        self.assertEqual(point['points'][0]['value'], {'int64Value': '0'})
        with self.assertRaises(ValueError):
            monitor.payload(True, now)
        with self.assertRaises(ValueError):
            monitor.payload(1, datetime(2026, 11, 3))

    def test_preflight_checks_locally_without_metric_or_ai_call(self):
        with patch.object(monitor.sys, 'argv', ['monitor', '--check']), \
             patch.object(monitor, 'readiness', return_value=1), patch.object(monitor, 'send') as send, \
             patch('builtins.print'):
            self.assertEqual(monitor.main(), 0)
        send.assert_not_called()

    def test_real_http_liveness_cannot_be_used_as_readiness(self):
        Handler.mode = 'healthy'
        live_url = self.url.replace('/ready', '/live')
        with patch.object(monitor, 'LIVENESS', live_url), patch.object(monitor, 'READINESS', live_url):
            self.assertEqual(monitor.liveness(self.opener), 1)
            self.assertEqual(monitor.readiness(self.opener), 0)
        with patch.object(monitor, 'LIVENESS', self.url):
            self.assertEqual(monitor.liveness(self.opener), 0)

    def test_liveness_uses_its_own_metric_and_never_queries_readiness(self):
        with patch.object(monitor.sys, 'argv', ['monitor', '--liveness']), \
             patch.object(monitor, 'liveness', return_value=1), \
             patch.object(monitor, 'readiness') as ready, \
             patch.object(monitor, 'send') as send, patch('builtins.print'):
            self.assertEqual(monitor.main(), 0)
        ready.assert_not_called()
        self.assertEqual(send.call_args.kwargs, {'metric': monitor.LIVENESS_METRIC})
        point = monitor.payload(1, datetime.now(timezone.utc), metric=monitor.LIVENESS_METRIC)
        self.assertEqual(point['timeSeries'][0]['metric']['type'], monitor.LIVENESS_METRIC)
        with self.assertRaises(ValueError):
            monitor.payload(1, datetime.now(timezone.utc), metric='untrusted_metric')

    def test_policy_uses_distinct_metric_and_only_channel_placeholder(self):
        repo = Path(__file__).resolve().parents[2]
        policy = json.loads((repo / 'infra/gcp-pilot/asb-readiness-alert-policy.template.json').read_text())
        self.assertEqual(policy['notificationChannels'], ['PROJECT_NOTIFICATION_CHANNEL_RESOURCE'])
        self.assertEqual(len(policy['conditions']), 2)
        threshold = policy['conditions'][0]['conditionThreshold']
        self.assertEqual(threshold['duration'], '0s')
        self.assertEqual(threshold['aggregations'][0]['alignmentPeriod'], '1800s')
        self.assertEqual(threshold['aggregations'][0]['perSeriesAligner'], 'ALIGN_MIN')
        self.assertEqual(policy['conditions'][1]['conditionAbsent']['duration'], '2700s')
        for condition in policy['conditions']:
            entry = condition.get('conditionThreshold') or condition.get('conditionAbsent')
            self.assertIn(monitor.METRIC, entry['filter'])
            self.assertNotIn('backup_health', entry['filter'])


if __name__ == '__main__':
    unittest.main()
