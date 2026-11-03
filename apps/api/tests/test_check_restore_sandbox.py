import copy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('check_restore_sandbox')


@pytest.fixture
def container():
    temp = 'rw,nosuid,nodev,noexec,size=32m,uid=65534,gid=65534,mode=0700'
    return {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64,
        'Config': {'Labels': {'asb.restore.purpose': 'offline-candidate', 'asb.restore.token': 'c' * 32},
                   'User': '65534:65534'},
        'State': {'Running': True, 'Paused': False, 'Restarting': False, 'Dead': False},
        'HostConfig': {'NetworkMode': 'none', 'Privileged': False, 'ReadonlyRootfs': True,
            'PublishAllPorts': False, 'PortBindings': {}, 'Binds': None, 'VolumesFrom': None,
            'Devices': [], 'DeviceRequests': None, 'DeviceCgroupRules': None, 'CapAdd': None,
            'CapDrop': ['ALL'], 'PidMode': '', 'IpcMode': 'private', 'UsernsMode': '', 'Links': None,
            'SecurityOpt': ['no-new-privileges'], 'LogConfig': {'Type': 'none'},
            'RestartPolicy': {'Name': 'no'}, 'Memory': 1024, 'MemorySwap': 1024, 'PidsLimit': 128,
            'Tmpfs': {'/tmp': temp, '/var/lib/asb-restore': temp}},
        'Mounts': [], 'NetworkSettings': {'Networks': {'none': {'IPAddress': '', 'GlobalIPv6Address': '',
            'Gateway': '', 'IPv6Gateway': ''}}, 'Ports': {}}}


def check(module, value):
    return module.assess(value, container_id='a' * 64, image_id='sha256:' + 'b' * 64, token='c' * 32)


def test_expected_sandbox_is_not_restore_authorization(module, container):
    assert check(module, container) == {'status': 'SANDBOX_CONFIGURATION_MATCHES', 'restore_authorized': False}


@pytest.mark.parametrize('section,key,value', [
    ('HostConfig', 'NetworkMode', 'bridge'), ('HostConfig', 'Binds', ['/host:/data']),
    ('HostConfig', 'Privileged', True), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
    ('HostConfig', 'ReadonlyRootfs', False), ('HostConfig', 'PortBindings', {'5432/tcp': [{}]}),
    ('HostConfig', 'MemorySwap', 2048), ('HostConfig', 'SecurityOpt', ['seccomp=unconfined']),
    ('HostConfig', 'LogConfig', {'Type': 'json-file'}), ('State', 'Paused', True),
    ('Config', 'User', '0:0'), ('NetworkSettings', 'Networks', {'bridge': {'IPAddress': '172.1.1.1'}}),
])
def test_unsafe_container_configurations_are_rejected(module, container, section, key, value):
    candidate = copy.deepcopy(container)
    candidate[section][key] = value
    with pytest.raises(module.SandboxError):
        check(module, candidate)


def test_mount_and_identity_changes_are_rejected(module, container):
    candidate = copy.deepcopy(container)
    candidate['Mounts'] = [{'Type': 'bind'}]
    with pytest.raises(module.SandboxError):
        check(module, candidate)
    candidate = copy.deepcopy(container)
    candidate['HostConfig']['Tmpfs']['/tmp'] = 'rw,size=32m'
    with pytest.raises(module.SandboxError):
        check(module, candidate)
    with pytest.raises(module.SandboxError):
        module.assess(container, container_id='a' * 64, image_id='sha256:' + 'b' * 64, token='d' * 32)
