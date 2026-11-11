"""
Integration test: the `write` syscall (writing to real stdout, fd 1)
followed by `exit`. See tests/asm_files/syscall_write.asm.

Because `write` performs real host I/O (per assembly_specs.md, section
7 "System Calls"), the subprocess's actual stdout is asserted on
directly, rather than only checking register state.
"""

import pytest

from interpreter._paths import LIBS_PRESENT

pytestmark = pytest.mark.skipif(
    not LIBS_PRESENT, reason="libreg.so / libmmu.so not built"
)


def test_write_syscall_output(run_asm):
    result = run_asm("syscall_write.asm")

    # The program writes exactly "hi\n" (3 bytes) to fd 1 (stdout).
    assert result.program_output == "hi\n"


def test_write_syscall_return_value(run_asm):
    result = run_asm("syscall_write.asm")
    regs = result.registers

    # r8 preserves the write() syscall's return value (bytes written)
    # before rax gets reused to stage the exit syscall.
    assert regs["r8"] == 3


def test_write_syscall_exits_cleanly(run_asm):
    result = run_asm("syscall_write.asm")
    assert result.returncode == 0
