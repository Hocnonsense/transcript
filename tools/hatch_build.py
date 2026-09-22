"""Build hook: minify the browser assets before packaging.

``*.min.*`` files are generated artifacts and are not committed.  Building in an
environment that has ``esbuild`` on ``PATH`` (the Pixi environment) regenerates
them so the wheel embeds the minified assets; an isolated build without esbuild
falls back to the readable sources, which the exporter still accepts.
"""

import subprocess
import sys
from pathlib import Path
from shutil import which

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if which("esbuild") is None:
            self.app.display_warning(
                "esbuild not found on PATH; building with unminified assets"
            )
            return
        script = Path(__file__).resolve().with_name("minify_assets.py")
        subprocess.run([sys.executable, str(script)], check=True)
