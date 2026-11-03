"""Disposable Linux Docker cutover integration; provider/ingress are fakes.

Uses only unique labelled containers, a private internal network and a unique
volume. The runner has the local Docker socket to create only those fixtures.
No real key, production API, customer data or external network is used.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]


INNER = r'''
import fcntl,hashlib,json,os,signal,socket,subprocess,sys,types
owner,base,network,network_id=sys.argv[1:]
def load(name, content):
 m=types.ModuleType(name);sys.modules[name]=m;exec(compile(__import__('base64').b64decode(content),name,'exec'),m.__dict__);return m
env=load('provider_environment', ENV_SOURCE)
journal=load('provider_cutover_journal', JOURNAL_SOURCE)
stage=load('provider_candidate_stage', STAGE_SOURCE)
stage._DOCKER_BIN='/usr/local/bin/docker'
cut=load('provider_cutover', CUT_SOURCE)
docker=load('provider_cutover_docker_runtime', DOCKER_SOURCE)

def run(args,pass_fds=()):
 p=subprocess.run(['docker',*args],capture_output=True,timeout=40,pass_fds=pass_fds)
 if p.returncode: raise RuntimeError('fixture docker command failed')
 return p.stdout.decode().strip()

os.chmod(base,0o700)
network_state=json.loads(run(['network','inspect',network]))[0]
assert network_state['Id']==network_id and network_state['Internal'] is True
os.mkdir(base+'/guard',0o700);os.mkdir(base+'/backup',0o700)
for f,data in (('config.py',b'synthetic config'),('provider.key',b'synthetic-provider-key'),
               ('ca.pem',b'synthetic-ca'),('journal.key',b'synthetic-journal')):
 path=base+'/'+f
 with open(path,'wb') as out:out.write(data)
 os.chmod(path,0o600)
for f in ('config.py','provider.key'):os.chown(base+'/'+f,1000,1000)
stage._OVERLAY_PATH=base+'/config.py';stage._KEY_PATH=base+'/provider.key';stage._NETWORK=network
stage._BASE_MOUNTS={'/run/storybook-certs/neon-ca.pem':(base+'/ca.pem',False),
                    '/guard':(base+'/guard',True),'/run/storybook-secrets/journal.key':(base+'/journal.key',False)}
stage._BACKUP_LOCK=base+'/backup/backup.lock';stage._PENDING=()
source_env=b'LLM_API_KEY=synthetic-old\nIMAGE_API_KEY=synthetic-old\nDATABASE_URL=synthetic-db\n'.replace(b'\\n',b'\n')
image_ids={role:json.loads(run(['image','inspect',tag]))[0]['Id'] for role,tag in
           (('api','storybook-launch-api:c20d312'),('worker','storybook-launch-worker:c20d312'))}

def run_case(case):
 prefix='asb-cuti-'+owner[:10]+'-'+case
 names={s:prefix+'-'+s for s in ('old-api','old-worker','new-api','new-worker','old-api-prev','old-worker-prev')}
 pre={'old_api':names['old-api'],'old_worker':names['old-worker'],
      'new_api':names['new-api'],'new_worker':names['new-worker']}
 post={'old_api':names['old-api-prev'],'old_worker':names['old-worker-prev'],
       'new_api':names['old-api'],'new_worker':names['old-worker']}
 cut._PRE_NAMES=pre;cut._POST_NAMES=post;cut._SLOTS={s:{pre[s],post[s]} for s in pre}
 state=base+'/state-'+case;os.mkdir(state,0o700)
 s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
 stage._API_PORT_BIND='127.0.0.1:'+str(port)+':8000'
 rolecmd=['-c','import time;time.sleep(300)']
 stage._ROLES={'api':{'old':pre['old_api'],'new':pre['new_api'],'cmd':rolecmd},
               'worker':{'old':pre['old_worker'],'new':pre['new_worker'],'cmd':rolecmd}}
 old={}; stage_runtime=stage.DockerStageRuntime()
 for role in ('api','worker'):
  fd=os.memfd_create('fixture-env',os.MFD_CLOEXEC);os.write(fd,source_env);os.lseek(fd,0,os.SEEK_SET)
  args=['create','--name',stage._ROLES[role]['old'],'--restart=unless-stopped','--network',network,
        '--label','asb.fixture.token='+owner,'--env-file','/proc/self/fd/'+str(fd)]
  for dst,(src,rw) in stage._BASE_MOUNTS.items():args+=['--mount','type=bind,src='+src+',dst='+dst+('' if rw else ',readonly')]
  if role=='api':args+=['-p',stage._API_PORT_BIND]
  args+=['--entrypoint','python',image_ids[role],*rolecmd]
  try:old[role]=run(args,pass_fds=(fd,))
  finally:os.close(fd)
  run(['start',old[role]])
 fd=os.open(stage._BACKUP_LOCK,os.O_CREAT|os.O_RDWR,0o600)
 try:
  staged=stage.stage_candidates(runtime=stage_runtime,old_ids=old,image_ids=image_ids,environment=source_env,
   overlay_path=stage._OVERLAY_PATH,overlay_sha256=hashlib.sha256(b'synthetic config').hexdigest(),
   key_path=stage._KEY_PATH,transaction_id=owner,lock_fd=fd)
 finally:os.close(fd)
 evidence=stage.capture_bound_file_evidence(overlay_path=stage._OVERLAY_PATH,overlay_sha256=hashlib.sha256(b'synthetic config').hexdigest(),key_path=stage._KEY_PATH)
 ids=staged['ids'];images={'old_api':image_ids['api'],'new_api':image_ids['api'],
                           'old_worker':image_ids['worker'],'new_worker':image_ids['worker']}
 def adapter():
  targets=[]
  for slot,id in ids.items():
   current=run(['inspect','--format','{{.Name}}',id]).lstrip('/')
   label='asb.fixture.token' if slot.startswith('old_') else 'asb.provider.transaction'
   targets.append(docker.ContainerTarget(id,images[slot],current,frozenset({pre[slot],post[slot]}),label))
  return docker.DockerCutoverRuntime(targets,owner_token=owner,internal_network_id=network_id,
                                     daemon_quiescence=lambda:True)
 class Runtime:
  def __init__(self, kill=False):self.docker=adapter();self.drained=False;self.kill=kill
  def __getattr__(self,name):return getattr(self.docker,name)
  def assert_candidate_and_interlocks(self,ids,images,*,lock_fd,old_restart):
   stage.verify_staged(runtime=stage_runtime,ids=ids,image_ids=image_ids,environment=source_env,
    overlay_path=stage._OVERLAY_PATH,overlay_sha256=hashlib.sha256(b'synthetic config').hexdigest(),
    key_path=stage._KEY_PATH,transaction_id=owner,lock_fd=lock_fd,old_restart=old_restart)
  def drain_ingress(self):self.drained=True
  def assert_ingress_drained(self):assert self.drained
  def assert_worker_idle(self):pass
  def probe_provider_and_assert_readiness(self,id):
   assert self.drained and self.docker.inspect(id)['running']
   assert stage.verify_running_bound_files(runtime=stage_runtime,identifier=id,image_id=image_ids['api'],transaction_id=owner,evidence=evidence,overlay_path=stage._OVERLAY_PATH,overlay_sha256=hashlib.sha256(b'synthetic config').hexdigest(),key_path=stage._KEY_PATH)
   if self.kill:os.kill(os.getpid(),signal.SIGKILL)
  def assert_worker_healthy(self,id):
   assert self.docker.inspect(id)['running']
   assert stage.verify_running_bound_files(runtime=stage_runtime,identifier=id,image_id=image_ids['worker'],transaction_id=owner,evidence=evidence,overlay_path=stage._OVERLAY_PATH,overlay_sha256=hashlib.sha256(b'synthetic config').hexdigest(),key_path=stage._KEY_PATH)
  def reload_proxy(self):pass
  def open_ingress(self):self.drained=False
  def assert_live_candidate(self,api,worker):
   assert not self.drained and self.docker.inspect(api)['running'] and self.docker.inspect(worker)['running']
 if case=='success':
  result=cut.run_fixture_cutover(state_dir=state,backup_dir=base+'/backup',ids=ids,images=images,
                                 other_markers=[],runtime=Runtime())
  assert result['status']=='FIXTURE_CUTOVER_PASSED' and not os.path.exists(state+'/recovery.json')
  check=adapter()
  assert not check.inspect(ids['old_api'])['running'] and not check.inspect(ids['old_worker'])['running']
  assert check.inspect(ids['new_api'])['running'] and check.inspect(ids['new_worker'])['running']
 else:
  child=os.fork()
  if child==0:
   try:cut.run_fixture_cutover(state_dir=state,backup_dir=base+'/backup',ids=ids,images=images,
                               other_markers=[],runtime=Runtime(kill=True))
   except BaseException:os._exit(3)
   os._exit(4)
  _,status=os.waitpid(child,0)
  assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
  assert os.path.isfile(state+'/recovery.json')
  result=cut.recover_fixture(state_dir=state,backup_dir=base+'/backup',runtime=Runtime())
  assert result['status']=='FIXTURE_QUARANTINED' and os.path.isfile(state+'/recovery.json')
  check=adapter()
  for id in ids.values():
   item=check.inspect(id);assert not item['running'] and item['restart_policy']=='no'
 return True

out={'status':'FAILED'}
try:
 out={'status':'PASSED','normal_cutover':run_case('success'),'sigkill_recovery':run_case('crash'),
      'provider_ingress_boot_and_quiescence':'fixture_stubs','production_authorized':False}
except BaseException as e:out={'status':'FAILED','error_type':type(e).__name__,'production_authorized':False}
print(json.dumps(out,sort_keys=True),flush=True)
'''


def run(args, *, data=None, timeout=60):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError('Fixture operation failed')
    return result.stdout


def main():
    token = uuid.uuid4().hex
    tag, volume, network, runner = (f'asb-cutover-integration-{token}-{part}'
                                    for part in ('image', 'volume', 'network', 'runner'))
    tag += ':local'
    source_names = {'ENV_SOURCE': 'provider_environment.py', 'STAGE_SOURCE': 'provider_candidate_stage.py',
                    'CUT_SOURCE': 'provider_cutover.py', 'DOCKER_SOURCE': 'provider_cutover_docker_runtime.py',
                    'JOURNAL_SOURCE': 'provider_cutover_journal.py'}
    header = ''.join(name + '=' + repr(base64.b64encode((ROOT / 'scripts' / filename).read_bytes()).decode()) + '\n'
                     for name, filename in source_names.items())
    payload = (header + INNER).encode()
    result = {'status': 'FAILED', 'production_authorized': False}
    uncertain = False
    try:
        if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
            raise ValueError('fixture requires the default local Docker daemon')
        context = json.loads(run(['docker', 'context', 'inspect']))
        if not context[0]['Endpoints']['docker']['Host'].startswith('unix://'):
            raise ValueError('fixture requires a local Docker daemon')
        dockerfile = (b'FROM docker:cli AS cli\nFROM storybook-launch-api:c20d312\nUSER root\n'
                      b'COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker\n')
        with tempfile.TemporaryDirectory(prefix='asb-cutover-build-') as build:
            run(['docker', 'build', '--pull=false', '--network=none', '-t', tag, '-f', '-', build],
                data=dockerfile, timeout=180)
        run(['docker', 'volume', 'create', '--label', 'asb.fixture.token=' + token, volume])
        volume_data = json.loads(run(['docker', 'volume', 'inspect', volume]))[0]
        if volume_data.get('Labels', {}).get('asb.fixture.token') != token:
            raise ValueError('fixture volume identity')
        base = volume_data['Mountpoint']
        network_id = run(['docker', 'network', 'create', '--internal',
                          '--label', 'ai-story-book.cutover-fixture-owner=' + token, network]).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', network_id):
            raise ValueError('fixture network identity')
        run(['docker', 'create', '-i', '--name', runner, '--network', 'none', '--pid=host', '--cap-add=SYS_PTRACE', '--user', '0:0',
             '--label', 'asb.fixture.token=' + token, '--log-driver', 'none',
             '--mount', f'type=volume,src={volume},dst={base}',
             '-v', '/var/run/docker.sock:/var/run/docker.sock', '--entrypoint', 'python',
             tag, '-', token, base, network, network_id])
        try:
            output = run(['docker', 'start', '-a', '-i', runner], data=payload, timeout=300)
        except subprocess.TimeoutExpired:
            uncertain = True
            raise
        result = json.loads(output.decode().splitlines()[-1])
    except Exception as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            uncertain = True
        result = {'status': 'FAILED', 'error_type': type(exc).__name__, 'production_authorized': False}
    finally:
        clean = not uncertain
        for key in ('asb.fixture.token', 'asb.provider.transaction'):
            try:
                identifiers = run(['docker', 'ps', '-aq', '--filter', f'label={key}={token}']).decode().splitlines()
                for identifier in identifiers:
                    labels = json.loads(run(['docker', 'inspect', '--format', '{{json .Config.Labels}}', identifier]))
                    if labels.get(key) != token:
                        clean = False
                        continue
                    run(['docker', 'rm', '-f', identifier], timeout=30)
            except Exception:
                clean = False
        for kind, name, key in (('network', network, 'ai-story-book.cutover-fixture-owner'),
                                ('volume', volume, 'asb.fixture.token')):
            check = subprocess.run(['docker', kind, 'inspect', name], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, timeout=20)
            if check.returncode == 0:
                try:
                    item = json.loads(check.stdout)[0]
                    if (item.get('Labels') or {}).get(key) != token:
                        clean = False
                        continue
                    run(['docker', kind, 'rm', name], timeout=30)
                except Exception:
                    clean = False
        subprocess.run(['docker', 'image', 'rm', tag], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60, check=False)
        result['owned_cleanup_confirmed'] = clean
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') == 'PASSED' and result['owned_cleanup_confirmed'] else 1


if __name__ == '__main__':
    sys.exit(main())
