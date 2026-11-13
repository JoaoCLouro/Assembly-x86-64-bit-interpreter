"""
Shared setup for tests/.

Finds the project root by walking upward looking for `pyproject.toml`,
rather than looking for a specific nested source directory. Anchoring on
the marker file (not a hardcoded path shape like `_src/bridges` or
`interpreter/_src/bridges`) means internal folder reorganizations never
break this again -- pyproject.toml only moves if the whole project moves,
and if that happens the fix is the same either way: nothing, since the
walk-up still finds it relative to wherever the repo now lives.

This project is pip-installed in editable mode (`pip install -e .` from
the project root, see pyproject.toml), which makes `bridges`, `FUs`,
`helpers`, and `parsing` importable as top-level packages
(`from bridges.register_manager import ...`) regardless of where the repo
sits on disk. This conftest no longer manually inserts bridges/ onto
sys.path -- that's what previously broke every time _src moved, and it's
no longer needed once the editable install is in place.

If you ever relocate the whole repo to a new path, just re-run
`pip install -e .` once from the new location.
"""

import ctypes
import importlib.util
import os
import sys


def _find_project_root(start_dir: str) -> str:
    current = start_dir
    while True:
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(
                f"Could not find a 'pyproject.toml' above {start_dir} -- "
                "is this test file still somewhere inside the project tree?"
            )
        current = parent


PROJECT_ROOT = _find_project_root(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, "interpreter", "_src") + os.sep
CACHE_DIR = os.path.join(SRC_ROOT, "program_cache")

LIBREG_PATH = os.path.join(SRC_ROOT, "lib", "libreg.so")
LIBMMU_PATH = os.path.join(SRC_ROOT, "lib", "libmmu.so")
LIBS_PRESENT = os.path.exists(LIBREG_PATH) and os.path.exists(LIBMMU_PATH)

# Add SRC_ROOT to sys.path so tests can import internal folders directly
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


def _load_c_lib(lib_name: str) -> ctypes.CDLL:
    spec = importlib.util.find_spec(f"interpreter._src.lib.{lib_name}")
    if spec is None or spec.origin is None:
        raise FileNotFoundError(
            f"Compiled C extension '{lib_name}' was not found. "
            "Install the package with 'uv sync' or 'pip install -e .'."
        )
    return ctypes.CDLL(spec.origin)


libmmu = _load_c_lib("libmmu")
libregisters = _load_c_lib("libregisters")
liboperations = _load_c_lib("liboperations")
libsyscall = _load_c_lib("libsyscall")
