# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class GoCheckstyleIntegrationTest(PantsRunIntegrationTest):
    def test_go_compile_go_with_readme_should_not_fail_checkstyle(self):
        args = ["compile", "contrib/go/examples/src/go/with_readme"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
