"""Device release gates reject simulator slices even when they are arm64."""
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
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
