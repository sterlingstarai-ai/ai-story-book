"""Publish the pilot HTTPS readiness signal; never call an AI provider."""
import http.client
import json
import socket
import sys
import urllib.request
from datetime import datetime, timezone

PROJECT = 'gen-lang-client-0308507618'
METRIC = 'custom.googleapis.com/ai_story_book/api_readiness'
LIVENESS_METRIC = 'custom.googleapis.com/ai_story_book/api_liveness'
READINESS = 'https://35.209.174.246/health/ready'
LIVENESS = 'https://35.209.174.246/health/live'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalPilotConnection(http.client.HTTPSConnection):
    def connect(self):
        # Route to nginx on this VM but validate the public certificate name.
        raw = socket.create_connection(('127.0.0.1', 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class LocalPilotHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(LocalPilotConnection, request)


def readiness(opener):
    """Unreachable, malformed, unverified and unhealthy are all not ready."""
    return _health(opener, READINESS, 'healthy', providers=True)


def liveness(opener):
    """Process availability only; never represent this as dependency readiness."""
    return _health(opener, LIVENESS, 'alive', providers=False)


def _health(opener, url, expected, *, providers):
    try:
        request = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                return 0
            raw = response.read(65537)
        if len(raw) > 65536:
            return 0
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('status') != expected:
            return 0
        if providers and (not isinstance(value.get('services'), dict)
                          or value['services'].get('provider_runtime') != 'healthy'):
            return 0
        return 1
    except Exception:
        return 0


def payload(value, now, *, metric=METRIC):
    if (type(value) is not int or value not in (0, 1) or now.tzinfo is None
            or metric not in {METRIC, LIVENESS_METRIC}):
        raise ValueError('Invalid readiness signal')
    timestamp = now.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    return {'timeSeries': [{'metric': {'type': metric}, 'resource': {'type': 'global',
        'labels': {'project_id': PROJECT}}, 'metricKind': 'GAUGE', 'valueType': 'INT64',
        'points': [{'interval': {'endTime': timestamp}, 'value': {'int64Value': str(value)}}]}]}


def send(value, opener, *, metric=METRIC):
    request = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                     headers={'Metadata-Flavor': 'Google'})
    with opener.open(request, timeout=10) as response:
        token = json.load(response)['access_token']
    body = json.dumps(payload(value, datetime.now(timezone.utc), metric=metric)).encode()
    request = urllib.request.Request(f'https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries',
        data=body, method='POST', headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError('Monitoring write rejected')


def main():
    try:
        arguments = sys.argv[1:]
        if len(set(arguments)) != len(arguments) or set(arguments) - {'--check', '--liveness'}:
            raise ValueError('Unexpected argument')
        live = '--liveness' in arguments
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        probe = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), LocalPilotHTTPS())
        value = liveness(probe) if live else readiness(probe)
        if '--check' in arguments:
            status = ('ALIVE' if value else 'NOT_ALIVE') if live else ('READY' if value else 'NOT_READY')
            print(json.dumps({'status': status, 'signal_sent': False}))
            return 0 if value else 1
        if live:
            send(value, opener, metric=LIVENESS_METRIC)
        else:
            send(value, opener)
        print(json.dumps({'status': 'SIGNAL_SENT', 'alive' if live else 'ready': bool(value)}))
        return 0
    except Exception:
        print(json.dumps({'status': 'SIGNAL_FAILED'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
