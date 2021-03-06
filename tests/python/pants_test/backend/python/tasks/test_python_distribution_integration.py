# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import os
import sys

from pants.util.contextutil import temporary_dir
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonDistributionIntegrationTest(PantsRunIntegrationTest):
  # The paths to both a project containing a simple C extension (to be packaged into a
  # whl by setup.py) and an associated test to be consumed by the pants goals tested below.
  fasthello_project = 'examples/src/python/example/python_distribution/hello/fasthello'
  fasthello_tests = 'examples/tests/python/example/python_distribution/hello/test_fasthello'
  fasthello_install_requires = 'testprojects/src/python/python_distribution/fasthello_with_install_requires'

  def _assert_native_greeting(self, output):
    self.assertIn('Hello from C!', output)
    self.assertIn('Hello from C++!', output)

  def test_pants_binary(self):
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main.pex')
      wheel_glob = os.path.join(tmp_dir, 'fasthello-1.0.0-*.whl')
      command=[
        '--pants-distdir={}'.format(tmp_dir), 'binary', '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex)
      self._assert_native_greeting(output)
      # Check that we have exact one wheel output
      self.assertEqual(len(glob.glob(wheel_glob)), 1)

  def test_pants_run(self):
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that text was properly printed to stdout.
      self._assert_native_greeting(pants_run.stdout_data)

  def test_pants_test(self):
    with temporary_dir() as tmp_dir:
      wheel_glob = os.path.join(tmp_dir, 'fasthello-1.0.0-*.whl')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'test',
        '{}:fasthello'.format(self.fasthello_tests)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Make sure that there is no wheel output when 'binary' goal is not invoked.
      self.assertEqual(len(glob.glob(wheel_glob)), 0)

  def test_with_install_requires(self):
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main_with_no_conflict.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main_with_no_conflict'.format(self.fasthello_install_requires)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      self.assertIn('United States', pants_run.stdout_data)
      command=['binary', '{}:main_with_no_conflict'.format(self.fasthello_install_requires)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      output = subprocess.check_output(pex)
      self.assertIn('United States', output)

  def test_with_conflicting_transitive_deps(self):
    command=['run', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)
    command=['binary', '{}:main_with_conflicting_dep'.format(self.fasthello_install_requires)]
    pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertIn('pycountry', pants_run.stderr_data)
    self.assertIn('fasthello', pants_run.stderr_data)

  def test_pants_binary_dep_isolation_with_multiple_targets(self):
    with temporary_dir() as tmp_dir:
      pex1 = os.path.join(tmp_dir, 'main_with_no_conflict.pex')
      pex2 = os.path.join(tmp_dir, 'main_with_no_pycountry.pex')
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'binary',
        '{}:main_with_no_conflict'.format(self.fasthello_install_requires),
        '{}:main_with_no_pycountry'.format(self.fasthello_install_requires)]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex1))
      self.assertTrue(os.path.isfile(pex2))
      # Check that the pex 1 runs.
      output = subprocess.check_output(pex1)
      self._assert_native_greeting(output)
      # Check that the pex 2 fails due to no python_dists leaked into it.
      try:
        output = subprocess.check_output(pex2)
      except subprocess.CalledProcessError as e:
        self.assertNotEquals(0, e.returncode)

  def test_pants_resolves_local_dists_for_current_platform_only(self):
    # Test that pants will override pants.ini platforms config when building
    # or running a target that depends on native (c or cpp) sources.
    with temporary_dir() as tmp_dir:
      pex = os.path.join(tmp_dir, 'main.pex')
      pants_ini_config = {'python-setup': {'platforms': ['current', 'linux-x86_64']}}
      # Clean all to rebuild requirements pex.
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'run',
        '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command, config=pants_ini_config)
      self.assert_success(pants_run)

      command=['binary', '{}:main'.format(self.fasthello_project)]
      pants_run = self.run_pants(command=command, config=pants_ini_config)
      self.assert_success(pants_run)
      # Check that the pex was built.
      self.assertTrue(os.path.isfile(pex))
      # Check that the pex runs.
      output = subprocess.check_output(pex)
      self._assert_native_greeting(output)

  def test_pants_tests_local_dists_for_current_platform_only(self):
    if 'linux' in sys.platform:
      platform_string = 'linux-x86_64'
    else:
      platform_string = 'macosx-10.12-x86_64'
    # Use a platform-specific string for testing because the test goal
    # requires the coverage package and the pex resolver raises an Untranslatable error when
    # attempting to translate the coverage sdist for incompatible platforms.
    pants_ini_config = {'python-setup': {'platforms': [platform_string]}}
    # Clean all to rebuild requirements pex.
    with temporary_dir() as tmp_dir:
      command=[
        '--pants-distdir={}'.format(tmp_dir),
        'clean-all',
        'test',
        '{}:fasthello'.format(self.fasthello_tests)]
      pants_run = self.run_pants(command=command, config=pants_ini_config)
      self.assert_success(pants_run)
