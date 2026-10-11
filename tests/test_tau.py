# -*- coding: utf-8 -*-
"""The Titan alternative updater component (data/components/tau).

Nothing here starts the bat, closes Titan, shows a dialog or touches the
user's own log or state: the log is text handed in, APPDATA is a temporary
folder, and Popen is replaced.
"""
import gettext
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAU_DIR = os.path.join(ROOT, 'data', 'components', 'tau')


def load_tau():
    spec = importlib.util.spec_from_file_location(
        'tau_under_test', os.path.join(TAU_DIR, 'init.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tau = load_tau()


def log(*lines):
    return '\n'.join(lines) + '\n'


OFFER = '2026-10-01 10:00:00 [UPDATER] update offered: 0.6.1 -> 0.6.2'
FAILED = '2026-10-01 10:01:00 [UPDATER] update failed: something'
APPLIED = '2026-10-01 10:01:00 [UPDATER] update applied successfully'
DECLINED = '2026-10-01 10:00:05 [UPDATER] Update declined by user; starting'


class WhatTheLogSays(unittest.TestCase):

    def test_a_failed_update_is_a_problem(self):
        found = tau.find_problem(log(OFFER, FAILED), '0.6.1')
        self.assertEqual(found['outcome'], 'failed')
        self.assertEqual(found['target'], '0.6.2')

    def test_an_applied_update_that_did_not_change_the_version(self):
        found = tau.find_problem(log(OFFER, APPLIED), '0.6.1')
        self.assertEqual(found['outcome'], 'applied')

    def test_an_applied_update_that_did_change_it_is_not(self):
        self.assertIsNone(tau.find_problem(log(OFFER, APPLIED), '0.6.2'))

    def test_a_declined_update_is_not(self):
        self.assertIsNone(tau.find_problem(log(OFFER, DECLINED), '0.6.1'))

    def test_declining_the_repeated_offer_still_finds_the_failure(self):
        again = '2026-10-01 10:05:00 [UPDATER] update offered: 0.6.1 -> 0.6.2'
        no = '2026-10-01 10:05:02 [UPDATER] Update declined by user; x'
        found = tau.find_problem(log(OFFER, APPLIED, again, no), '0.6.1')
        self.assertEqual(found['time'], '2026-10-01 10:00:00')

    def test_an_attempt_already_asked_about_is_not_asked_again(self):
        self.assertIsNone(tau.find_problem(log(OFFER, FAILED), '0.6.1',
                                           '2026-10-01 10:00:00'))

    def test_an_attempt_made_by_another_version_is_left_alone(self):
        old = '2026-09-01 10:00:00 [UPDATER] update offered: 0.5.9 -> 0.6.0'
        old_fail = '2026-09-01 10:01:00 [UPDATER] update failed: x'
        self.assertIsNone(tau.find_problem(log(old, old_fail), '0.6.1'))

    def test_no_log_and_no_version(self):
        self.assertIsNone(tau.find_problem('', '0.6.1'))
        self.assertIsNone(tau.find_problem(log(OFFER, FAILED), None))


class TheAnswerIsRemembered(unittest.TestCase):

    def test_remember_and_read_back(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {'APPDATA': home}):
            self.assertEqual(tau.handled_after(), '')
            tau.remember('2026-10-01 10:00:00')
            self.assertEqual(tau.handled_after(), '2026-10-01 10:00:00')

    def test_the_rotated_log_is_read_too(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {'APPDATA': home}):
            logs = os.path.join(home, 'titosoft', 'Titan', 'logs')
            os.makedirs(logs)
            with open(os.path.join(logs, 'update.log.1'), 'w') as f:
                f.write(OFFER + '\n')
            with open(os.path.join(logs, 'update.log'), 'w') as f:
                f.write(FAILED + '\n')
            found = tau.find_problem(tau.read_log(), '0.6.1')
            self.assertEqual(found['outcome'], 'failed')


class TheBatIsRunFromACopy(unittest.TestCase):

    def test_the_bat_ships_in_the_component(self):
        with open(os.path.join(TAU_DIR, 'updater.bat'), 'rb') as f:
            data = f.read()
        self.assertIn(b'/wait', data)
        self.assertIn(b'/restart', data)
        self.assertNotIn(b'\n', data.replace(b'\r\n', b''),
                         "cmd.exe needs CRLF for its labels")

    def test_start_updater_runs_a_copy_with_its_arguments(self):
        with tempfile.TemporaryDirectory() as install, \
                tempfile.TemporaryDirectory() as temp:
            open(os.path.join(install, 'Titan.exe'), 'w').close()
            with mock.patch.object(tau.sys, 'platform', 'win32'), \
                    mock.patch.object(tau, 'install_dir', lambda: install), \
                    mock.patch.object(tau.tempfile, 'gettempdir',
                                      lambda: temp), \
                    mock.patch.object(tau.subprocess, 'Popen') as popen:
                self.assertTrue(tau.start_updater())
            args = popen.call_args[0][0]
            copy = os.path.join(temp, 'titan_tau', 'updater.bat')
            self.assertTrue(os.path.exists(copy))
            self.assertEqual(args[:4], ['cmd.exe', '/c', copy, install])
            self.assertEqual(args[4:], ['/y', '/wait', '/restart'])

    def test_from_source_it_says_why_not(self):
        with mock.patch.object(tau.sys, 'platform', 'win32'), \
                mock.patch.object(tau, 'install_dir', lambda: None):
            self.assertIsNotNone(tau.can_run())


class ThePolishSaysIt(unittest.TestCase):

    def test_the_question_in_polish(self):
        pl = gettext.translation('tau', os.path.join(TAU_DIR, 'languages'),
                                 languages=['pl'])
        self.assertEqual(
            pl.gettext("It looks like there was an update error. "
                       "Do you want to use the alternative updater?"),
            "Wygląda na to, że wystąpił błąd aktualizacji. "
            "Czy chcesz użyć alternatywnego aktualizatora?")


if __name__ == '__main__':
    unittest.main()
