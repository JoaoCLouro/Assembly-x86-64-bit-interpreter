"""
Unit tests for FUs/fpu.py

Strategy
--------
FPU.__init__ loads a real compiled shared library via ctypes.CDLL, which we
don't have at unit-test time -- so we patch ctypes.CDLL with a MagicMock,
same as in test_data_manager.py.

FPU also depends on a Registers_Interface and a Data_Memory instance. We
hand it plain MagicMocks for both since FPU only forwards these pointers
into set_registers_ref/set_table_ref without touching them itself.

Run with: pytest tests/FUs/test_fpu.py -v
"""

import ctypes
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from interpreter._src.functional_units.fpu import FPU, FPU_OPCODES
from interpreter._src.parsing.patter_matching_helpers import INSTRUCTIONS

pytestmark = pytest.mark.skipif(
    not FPU_OPCODES,
    reason="FPU_OPCODES is empty -- no FPU instructions defined yet in "
    "patter_matching_helpers.py (operations.h still marks FPU as 'TO IMPLEMENT LATER')",
)


def make_op(
    address: int = 0,
    type_: int = 0,
    size: int = 4,
    is_high: int = 0,
    is_signed: int = 0,
    valid: bool = True,
) -> Any:
    op = SimpleNamespace(
        address=address, type=type_, size=size, is_high=is_high, is_signed=is_signed
    )
    op.is_valid = lambda: valid
    return op


@pytest.fixture
def mock_registers():
    return MagicMock()


@pytest.fixture
def mock_memory():
    return MagicMock()


@pytest.fixture
def fpu(mock_registers: MagicMock, mock_memory: MagicMock):
    """An FPU backed by a MagicMock instead of a real .so."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_lib = MagicMock()
        mock_lib.create_operand_state.return_value = ctypes.c_void_p(0xCAFEBABE)
        mock_cdll.return_value = mock_lib
        instance = FPU(
            registers=mock_registers, memory=mock_memory, libops_path="fake.so"
        )
        yield instance


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_operand_state_and_wires_registers_and_memory(
        self, mock_registers: MagicMock, mock_memory: MagicMock
    ):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            state = ctypes.c_void_p(0x1234)
            mock_lib.create_operand_state.return_value = state
            mock_cdll.return_value = mock_lib

            instance = FPU(
                registers=mock_registers, memory=mock_memory, libops_path="fake.so"
            )

            mock_lib.set_registers_ref.assert_called_once_with(state, mock_registers)
            mock_lib.set_table_ref.assert_called_once_with(state, mock_memory)
            assert instance.state == state

    def test_set_operand_info_argtypes_match_header_order(self, fpu: FPU):
        # operations.h: set_operand_info(Info*, char*, long long address,
        # uint8_t size, uint8_t op_type, uint8_t is_high, uint8_t is_signed)
        argtypes = fpu.lib.set_operand_info.argtypes
        assert argtypes[2] is ctypes.c_longlong
        assert argtypes[3] is ctypes.c_uint8  # size
        assert argtypes[4] is ctypes.c_uint8  # op_type
        assert argtypes[5] is ctypes.c_uint8  # is_high
        assert argtypes[6] is ctypes.c_uint8  # is_signed

    def test_set_instruction_argtype_is_uint8(self, fpu: FPU):
        assert fpu.lib.set_instruction.argtypes[1] is ctypes.c_uint8


# ---------------------------------------------------------------------------
# load_values
# ---------------------------------------------------------------------------


class TestLoadValues:
    def test_clean_called_before_set_instruction(self, fpu: FPU):
        name = next(iter(FPU_OPCODES))
        fpu.load_values(name, make_op(valid=False), make_op(valid=False))

        method_order = [c[0] for c in getattr(fpu.lib, "method_calls", [])]
        assert method_order.index("clean") < method_order.index("set_instruction")

    def test_set_instruction_called_with_offset_opcode(self, fpu: FPU):
        name = next(iter(FPU_OPCODES))
        fpu.load_values(name, make_op(valid=False), make_op(valid=False))

        expected_opcode = FPU_OPCODES[name] + len(INSTRUCTIONS["alu"])
        cast(MagicMock, fpu.lib.set_instruction).assert_called_once_with(
            fpu.state, expected_opcode
        )

    def test_set_operand_info_called_with_size_before_op_type(self, fpu: FPU):
        op1 = make_op(address=0x1000, type_=2, size=8, is_high=0, is_signed=1)
        name = next(iter(FPU_OPCODES))

        fpu.load_values(name, op1, make_op(valid=False))

        cast(MagicMock, fpu.lib.set_operand_info).assert_called_once_with(
            fpu.state,
            b"op1",
            0x1000,
            8,  # size
            2,  # op_type
            0,  # is_high
            1,  # is_signed
        )

    def test_both_operands_loaded_when_valid(self, fpu: FPU):
        op1 = make_op(address=0x1000, type_=1, size=4)
        op2 = make_op(address=0x2000, type_=2, size=8)
        name = next(iter(FPU_OPCODES))

        fpu.load_values(name, op1, op2)

        assert cast(MagicMock, fpu.lib.set_operand_info).call_count == 2
        cast(MagicMock, fpu.lib.set_operand_info).assert_any_call(
            fpu.state, b"op1", 0x1000, 4, 1, 0, 0
        )
        cast(MagicMock, fpu.lib.set_operand_info).assert_any_call(
            fpu.state, b"op2", 0x2000, 8, 2, 0, 0
        )

    def test_invalid_operands_are_skipped(self, fpu: FPU):
        name = next(iter(FPU_OPCODES))
        fpu.load_values(name, make_op(valid=False), make_op(valid=False))
        cast(MagicMock, fpu.lib.set_operand_info).assert_not_called()

    def test_none_operands_are_skipped(self, fpu: FPU):
        name = next(iter(FPU_OPCODES))
        fpu.load_values(name, None, None)  # type: ignore
        cast(MagicMock, fpu.lib.set_operand_info).assert_not_called()


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_calls_dispatch_with_state(self, fpu: FPU):
        fpu.execute()
        cast(MagicMock, fpu.lib).dispatch.assert_called_once_with(fpu.state)


# ---------------------------------------------------------------------------
# __del__
# ---------------------------------------------------------------------------


class TestDel:
    def test_del_frees_operand_state(self, fpu: FPU):
        state = fpu.state
        fpu.__del__()
        cast(MagicMock, fpu.lib).free_operand_state.assert_called_once_with(state)


# ---------------------------------------------------------------------------
# get_opcode
# ---------------------------------------------------------------------------


class TestGetOpcode:
    def test_known_instruction_returns_offset_table_index(self):
        name = next(iter(FPU_OPCODES))
        expected = FPU_OPCODES[name] + len(INSTRUCTIONS["alu"])
        assert FPU.get_opcode(name) == expected

    def test_lookup_is_case_insensitive(self):
        name = next(iter(FPU_OPCODES))
        assert FPU.get_opcode(name.upper()) == FPU.get_opcode(name)

    def test_unknown_instruction_returns_offset_minus_one(self):
        expected = -1 + len(INSTRUCTIONS["alu"])
        assert FPU.get_opcode("not_a_real_instruction") == expected
