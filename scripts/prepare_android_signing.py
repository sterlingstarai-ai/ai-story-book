"""Create local Android upload signing material once, without exposing passwords.

Existing material is never overwritten. Passwords go to keytool through environment
variables, not argv; key.properties and the keystore stay in protected ignored paths.
This does not register the key with Play Console or build/publish an application.
"""

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    android = ROOT / "apps/mobile/android"
    key_dir = android / ".signing"
    properties = android / "key.properties"
    if properties.exists() or properties.is_symlink() or key_dir.exists() or key_dir.is_symlink():
        print("Signing setup stopped: existing key.properties or .signing material must be preserved.")
        return 1
    keytool = shutil.which("keytool")
    if not keytool:
        print("Signing setup stopped: JDK keytool is unavailable.")
        return 1
    os.umask(0o077)
    created_properties = False
    created_directory = False
    try:
        key_dir.mkdir(mode=0o700)
        created_directory = True
        keystore = key_dir / "upload-key.jks"
        store_password = secrets.token_urlsafe(48)
        key_password = secrets.token_urlsafe(48)
        environment = {name: os.environ[name] for name in ("PATH", "JAVA_HOME", "HOME", "LANG") if name in os.environ}
        environment.update(STORYBOOK_STORE_PASSWORD=store_password, STORYBOOK_KEY_PASSWORD=key_password)
        command = [keytool, "-genkeypair", "-noprompt", "-storetype", "JKS", "-keystore", str(keystore),
                   "-storepass:env", "STORYBOOK_STORE_PASSWORD", "-keypass:env", "STORYBOOK_KEY_PASSWORD",
                   "-alias", "storybook-upload", "-keyalg", "RSA", "-keysize", "4096",
                   "-sigalg", "SHA256withRSA", "-validity", "10000", "-dname", "CN=AI Story Book Upload, OU=Mobile"]
        result = subprocess.run(command, env=environment, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError("keytool generation failed")
        keystore.chmod(0o600)
        certificate = key_dir / "upload-certificate.pem"
        exported = subprocess.run([keytool, "-exportcert", "-rfc", "-keystore", str(keystore),
                                   "-storepass:env", "STORYBOOK_STORE_PASSWORD", "-alias", "storybook-upload"],
                                  env=environment, capture_output=True, timeout=30)
        if exported.returncode:
            raise RuntimeError("keytool verification failed")
        public_pem = exported.stdout.decode()
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(public_pem)).hexdigest()
        certificate.write_text(public_pem)
        descriptor = os.open(properties, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created_properties = True
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"storePassword={store_password}\nkeyPassword={key_password}\n"
                         f"keyAlias=storybook-upload\nstoreFile={keystore}\n")
        print("Android upload signing prepared; no application was published.")
        print(f"Private keystore: {keystore}")
        print(f"Private password configuration: {properties}")
        print(f"Public certificate SHA-256: {fingerprint}")
        print("Back up the keystore and password configuration together in encrypted storage outside this checkout.")
        return 0
    except BaseException as exc:
        # Remove only material exclusively created by this run. Never print SDK output or secrets.
        if created_properties:
            properties.unlink(missing_ok=True)
        if created_directory:
            shutil.rmtree(key_dir)
        print(f"Signing preparation failed ({type(exc).__name__}); newly created incomplete material removed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
