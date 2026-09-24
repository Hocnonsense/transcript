"""Build hook: compile the browser assets before packaging.

Source builds require ``esbuild`` and always refresh the committed ``*.min.*``
assets from TypeScript and CSS before the wheel or sdist is assembled. Installed
wheels only contain the compiled assets and do not need ``esbuild`` at runtime.
"""

import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        script = Path(__file__).resolve().with_name("build_frontend.py")
        subprocess.run([sys.executable, str(script)], check=True)
