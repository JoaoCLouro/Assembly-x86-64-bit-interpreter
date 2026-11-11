"""
Helper script run as a subprocess by the integration test suite.

This script is kept as a subprocess entry point anyway, for two reasons:
1. It's still invoked via subprocess.run() from tests/integration/conftest.py's
   run_asm fixture, so keeping this file's own behavior stable (read argv,
   print __STATE__<json>, exit 0) avoids having to touch the test fixture's
   subprocess-based interface at the same time as this interpreter interface
   change.
2. Isolation from the pytest process is still a nice safety property in
   general (e.g. if a future change reintroduces a code path that really
   does call sys.exit() unguarded), even though it's no longer strictly
   required for the exit syscall specifically.

Protocol:
    python _runner.py <asm_file_path>

On success, prints two lines to stdout:
    __EXIT_CODE__<int>
    __STATE__<json>
The first is the raw integer ExitCode returned directly by run() - kept
separate from the state dict, since it's the interpreter's own direct
run() result, not part of register/memory state. The second is
get_state("all")'s state dict. Any output the program itself wrote to
stdout (e.g. via the `write` syscall) appears before both marker lines,
since it's written during execution, prior to this script's own final
printing.
"""

import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_project_root(start_dir: str) -> str:
    current = start_dir
    while True:
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(f"Could not find a 'pyproject.toml' above {start_dir}")
        current = parent


_PROJECT_ROOT = _find_project_root(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from interpreter import Interpreter


def main() -> None:
    asm_path = sys.argv[1]

    interp = Interpreter(file_name=asm_path, args=["_"])

    exit_code = interp.run()
    state = interp.get_state("all", 10)

    sys.stdout.write("__EXIT_CODE__" + str(int(exit_code)) + "\n")
    sys.stdout.write("__STATE__" + json.dumps(state) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
