"""Reject simulator or non-iOS Mach-O files before exporting/uploading an app.

Uses Apple's installed inspection tools only. Never signs, executes, uploads,
or changes an artifact. IPA members are inspected in flat temporary files.
"""
import argparse
import json
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
from xml.parsers.expat import ExpatError
import zipfile

_MACHO = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
    'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca',
)}
_MAX_BINARY = 256 * 1024 * 1024
_MAX_MANIFEST = 1024 * 1024
# SDK-specific names prevent an unrelated app/SDK manifest hiding this omission.
_REQUIRED_SDK_BUNDLES = {
    'share_plus': ('share_plus_privacy.bundle', 'share_plus_share_plus.bundle'),
}


def _validate_privacy_manifest(data, name):
    """Check plist structure, not Apple's full API/reason policy or approval."""
    if len(data) > _MAX_MANIFEST:
        raise ValueError(f'SDK privacy manifest exceeds the size bound: {name}.')
    try:
        manifest = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError, ExpatError):
        raise ValueError(f'Invalid SDK privacy manifest plist: {name}.') from None
    known = {'NSPrivacyTracking', 'NSPrivacyTrackingDomains',
             'NSPrivacyCollectedDataTypes', 'NSPrivacyAccessedAPITypes'}
    valid = isinstance(manifest, dict) and bool(manifest) and set(manifest).issubset(known)
    if valid:
        if 'NSPrivacyTracking' in manifest:
            valid = type(manifest['NSPrivacyTracking']) is bool
        domains = manifest.get('NSPrivacyTrackingDomains', [])
        valid = valid and isinstance(domains, list) and all(isinstance(v, str) and v for v in domains)
        if manifest.get('NSPrivacyTracking') is True:
            valid = valid and bool(domains)
        for key, category, values in (
            ('NSPrivacyAccessedAPITypes', 'NSPrivacyAccessedAPIType', 'NSPrivacyAccessedAPITypeReasons'),
            ('NSPrivacyCollectedDataTypes', 'NSPrivacyCollectedDataType', 'NSPrivacyCollectedDataTypePurposes'),
        ):
            entries = manifest.get(key, [])
            valid = valid and isinstance(entries, list)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                valid = valid and isinstance(entry, dict)
                if not isinstance(entry, dict):
                    continue
                valid = valid and isinstance(entry.get(category), str) and bool(entry[category])
                reasons = entry.get(values)
                valid = valid and isinstance(reasons, list) and bool(reasons)
                valid = valid and isinstance(reasons, list) and all(isinstance(v, str) and v for v in reasons)
                if key == 'NSPrivacyCollectedDataTypes':
                    valid = valid and all(type(entry.get(k)) is bool for k in (
                        'NSPrivacyCollectedDataTypeLinked', 'NSPrivacyCollectedDataTypeTracking',
                    ))
    if not valid:
        raise ValueError(f'Invalid SDK privacy manifest fields: {name}.')


def _validate_sdk_privacy_manifests(binaries, exists, read):
    checked = []
    for binary in binaries:
        path = Path(binary['file'])
        sdk = path.name
        if sdk not in _REQUIRED_SDK_BUNDLES or path.parent.name != f'{sdk}.framework':
            continue
        framework = path.parent
        container = framework.parent.parent
        candidates = [framework / 'PrivacyInfo.xcprivacy']
        for bundle in _REQUIRED_SDK_BUNDLES[sdk]:
            candidates.extend((framework / bundle / 'PrivacyInfo.xcprivacy',
                               container / bundle / 'PrivacyInfo.xcprivacy'))
        present = [str(candidate) for candidate in candidates if exists(str(candidate))]
        if not present:
            raise ValueError(f'Missing SDK privacy manifest for {sdk}: {framework}.')
        for name in present:
            _validate_privacy_manifest(read(name), name)
        checked.append({'sdk': sdk, 'framework': str(framework), 'manifests': present})
    return checked


