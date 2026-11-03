"""Publish a secret-free local readiness signal; never call an AI provider."""
import json
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/api_readiness'
READINESS = 'http://127.0.0.1:18081/health/ready'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def readiness(opener):
    """Unreachable, malformed, unverified and unhealthy are all not ready."""
    try:
        request = urllib.request.Request(READINESS, headers={'Accept': 'application/json'})
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                return 0
            raw = response.read(65537)
        if len(raw) > 65536:
            return 0
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get('status') != 'healthy'
                or not isinstance(value.get('services'), dict)
                or value['services'].get('provider_runtime') != 'healthy'):
            return 0
        return 1
    except Exception:
        return 0


def payload(value, now):
    if type(value) is not int or value not in (0, 1) or now.tzinfo is None:
        raise ValueError('Invalid readiness signal')
    timestamp = now.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    return {'timeSeries': [{'metric': {'type': METRIC}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}


def send(value, opener):
    request = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                     headers={'Metadata-Flavor': 'Google'})
    with opener.open(request, timeout=10) as response:
        token = json.load(response)['access_token']
    body = json.dumps(payload(value, datetime.now(timezone.utc))).encode()
    request = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
        data=body, method='POST', headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('Monitoring write rejected')


def main():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        value = readiness(opener)
        if sys.argv[1:] == ['--check']:
            print(json.dumps({'status': 'READY' if value else 'NOT_READY', 'signal_sent': False}))
            return 0 if value else 1
        if sys.argv[1:]:
            raise ValueError('Unexpected argument')
        send(value, opener)
        print(json.dumps({'status': 'SIGNAL_SENT', 'ready': bool(value)}))
        return 0
    except Exception:
        print(json.dumps({'status': 'SIGNAL_FAILED'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
