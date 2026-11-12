"""Portable tool selection only; no Docker, database or provider calls."""

from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_online_backup_fixture as fixture


class OnlineFixtureToolTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        self.env = {'PATH': '/usr/bin:/bin'}

    def tools(self, name):
        folder = self.root / name
        folder.mkdir()
        for tool in ('pg_dump', 'pg_restore', 'psql'):
            path = folder / tool
            path.write_text('fixed synthetic executable placeholder')
            path.chmod(0o700)
        return folder

    @staticmethod
    def version(command, **kwargs):
        if command[1:] != ['--version'] or kwargs.get('timeout') != 5 or not kwargs.get('check'):
            raise AssertionError('Only bounded version discovery is allowed')
        name = Path(command[0]).name
        major = 17 if 'other-major' in command[0] else 16
        return SimpleNamespace(stdout=f'{name} (PostgreSQL) {major}.11 (packaged build)\n')

    def test_linux_location_is_found_without_homebrew_or_path_tools(self):
        linux = self.tools('linux-pg16')
        with patch.object(fixture, '_PG16_LOCATIONS', (self.root / 'missing-homebrew', linux)), \
                patch.object(fixture.shutil, 'which', return_value=None), \
                patch.object(fixture.subprocess, 'run', side_effect=self.version) as probe:
            self.assertEqual(fixture.find_pg16_bin(self.env), linux)
        self.assertEqual(probe.call_count, 3)

    def test_path_tools_are_supported_when_platform_locations_are_absent(self):
        folder = self.tools('path-pg16')
        with patch.object(fixture, '_PG16_LOCATIONS', (self.root / 'missing',)), \
                patch.object(fixture.shutil, 'which', return_value=str(folder / 'pg_dump')), \
                patch.object(fixture.subprocess, 'run', side_effect=self.version):
            self.assertEqual(fixture.find_pg16_bin(self.env), folder)

    def test_explicit_directory_wins_and_every_binary_major_is_checked(self):
        selected = self.tools('selected')
        fallback = self.tools('fallback')
        with patch.object(fixture, '_PG16_LOCATIONS', (fallback,)), \
                patch.object(fixture.shutil, 'which', return_value=str(fallback / 'pg_dump')), \
                patch.object(fixture.subprocess, 'run', side_effect=self.version) as probe:
            self.assertEqual(fixture.find_pg16_bin(self.env, explicit=str(selected)), selected)
        self.assertEqual({Path(call.args[0][0]).name for call in probe.call_args_list},
                         {'pg_dump', 'pg_restore', 'psql'})

    def test_wrong_explicit_major_does_not_silently_fall_back(self):
        wrong = self.tools('other-major')
        fallback = self.tools('fallback')
        with patch.object(fixture, '_PG16_LOCATIONS', (fallback,)), \
                patch.object(fixture.shutil, 'which', return_value=str(fallback / 'pg_dump')), \
                patch.object(fixture.subprocess, 'run', side_effect=self.version):
            with self.assertRaisesRegex(RuntimeError, 'PostgreSQL 16'):
                fixture.find_pg16_bin(self.env, explicit=str(wrong))

    def test_mixed_major_toolset_is_rejected(self):
        selected = self.tools('mixed')
        def mixed(command, **kwargs):
            result = self.version(command, **kwargs)
            if Path(command[0]).name == 'pg_restore':
                result.stdout = 'pg_restore (PostgreSQL) 17.1\n'
            return result
        with patch.object(fixture.subprocess, 'run', side_effect=mixed):
            with self.assertRaisesRegex(RuntimeError, 'PostgreSQL 16'):
                fixture.find_pg16_bin(self.env, explicit=str(selected))

    def test_missing_or_nonexecutable_binary_cannot_pass(self):
        selected = self.tools('missing-tool')
        (selected / 'psql').unlink()
        with patch.object(fixture.subprocess, 'run', side_effect=self.version):
            with self.assertRaises(RuntimeError):
                fixture.find_pg16_bin(self.env, explicit=str(selected))
        (selected / 'psql').write_text('not executable')
        with patch.object(fixture.subprocess, 'run', side_effect=self.version):
            with self.assertRaises(RuntimeError):
                fixture.find_pg16_bin(self.env, explicit=str(selected))

    def test_tool_failure_is_bounded_and_does_not_expose_output(self):
        selected = self.tools('timeout')
        with patch.object(fixture.subprocess, 'run', side_effect=subprocess.TimeoutExpired('synthetic-secret', 5)):
            with self.assertRaises(RuntimeError) as failure:
                fixture.find_pg16_bin(self.env, explicit=str(selected))
        self.assertNotIn('synthetic-secret', str(failure.exception))


if __name__ == '__main__':
    unittest.main()
