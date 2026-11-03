"""Publish a binary private-pilot purge queue signal without personal data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/privacy_purge_health'
PYTHON = sys.executable
CHECK = str(Path(__file__).resolve().with_name('check_privacy_purge_queue.py'))


def measurement(result):
    try:
        value = json.loads(result.stdout)
        return int(result.returncode == 0 and isinstance(value, dict)
                   and set(value) == {'status', 'restore_authorized'}
                   and value['status'] == 'OK' and value['restore_authorized'] is False)
    except (ValueError, TypeError, AttributeError):
        return 0


def check_command(env):
    environment, ca = env.get('ASB_PURGE_MONITOR_ENV_FILE'), env.get('ASB_PURGE_MONITOR_CA_FILE')
    if any(not isinstance(item, str) or not item or item.startswith('-') for item in (environment, ca)):
        raise ValueError('Private monitor configuration missing')
    return [PYTHON, CHECK, '--execute', '--env-file', environment, '--ca-file', ca]


def send(value, opener):
    if type(value) is not int or value not in (0, 1):
        raise ValueError('Invalid monitoring signal')
    request = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'})
    with opener.open(request, timeout=10) as response:
        token = json.load(response)['access_token']
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    payload = {'timeSeries': [{'metric': {'type': METRIC}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}
    request = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
        data=json.dumps(payload).encode(), method='POST', headers={'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('Monitoring write rejected')


def main():
    try:
        try:
            result = subprocess.run(check_command(os.environ), capture_output=True, text=True, timeout=90)
            value = measurement(result)
        except (ValueError, OSError, subprocess.SubprocessError):
            value = 0
        send(value, urllib.request.build_opener(urllib.request.ProxyHandler({})))
        print(json.dumps({'status': 'SIGNAL_SENT', 'healthy': bool(value), 'restore_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'SIGNAL_FAILED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