def validate_tool_output(architectures, build_versions):
    arches = architectures.split()
    platforms = re.findall(r'^\s*platform\s+(\S+)\s*$', build_versions, re.MULTILINE)
    legacy = set(re.findall(r'^\s*cmd\s+(LC_VERSION_MIN_[A-Z_]+)\s*$', build_versions, re.MULTILINE))
    if not arches or not set(arches) <= {'arm64', 'arm64e'}:
        raise ValueError('Native binary contains a non-device architecture.')
    if legacy - {'LC_VERSION_MIN_IPHONEOS'}:
        raise ValueError('Native binary contains a non-iOS legacy platform.')
    if not platforms and legacy == {'LC_VERSION_MIN_IPHONEOS'}:
        platforms = ['IOS']
    if not platforms or set(platforms) != {'IOS'}:
        raise ValueError('Native binary contains a missing or non-device iOS platform.')
    return {'architectures': arches, 'platforms': platforms,
            'legacy_iphoneos_metadata': bool(legacy)}


def _inspect(path, name):
    results = []
    for tool, option in [('lipo', '-archs'), ('vtool', '-show-build')]:
        result = subprocess.run(['xcrun', tool, option, str(path)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError(f'Apple native inspection failed for {name}.')
        results.append(result.stdout)
    try:
        return {'file': name, **validate_tool_output(*results)}
    except ValueError as error:
        raise ValueError(f'{name}: {error}') from None


def validate_app(app):
    app = Path(app)
    if not app.is_dir() or app.suffix != '.app':
        raise ValueError('An existing iOS .app directory is required.')
    binaries = []
    for path in sorted(app.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symbolic links are not supported in this iOS artifact check.')
        if not path.is_file():
            continue
        with path.open('rb') as source:
            magic = source.read(4)
        if magic in _MACHO:
            binaries.append(_inspect(path, str(path.relative_to(app))))
    if not binaries:
        raise ValueError('No native iOS binaries were found.')
    def read_manifest(name):
        with (app / name).open('rb') as source:
            return source.read(_MAX_MANIFEST + 1)
    manifests = _validate_sdk_privacy_manifests(
        binaries, lambda name: (app / name).is_file(), read_manifest,
    )
    return {'status': 'DEVICE_NATIVE_PLATFORMS_VERIFIED', 'binaries': binaries,
            'required_sdk_privacy_manifests': manifests}


def validate_ipa(ipa):
    binaries = []
    with tempfile.TemporaryDirectory(prefix='asb-ios-native-check-') as folder:
        with zipfile.ZipFile(ipa) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = member.filename
                if (name.startswith('/')
                        or '..' in Path(name).parts or '\\' in name
                        or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError('Unexpected IPA member path or symbolic link.')
                if not name.startswith('Payload/'):
                    continue
                with archive.open(member) as source:
                    magic = source.read(4)
                    if magic not in _MACHO:
                        continue
                    if member.file_size > _MAX_BINARY:
                        raise ValueError('Native binary exceeds the inspection size bound.')
                    path = Path(folder) / f'binary-{len(binaries)}'
                    path.write_bytes(magic + source.read(_MAX_BINARY + 1))
                if path.stat().st_size != member.file_size:
                    raise ValueError('Native binary length does not match the IPA entry.')
                binaries.append(_inspect(path, name))
            def read_manifest(name):
                with archive.open(name) as source:
                    return source.read(_MAX_MANIFEST + 1)
            manifests = _validate_sdk_privacy_manifests(
                binaries, lambda name: name in archive.namelist(), read_manifest,
            )
    if not binaries:
        raise ValueError('No native iOS binaries were found.')
    return {'status': 'DEVICE_NATIVE_PLATFORMS_VERIFIED', 'binaries': binaries,
            'required_sdk_privacy_manifests': manifests}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ipa', type=Path)
    group.add_argument('--app', type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_ipa(args.ipa) if args.ipa else validate_app(args.app)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'BLOCKED', 'message': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
