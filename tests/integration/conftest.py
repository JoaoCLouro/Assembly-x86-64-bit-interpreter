"""
Fixtures for tests/integration/ -- full .asm-file-to-Interpreter_x86
integration tests, run end-to-end through a subprocess.

These tests work in two layouts:

* Source checkout: a pyproject.toml exists above this file. The project
  root is put on sys.path (and on PYTHONPATH for the subprocess) so the
  in-tree package is importable even without an editable install.
* Installed wheel (cibuildwheel copies only tests/ to a temp dir): no
  pyproject.toml exists, PROJECT_ROOT is None, and nothing is added to the
  path, so `interpreter` resolves to the installed package.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _find_project_root(start_dir: str) -> str | None:
    """Walk up looking for pyproject.toml. Returns None if there isn't one."""
    current = start_dir
    while True:
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


PROJECT_ROOT = _find_project_root(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT is not None and PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# tests/integration/conftest.py -> parents[1] is tests/, which travels with
# the test files wherever they are copied.
_TESTS_DIR = Path(__file__).resolve().parents[1]
ASM_DIR = _TESTS_DIR / "asm_files"
RUNNER = Path(__file__).resolve().parent / "_runner.py"


class AsmResult:
    """Wraps the outcome of running one .asm file through the interpreter."""

    def __init__(self, returncode: int, stdout: str, stderr: str):
        # Imported lazily so collecting this module never triggers the full
        # `interpreter` import chain.
        from interpreter.exit_codes import ExitCode

        self.returncode = returncode
        self.raw_stdout = stdout
        self.stderr = stderr

        self.program_output = stdout
        self.state = None
        self.exit_code = None

        exit_marker = "__EXIT_CODE__"
        state_marker = "__STATE__"

        idx = stdout.find(exit_marker)
        if idx != -1:
            self.program_output = stdout[:idx]
            rest = stdout[idx + len(exit_marker) :].strip().splitlines()[0]
            if rest == "None":
                self.exit_code = None
            else:
                raw = int(rest)
                try:
                    self.exit_code = ExitCode(raw)
                except ValueError:
                    self.exit_code = raw

        idx = stdout.find(state_marker)
        if idx != -1:
            if self.exit_code is None:
                self.program_output = stdout[:idx]
            json_part = stdout[idx + len(state_marker) :].strip().splitlines()[0]
            self.state = json.loads(json_part)

    @property
    def registers(self) -> dict[str, object]:
        assert self.state is not None, (
            f"No state was captured (process may have crashed before "
            f"finishing). stderr:\n{self.stderr}"
        )
        return self.state


@pytest.fixture
def run_asm():
    """
    Returns a callable: run_asm("filename.asm") -> AsmResult
    Runs the given file (resolved relative to tests/asm_files/) through
    the interpreter in a fresh subprocess and captures its state + stdout.
    """

    def _run(asm_filename: str, timeout: float = 10.0) -> AsmResult:
        asm_path = ASM_DIR / asm_filename
        assert asm_path.exists(), f"Missing test asm file: {asm_path}"

        env = os.environ.copy()
        if PROJECT_ROOT is not None:
            # Source checkout: make the in-tree package importable in the
            # subprocess. Wheel test: leave the environment alone so the
            # installed package is used.
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                PROJECT_ROOT + os.pathsep + existing if existing else PROJECT_ROOT
            )

        proc = subprocess.run(
            [sys.executable, str(RUNNER), str(asm_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT if PROJECT_ROOT is not None else str(_TESTS_DIR),
            env=env,
        )
        return AsmResult(proc.returncode, proc.stdout, proc.stderr)

    return _run
