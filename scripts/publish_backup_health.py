"""Publish the binary backup signal and a bounded failure diagnosis."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/backup_health'
FAILURE_METRIC = 'custom.googleapis.com/ai_story_book/backup_failure_stage'
CHECK = str(Path(__file__).resolve().with_name('check_backup_status.py'))


def measurement(result):
    """Treat an invalid, failed or missing local check as unhealthy."""
    try:
        value = json.loads(result.stdout)
        if (result.returncode == 0 and isinstance(value, dict) and value.get('status') == 'OK'
                and value.get('problems') == [] and value.get('restore_authorized') is False):
            return 1
    except (ValueError, TypeError, AttributeError):
        pass
    return 0


def failure_stage_code(result):
    try:
        value = json.loads(result.stdout)
        if (result.returncode == 1 and isinstance(value, dict) and value.get('status') == 'ALERT'
                and value.get('restore_authorized') is False
                and isinstance(value.get('problems'), list) and value['problems']):
            code = value.get('failure_reason_code')
            if type(code) is int and (1 <= code <= 17 or 19 <= code <= 21):
                return code
            # Accept a mixed-version deployment of the original checker.
            legacy = value.get('failure_stage_code')
            if 'last_service_failed' in value['problems'] and type(legacy) is int and 1 <= legacy <= 7:
                return legacy
            return None
    except (ValueError, TypeError, AttributeError):
        pass
    return 18 if measurement(result) == 0 else None


def payload(value, now):
    if type(value) is not int or value not in (0, 1) or now.tzinfo is None:
        raise ValueError('Invalid monitoring signal')
    return _payload(METRIC, value, now)


def _payload(metric, value, now):
    timestamp = now.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    return {'timeSeries': [{'metric': {'type': metric}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}


def send(value, opener, *, stage_code=None):
    req = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                 headers={'Metadata-Flavor': 'Google'})
    with opener.open(req, timeout=10) as response:
        token = json.load(response)['access_token']

    def publish(point):
        req = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
            data=json.dumps(point).encode(), method='POST', headers={'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'})
        with opener.open(req, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError('Monitoring write rejected')

    now = datetime.now(timezone.utc)
    publish(payload(value, now))
    if value == 0 and type(stage_code) is int and 1 <= stage_code <= 21:
        try:
            publish(_payload(FAILURE_METRIC, stage_code, now))
        except (OSError, RuntimeError):
            return False
        return True
    return None


def main():
    try:
        stage_code = None
        try:
            result = subprocess.run(['/usr/bin/python3', '-B', CHECK], capture_output=True, text=True, timeout=45,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            value = measurement(result)
            stage_code = failure_stage_code(result)
        except (OSError, subprocess.SubprocessError):
            value = 0
            stage_code = 18
        stage_sent = send(value, urllib.request.build_opener(urllib.request.ProxyHandler({})), stage_code=stage_code)
        print(json.dumps({'status': 'SIGNAL_SENT', 'healthy': bool(value),
                          **({'failure_stage_code': stage_code, 'stage_signal_sent': stage_sent} if stage_code else {})}))
        return 0
    except Exception:
        print(json.dumps({'status': 'SIGNAL_FAILED'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
