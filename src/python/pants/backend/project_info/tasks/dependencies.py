# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.payload_field import JarsField, PythonRequirementsField
from pants.task.console_task import ConsoleTask
from collections import defaultdict
import json


class Dependencies(ConsoleTask):
  """Print the target's dependencies."""

  @staticmethod
  def _is_jvm(target):
    return isinstance(target, (JarLibrary, JvmTarget, JvmApp))

  @classmethod
  def register_options(cls, register):
    super(Dependencies, cls).register_options(register)
    register('--internal-only', type=bool,
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--external-only', type=bool,
             help='Specifies that only external dependencies should be included in the graph '
                  'output (only external jars).')
    register('--transitive', default=True, type=bool,
             help='List transitive dependencies. Disable to only list dependencies defined '
                  'in target BUILD file(s).')
    register('--output-format', default='text', choices=['text', 'json'],
             help='Output format of results.')

  def __init__(self, *args, **kwargs):
    super(Dependencies, self).__init__(*args, **kwargs)

    self.is_internal_only = self.get_options().internal_only
    self.is_external_only = self.get_options().external_only
    self._transitive = self.get_options().transitive
    if self.is_internal_only and self.is_external_only:
      raise TaskError('At most one of --internal-only or --external-only can be selected.')

  def console_output(self, unused_method_argument):
    if self.get_options().output_format == 'json':
      dependencies = defaultdict(list)
      for target in self.context.target_roots:
        if self._transitive:
          trans_deps = OrderedSet()
          target.walk(trans_deps.add)
          dependencies.update({target.address.spec: trans_deps})
        else:
          dependencies.update({target.address.spec: target.dependencies})

      for target in dependencies:
        # Some nodes are ScalaLibrary, JarLibrary, etc wrapped around BuildFileAddress and some are string paths
        string_paths = filter(lambda x: type(x) == str, dependencies[target])
        libs = filter(lambda x: type(x) != str, dependencies[target])
        lib_paths = [dep.address.spec for dep in libs]

        dependencies.update({target: sorted(string_paths + lib_paths)})

      yield json.dumps(dependencies, indent=4, separators=(',', ': '), sort_keys=True)

    else:
      deps = OrderedSet()
      for target in self.context.target_roots:
        if self._transitive:
          target.walk(deps.add)
        else:
          deps.update(target.dependencies)
      for tgt in deps:
        if not self.is_external_only:
          yield tgt.address.spec
        if not self.is_internal_only:
          # TODO(John Sirois): We need an external payload abstraction at which point knowledge
          # of jar and requirement payloads can go and this hairball will be untangled.
          if isinstance(tgt.payload.get_field('requirements'), PythonRequirementsField):
            for requirement in tgt.payload.requirements:
              yield str(requirement.requirement)
          elif isinstance(tgt.payload.get_field('jars'), JarsField):
            for jar in tgt.payload.jars:
              data = dict(org=jar.org, name=jar.name, rev=jar.rev)
              yield ('{org}:{name}:{rev}' if jar.rev else '{org}:{name}').format(**data)
