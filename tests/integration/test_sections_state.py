"""
Integration test: .data, .rodata, .bss variable declarations, verified
both by register loads and by direct memory-section state.
See tests/asm_files/sections_state.asm.
"""

import pytest

from conftest import LIBS_PRESENT

pytestmark = pytest.mark.skipif(
    not LIBS_PRESENT, reason="libreg.so / libmmu.so not built"
)


def test_sections_register_loads(run_asm):
    result = run_asm("sections_state.asm")
    regs = result.registers

    assert regs["r8"] == 42  # loaded from .data counter
    assert regs["r9"] == 1  # loaded from .data flag
    assert regs["r10"] == 100  # loaded from .rodata max_val
    assert regs["r11"] == 7  # loaded back from .bss scratch after write


def test_sections_memory_state(run_asm):
    result = run_asm("sections_state.asm")
    state = result.registers  # get_state("all") merges every section in (flat dict)

    assert state["counter"] == 42
    assert state["flag"] == 1
    assert state["max_val"] == 100
    assert state["scratch"] == 7

    # buffer was declared via `times 5 dd 0` and never written to, so it
    # should still read back as zero.
    assert state["buffer"] == 0


def test_sections_state_exits_cleanly(run_asm):
    result = run_asm("sections_state.asm")
    assert result.returncode == 0
