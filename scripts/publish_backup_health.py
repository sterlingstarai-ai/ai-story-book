"""Publish only a binary private-pilot backup health signal to Cloud Monitoring."""
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/backup_health'
CHECK = '/opt/ai-story-book/current/scripts/check_backup_status.py'


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


def payload(value, now):
    if type(value) is not int or value not in (0, 1) or now.tzinfo is None:
        raise ValueError('Invalid monitoring signal')
    timestamp = now.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    return {'timeSeries': [{'metric': {'type': METRIC}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}


def send(value, opener):
    req = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                 headers={'Metadata-Flavor': 'Google'})
    with opener.open(req, timeout=10) as response:
        token = json.load(response)['access_token']
    body = json.dumps(payload(value, datetime.now(timezone.utc))).encode()
    req = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
                                 data=body, method='POST', headers={'Authorization': 'Bearer ' + token,
                                 'Content-Type': 'application/json'})
    with opener.open(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('Monitoring write rejected')


def main():
    try:
        try:
            result = subprocess.run(['/usr/bin/python3', CHECK], capture_output=True, text=True, timeout=45)
            value = measurement(result)
        except (OSError, subprocess.SubprocessError):
            value = 0
        send(value, urllib.request.build_opener(urllib.request.ProxyHandler({})))
        print(json.dumps({'status': 'SIGNAL_SENT', 'healthy': bool(value)}))
        return 0
    except Exception:
        print(json.dumps({'status': 'SIGNAL_FAILED'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
