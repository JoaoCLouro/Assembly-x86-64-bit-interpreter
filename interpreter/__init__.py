# interpreter/__init__.py

from .exit_codes import ExitCode
from .interpreter import Interpreter_x86 as Interpreter

__all__ = ["ExitCode", "Interpreter"]
