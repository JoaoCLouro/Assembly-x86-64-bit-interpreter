import ctypes
import importlib.util
import os
import sys
from pathlib import Path


def _find_project_root(start_dir: str) -> str:
    current = start_dir
    while True:
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            # Installed as a non-editable wheel / uv tool (no pyproject.toml above site-packages)
            return os.path.dirname(start_dir)
        current = parent


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = _find_project_root(PACKAGE_DIR)
SRC_ROOT = os.path.join(PACKAGE_DIR, "_src") + os.sep
CACHE_DIR = os.path.join(SRC_ROOT, "program_cache")

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


def _resolve_c_lib_path(lib_name: str) -> str:
    spec = importlib.util.find_spec(f"interpreter._src.lib.{lib_name}")
    if spec is not None and spec.origin is not None:
        return spec.origin

    lib_dir = Path(SRC_ROOT) / "lib"
    matches = [
        p
        for p in lib_dir.glob(f"{lib_name}.*")
        if p.suffix in {".so", ".pyd", ".dylib"}
    ]
    if not matches:
        raise FileNotFoundError(
            f"Compiled C extension '{lib_name}' not found. Run 'uv sync' or 'pip install -e .'."
        )
    return str(matches[0])


LIBREG_PATH = _resolve_c_lib_path("libregisters")
LIBMMU_PATH = _resolve_c_lib_path("libmmu")
LIBOPS_PATH = _resolve_c_lib_path("liboperations")
LIBSCL_PATH = _resolve_c_lib_path("libsyscall")
LIBS_PRESENT = os.path.exists(LIBREG_PATH) and os.path.exists(LIBMMU_PATH)

libregisters = ctypes.CDLL(LIBREG_PATH)
libmmu = ctypes.CDLL(LIBMMU_PATH)
liboperations = ctypes.CDLL(LIBOPS_PATH)
libsyscall = ctypes.CDLL(LIBSCL_PATH)
