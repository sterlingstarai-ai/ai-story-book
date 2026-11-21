"""Operator credentials may only be read from an owner-controlled directory."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gcloud_operator_config import operator_gcloud_config


class GcloudOperatorConfigTest(unittest.TestCase):
    def test_private_operator_config(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            chosen = Path(root) / "gcloud"
            chosen.mkdir(mode=0o700)
            with patch.dict(os.environ, {"CLOUDSDK_CONFIG": str(chosen)}):
                self.assertEqual(operator_gcloud_config(), str(chosen))
            chosen.chmod(0o755)
            with self.assertRaises(ValueError):
                operator_gcloud_config(str(chosen))

    def test_shared_ancestor_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            root = Path(root)
            config = root / "config"
            config.mkdir(mode=0o700)
            alt = root / "alias"
            alt.symlink_to(config, target_is_directory=True)
            with self.assertRaises(ValueError):
                operator_gcloud_config(str(alt))
            root.chmod(0o770)
            with self.assertRaises(ValueError):
                operator_gcloud_config(str(config))
