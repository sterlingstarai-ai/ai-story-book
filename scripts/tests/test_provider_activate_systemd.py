from types import SimpleNamespace
import unittest
from unittest import mock

import provider_activate_systemd as systemd


def unit_state(unit):
    value = {key: '' for key in systemd.PROPERTIES}
    value.update(Id=unit, LoadState='loaded', UnitFileState='enabled', NeedDaemonReload='no',
                 ExecStart='{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 synthetic ; }')
    return value


class SystemdActivationTests(unittest.TestCase):
    def test_show_requires_exact_unit_and_all_fixed_properties(self):
        values = unit_state(systemd.UNITS[0])
        payload = ''.join(f'{key}={value}\n' for key, value in values.items()).encode()
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=payload))
        self.assertEqual(systemd.show(systemd.UNITS[0], runner=runner), values)
        runner.return_value.stdout = b'Id=wrong\nLoadState=loaded\n'
        with self.assertRaises(systemd.SystemdActivationError):
            systemd.show(systemd.UNITS[0], runner=runner)

    def test_not_found_unit_can_have_only_basic_properties(self):
        unit = systemd.UNITS[0]
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=f'Id={unit}\nLoadState=not-found\n'.encode()))
        self.assertEqual(systemd.show(unit, runner=runner), {'Id': unit, 'LoadState': 'not-found'})
        baseline = systemd.capture_baseline(query=lambda name: (
            {'Id': name, 'LoadState': 'not-found'} if name == unit else unit_state(name)))
        self.assertTrue(systemd.reload_old(baseline, runner=mock.Mock(return_value=SimpleNamespace(returncode=0)),
                                           query=lambda name: ({'Id': name, 'LoadState': 'not-found'}
                                                               if name == unit else unit_state(name))))

    def test_new_reload_must_verify_files_and_loaded_units(self):
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0))
        with mock.patch.object(systemd, 'verify_installed_guard_files') as files, \
             mock.patch.object(systemd, 'verify_loaded_units') as units:
            self.assertTrue(systemd.reload_new(runner=runner, query=unit_state))
        files.assert_called_once()
        units.assert_called_once()
        self.assertIn('daemon-reload', runner.call_args.args[0])

    def test_old_reload_compares_prior_unit_properties(self):
        baseline = systemd.capture_baseline(query=unit_state)
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0))
        self.assertTrue(systemd.reload_old(baseline, runner=runner, query=unit_state))
        def changed(unit):
            state = unit_state(unit)
            if unit == systemd.UNITS[0]:
                state['FragmentPath'] = '/other'
            return state
        with self.assertRaises(systemd.SystemdActivationError):
            systemd.reload_old(baseline, runner=runner, query=changed)

    def test_failed_reload_is_not_success(self):
        runner = mock.Mock(return_value=SimpleNamespace(returncode=1))
        with self.assertRaises(systemd.SystemdActivationError):
            systemd.reload_new(runner=runner, query=unit_state)


if __name__ == '__main__':
    unittest.main()
