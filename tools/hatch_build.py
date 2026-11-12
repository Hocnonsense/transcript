"""Build hook: compile the browser assets before packaging.

Source builds require ``esbuild`` and always refresh the committed ``*.min.*``
assets from TypeScript and CSS before the wheel or sdist is assembled. Installed
wheels only contain the compiled assets and do not need ``esbuild`` at runtime.

Editable installs are skipped: they import assets directly from the source tree
and are installed by ``pixi`` inside a build-isolation environment that has no
``esbuild``. The frontend is built explicitly by the ``frontend``/``test``
tasks instead.
"""

import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if version == "editable":
            return
        script = Path(__file__).resolve().with_name("build_frontend.py")
        subprocess.run([sys.executable, str(script)], check=True)
