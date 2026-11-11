"""Device release gates reject simulator slices even when they are arm64."""
from pathlib import Path
import plistlib
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import validate_ios_native_platforms as native_gate
from validate_ios_native_platforms import validate_tool_output, validate_ipa


def test_device_arm64_platform_is_accepted():
    assert validate_tool_output('arm64\n', 'Load command 9\n platform IOS\n minos 14.0')['platforms'] == ['IOS']


def test_apple_legacy_iphoneos_metadata_is_accepted_for_device_arm64():
    result = validate_tool_output('arm64\n', 'Load command 8\n cmd LC_VERSION_MIN_IPHONEOS\n version 7.0\n sdk 27.2')
    assert result['platforms'] == ['IOS']
    assert result['legacy_iphoneos_metadata'] is True


@pytest.mark.parametrize('architectures,platforms', [
    ('arm64', ' platform IOSSIMULATOR\n'),
    ('arm64', ' platform MACOS\n'),
    ('arm64', ' platform IOS\n platform IOSSIMULATOR\n'),
    ('x86_64', ' platform IOS\n'),
    ('arm64', ' minos 15.0\n'),
    ('arm64', ' cmd LC_VERSION_MIN_MACOSX\n version 15.0\n'),
    ('', ' platform IOS\n'),
])
def test_non_device_or_unproven_platform_is_rejected(architectures, platforms):
    with pytest.raises(ValueError):
        validate_tool_output(architectures, platforms)


def test_archive_without_native_payload_is_not_verified(tmp_path):
    archive = tmp_path / 'fixture.ipa'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr('Payload/Runner.app/Info.plist', 'fixture')
    with pytest.raises(ValueError, match='No native iOS binaries'):
        validate_ipa(archive)


def test_untrusted_archive_paths_are_not_extracted(tmp_path):
    archive = tmp_path / 'fixture.ipa'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr('../outside', 'fixture')
    with pytest.raises(ValueError, match='member path'):
        validate_ipa(archive)
    assert not (tmp_path / 'outside').exists()


_APP = 'Payload/Runner.app/'
_SHARE_FRAMEWORK = _APP + 'Frameworks/share_plus.framework/'
_VALID_MANIFEST = {
    'NSPrivacyTracking': False,
    'NSPrivacyTrackingDomains': [],
    'NSPrivacyCollectedDataTypes': [],
    'NSPrivacyAccessedAPITypes': [{
        'NSPrivacyAccessedAPIType': 'NSPrivacyAccessedAPICategoryFileTimestamp',
        'NSPrivacyAccessedAPITypeReasons': ['C617.1'],
    }],
}


def _sdk_archive(tmp_path, monkeypatch, manifests):
    monkeypatch.setattr(native_gate, '_inspect', lambda path, name: {
        'file': name, 'architectures': ['arm64'], 'platforms': ['IOS'],
    })
    archive = tmp_path / 'fixture.ipa'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr(_APP + 'Runner', bytes.fromhex('cffaedfe') + b'fixture')
        out.writestr(_SHARE_FRAMEWORK + 'share_plus', bytes.fromhex('cffaedfe') + b'fixture')
        for name, data in manifests.items():
            out.writestr(name, data)
    return archive


def test_share_sdk_missing_manifest_is_not_hidden_by_other_manifests(tmp_path, monkeypatch):
    manifests = {
        _APP + f'Frameworks/other_{i}.framework/PrivacyInfo.xcprivacy': plistlib.dumps(_VALID_MANIFEST)
        for i in range(16)
    }
    # An app's own manifest cannot satisfy a third-party SDK's requirement.
    manifests[_APP + 'PrivacyInfo.xcprivacy'] = plistlib.dumps(_VALID_MANIFEST)
    archive = _sdk_archive(tmp_path, monkeypatch, manifests)
    with pytest.raises(ValueError, match='Missing SDK privacy manifest for share_plus'):
        validate_ipa(archive)


@pytest.mark.parametrize('location', [
    _SHARE_FRAMEWORK + 'PrivacyInfo.xcprivacy',
    _SHARE_FRAMEWORK + 'share_plus_privacy.bundle/PrivacyInfo.xcprivacy',
    _APP + 'share_plus_privacy.bundle/PrivacyInfo.xcprivacy',
    _APP + 'share_plus_share_plus.bundle/PrivacyInfo.xcprivacy',
])
def test_share_sdk_manifest_is_accepted_in_its_framework_or_resource_bundle(tmp_path, monkeypatch, location):
    archive = _sdk_archive(tmp_path, monkeypatch, {location: plistlib.dumps(_VALID_MANIFEST)})
    result = validate_ipa(archive)
    assert result['required_sdk_privacy_manifests'] == [{
        'sdk': 'share_plus', 'framework': _SHARE_FRAMEWORK.rstrip('/'), 'manifests': [location],
    }]


@pytest.mark.parametrize('location', [
    _APP + 'unrelated.bundle/PrivacyInfo.xcprivacy',
    _APP + 'Frameworks/another.framework/share_plus_privacy.bundle/PrivacyInfo.xcprivacy',
    _APP + 'Frameworks/share_plus.framework/Resources/PrivacyInfo.xcprivacy',
])
def test_other_sdk_or_misplaced_resource_does_not_satisfy_share_sdk(tmp_path, monkeypatch, location):
    archive = _sdk_archive(tmp_path, monkeypatch, {location: plistlib.dumps(_VALID_MANIFEST)})
    with pytest.raises(ValueError, match='Missing SDK privacy manifest for share_plus'):
        validate_ipa(archive)


@pytest.mark.parametrize('data', [
    b'not a property list', b'<?xml version="1.0"?><plist><dict>',
    plistlib.dumps([]), plistlib.dumps({}),
    plistlib.dumps({'NSPrivacyTracking': 'false'}),
    plistlib.dumps({'NSPrivacyTracking': False, 'unexpected_key': 1}),
    plistlib.dumps({'NSPrivacyAccessedAPITypes': ['invalid']}),
    plistlib.dumps({'NSPrivacyAccessedAPITypes': [{
        'NSPrivacyAccessedAPIType': 'NSPrivacyAccessedAPICategoryFileTimestamp',
        'NSPrivacyAccessedAPITypeReasons': 'C617.1',
    }]}),
])
def test_malformed_or_invalid_manifest_cannot_pass_presence_check(tmp_path, monkeypatch, data):
    location = _SHARE_FRAMEWORK + 'PrivacyInfo.xcprivacy'
    archive = _sdk_archive(tmp_path, monkeypatch, {location: data})
    with pytest.raises(ValueError, match='Invalid SDK privacy manifest'):
        validate_ipa(archive)


def test_unsigned_app_checks_sdk_manifest_before_allowing_export(tmp_path, monkeypatch):
    monkeypatch.setattr(native_gate, '_inspect', lambda path, name: {
        'file': name, 'architectures': ['arm64'], 'platforms': ['IOS'],
    })
    app = tmp_path / 'Runner.app'
    framework = app / 'Frameworks/share_plus.framework'
    framework.mkdir(parents=True)
    (framework / 'share_plus').write_bytes(bytes.fromhex('cffaedfe') + b'fixture')
    with pytest.raises(ValueError, match='Missing SDK privacy manifest for share_plus'):
        native_gate.validate_app(app)
    (framework / 'PrivacyInfo.xcprivacy').write_bytes(plistlib.dumps(_VALID_MANIFEST))
    assert native_gate.validate_app(app)['required_sdk_privacy_manifests'][0]['sdk'] == 'share_plus'
