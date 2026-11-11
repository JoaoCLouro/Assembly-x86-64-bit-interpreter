"""
Integration test: push/pop/call/ret and the single-integer
argument-in-rdi convention. See tests/asm_files/stack_call.asm.
"""

import pytest

from interpreter._paths import LIBS_PRESENT

pytestmark = pytest.mark.skipif(
    not LIBS_PRESENT, reason="libreg.so / libmmu.so not built"
)


def test_call_ret_return_value(run_asm):
    result = run_asm("stack_call.asm")
    regs = result.registers

    # add_five(12) == 17, saved into rbx before rax gets reused for the
    # exit syscall setup.
    assert regs["rbx"] == 17


def test_stack_call_exits_cleanly(run_asm):
    result = run_asm("stack_call.asm")
    assert result.returncode == 0
