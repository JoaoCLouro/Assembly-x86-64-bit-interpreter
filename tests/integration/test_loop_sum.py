"""
Integration test: conditional jumps (jg) and unconditional jumps (jmp)
forming a summation loop. See tests/asm_files/loop_sum.asm.
"""

import pytest

from conftest import LIBS_PRESENT

pytestmark = pytest.mark.skipif(
    not LIBS_PRESENT, reason="libreg.so / libmmu.so not built"
)


def test_loop_sum_accumulator(run_asm):
    result = run_asm("loop_sum.asm")
    regs = result.registers

    # Loop sums 1..5 into rbx; rcx is left one past the final counter
    # value that failed the "cmp rcx, 5 / jg loop_end" check.
    assert regs["rbx"] == 15  # 1+2+3+4+5
    assert regs["rcx"] == 6  # counter incremented past the loop bound


def test_loop_sum_exits_cleanly(run_asm):
    result = run_asm("loop_sum.asm")
    assert result.returncode == 0
