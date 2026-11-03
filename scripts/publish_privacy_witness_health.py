"""Publish a binary witness-snapshot signal; a match never authorizes restore."""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/privacy_witness_health'
RUNNER = '/opt/ai-story-book/current/scripts/run_privacy_witness_monitor.py'
PYTHON = '/opt/ai-story-book/current/apps/api/venv/bin/python'
OPTIONS = {
    'env-file': 'ASB_WITNESS_ENV_FILE', 'ca-file': 'ASB_WITNESS_CA_FILE',
    'journal-key-file': 'ASB_WITNESS_JOURNAL_KEY_FILE',
    'checkpoint-key-file': 'ASB_WITNESS_CHECKPOINT_KEY_FILE', 'head-key-file': 'ASB_WITNESS_HEAD_KEY_FILE',
    'trusted-reference-file': 'ASB_WITNESS_TRUSTED_REFERENCE_FILE',
    'journal-bucket': 'ASB_WITNESS_JOURNAL_BUCKET', 'journal-witness-bucket': 'ASB_WITNESS_JOURNAL_MIRROR_BUCKET',
    'checkpoint-bucket': 'ASB_WITNESS_CHECKPOINT_BUCKET', 'head-bucket': 'ASB_WITNESS_HEAD_BUCKET',
}


def measurement(result):
    try:
        value = json.loads(result.stdout)
        return int(result.returncode == 0 and isinstance(value, dict)
                   and set(value) == {'status', 'restore_authorized'}
                   and value['status'] == 'SNAPSHOT_MATCHES' and value['restore_authorized'] is False)
    except (ValueError, TypeError, AttributeError):
        return 0


def watch_command(env):
    args = [PYTHON, RUNNER, '--execute']
    for option, variable in OPTIONS.items():
        value = env.get(variable)
        if not isinstance(value, str) or not value or value.startswith('-'):
            raise ValueError('Witness settings are incomplete')
        args.extend(['--' + option, value])
    return args


def send(value, opener):
    if type(value) is not int or value not in (0, 1):
        raise ValueError('Invalid monitoring signal')
    token_request = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'})
    with opener.open(token_request, timeout=10) as response:
        token = json.load(response)['access_token']
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    data = {'timeSeries': [{'metric': {'type': METRIC}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}
    req = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
        data=json.dumps(data).encode(), method='POST', headers={'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'})
    with opener.open(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('Monitoring write rejected')


def main():
    try:
        try:
            result = subprocess.run(watch_command(os.environ), capture_output=True, text=True, timeout=120)
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
