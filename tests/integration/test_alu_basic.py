"""
Integration test: basic ALU operations (add, sub, xor, and, or, inc, dec).

See tests/asm_files/alu_basic.asm for the exact instruction sequence and
the expected values below.
"""

import pytest

from interpreter._paths import LIBS_PRESENT

pytestmark = pytest.mark.skipif(
    not LIBS_PRESENT, reason="libreg.so / libmmu.so not built"
)


def test_alu_basic_register_values(run_asm):
    result = run_asm("alu_basic.asm")
    regs = result.registers

    # rax and rdi are deliberately reused right before the exit syscall
    # (mov rax, 60 / xor rdi, rdi), so they reflect the syscall setup,
    # not the earlier ALU result. rax == 60 confirms the exit syscall
    # path was actually taken.
    assert regs["rax"] == 60
    assert regs["rdi"] == 0

    assert regs["rbx"] == 4  # 10 - 6
    assert regs["rcx"] == 12  # 10 XOR 6
    assert regs["rdx"] == 2  # 10 AND 6
    assert regs["r8"] == 14  # 10 OR 6
    assert regs["r9"] == 6  # 5 + 1 (inc)
    assert regs["r10"] == 4  # 5 - 1 (dec)


def test_alu_basic_exits_cleanly(run_asm):
    result = run_asm("alu_basic.asm")
    assert result.returncode == 0
