"""
Unit tests for FUs/alu.py

Strategy
--------
ALU.__init__ loads a real compiled shared library via ctypes.CDLL, which we
don't have at unit-test time -- so we patch ctypes.CDLL with a MagicMock,
same as in test_data_manager.py.

ALU also depends on a Registers_Interface and a Data_Memory instance. We
hand it plain MagicMocks for both since ALU only forwards these pointers
into set_registers_ref/set_table_ref without touching them itself.

Run with: pytest tests/FUs/test_alu.py -v
"""

import ctypes
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from interpreter._src.FUs.alu import ALU, ALU_OPCODES


def make_op(address=0, type_=0, size=4, is_high=0, is_signed=0, valid=True):
    op = SimpleNamespace(
        address=address, type=type_, size=size, is_high=is_high, is_signed=is_signed
    )
    op.is_valid = lambda: valid
    return op


@pytest.fixture
def mock_registers():
    regs = MagicMock()
    regs.regs = ctypes.c_void_p(0xDEADBEEF)
    return regs


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.table = ctypes.c_void_p(0xFEEDFACE)
    return mem


@pytest.fixture
def alu(mock_registers, mock_memory):
    """An ALU backed by a MagicMock instead of a real .so."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_lib = MagicMock()
        mock_lib.create_operand_state.return_value = ctypes.c_void_p(0xCAFEBABE)
        mock_cdll.return_value = mock_lib
        instance = ALU(
            registers=mock_registers, memory=mock_memory, libops_path="fake.so"
        )
        yield instance


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_operand_state_and_wires_registers_and_memory(
        self, mock_registers, mock_memory
    ):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            state = ctypes.c_void_p(0x1234)
            mock_lib.create_operand_state.return_value = state
            mock_cdll.return_value = mock_lib

            instance = ALU(
                registers=mock_registers, memory=mock_memory, libops_path="fake.so"
            )

            mock_lib.set_registers_ref.assert_called_once()
            assert mock_lib.set_registers_ref.call_args[0][0] == state
            mock_lib.set_table_ref.assert_called_once()
            assert mock_lib.set_table_ref.call_args[0][0] == state
            assert instance.state == state

    def test_set_operand_info_argtypes_match_header_order(self, alu):
        # operations.h: set_operand_info(Info*, char*, long long address,
        # uint8_t size, uint8_t op_type, uint8_t is_high, uint8_t is_signed)
        argtypes = alu.lib.set_operand_info.argtypes
        assert argtypes[2] is ctypes.c_longlong
        assert argtypes[3] is ctypes.c_uint8  # size
        assert argtypes[4] is ctypes.c_uint8  # op_type
        assert argtypes[5] is ctypes.c_uint8  # is_high
        assert argtypes[6] is ctypes.c_uint8  # is_signed

    def test_set_instruction_argtype_is_uint8(self, alu):
        assert alu.lib.set_instruction.argtypes[1] is ctypes.c_uint8


# ---------------------------------------------------------------------------
# load_values
# ---------------------------------------------------------------------------


class TestLoadValues:
    def test_clean_called_before_set_instruction(self, alu):
        alu.load_values("add", make_op(valid=False), make_op(valid=False))

        method_order = [c[0] for c in alu.lib.method_calls]
        assert method_order.index("clean") < method_order.index("set_instruction")

    def test_set_instruction_called_with_correct_opcode(self, alu):
        alu.load_values("add", make_op(valid=False), make_op(valid=False))
        alu.lib.set_instruction.assert_called_once_with(alu.state, ALU_OPCODES["add"])

    def test_set_operand_info_called_with_size_before_op_type(self, alu):
        op1 = make_op(address=0x1000, type_=2, size=8, is_high=0, is_signed=1)

        alu.load_values("add", op1, make_op(valid=False))

        alu.lib.set_operand_info.assert_called_once_with(
            alu.state,
            b"op1",
            0x1000,
            8,  # size
            2,  # op_type
            0,  # is_high
            1,  # is_signed
        )

    def test_both_operands_loaded_when_valid(self, alu):
        op1 = make_op(address=0x1000, type_=1, size=4)
        op2 = make_op(address=0x2000, type_=2, size=8)

        alu.load_values("add", op1, op2)

        assert alu.lib.set_operand_info.call_count == 2
        alu.lib.set_operand_info.assert_any_call(alu.state, b"op1", 0x1000, 4, 1, 0, 0)
        alu.lib.set_operand_info.assert_any_call(alu.state, b"op2", 0x2000, 8, 2, 0, 0)

    def test_invalid_operands_are_skipped(self, alu):
        alu.load_values("add", make_op(valid=False), make_op(valid=False))
        alu.lib.set_operand_info.assert_not_called()

    def test_none_operands_are_skipped(self, alu):
        alu.load_values("add", None, None)
        alu.lib.set_operand_info.assert_not_called()


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_calls_dispatch_with_state(self, alu):
        alu.execute()
        alu.lib.dispatch.assert_called_once_with(alu.state)


# ---------------------------------------------------------------------------
# __del__
# ---------------------------------------------------------------------------


class TestDel:
    def test_del_frees_operand_state(self, alu):
        state = alu.state
        alu.__del__()
        alu.lib.free_operand_state.assert_called_once_with(state)


# ---------------------------------------------------------------------------
# get_opcode
# ---------------------------------------------------------------------------


class TestGetOpcode:
    def test_known_instruction_returns_table_index(self):
        assert ALU.get_opcode("add") == ALU_OPCODES["add"]

    def test_lookup_is_case_insensitive(self):
        assert ALU.get_opcode("ADD") == ALU_OPCODES["add"]
        assert ALU.get_opcode("Add") == ALU_OPCODES["add"]

    def test_unknown_instruction_returns_minus_one(self):
        assert ALU.get_opcode("not_a_real_instruction") == -1
