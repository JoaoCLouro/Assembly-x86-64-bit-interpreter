"""
Unit tests for bridges/register_manager.py

Strategy
--------
Registers_Interface.__init__ loads a real compiled shared library via
ctypes.CDLL, which we don't have at unit-test time. So for these tests we
patch ctypes.CDLL to return a MagicMock instead of a real library handle.

That lets us test everything that's actually *Python logic*:
  - register name -> (parent, size) resolution (get_register_parent)
  - is_high detection
  - bounds checking in write_reg (signed vs unsigned, off-by-one)
  - error handling for unknown registers
  - sign extension in read_reg
  - flag helpers (bool conversion, byte packing, bounds on exch_flag)

It does NOT verify that the real C library behaves correctly -- that needs
an integration test against the compiled .so (see test_register_manager_integration.py).

Run with: pytest tests/bridge/test_register_manager.py -v
"""

import ctypes
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Make `bridges/` importable the same way data_memory.py expects
# (it does `from register_manager import Registers_Interface`, a flat import).
_BRIDGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bridges",
)
if _BRIDGES_DIR not in sys.path:
    sys.path.insert(0, _BRIDGES_DIR)

from interpreter._paths import LIBREG_PATH
from interpreter._src.bridges.register_manager import Registers_Interface


@pytest.fixture
def regs():
    """A Registers_Interface backed by a MagicMock instead of a real .so."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_lib = MagicMock()
        # CPURegs_create must return something truthy and stable
        mock_lib.CPURegs_create.return_value = 0xDEADBEEF
        mock_cdll.return_value = mock_lib
        instance = Registers_Interface()
        # stash the mock on the instance for convenience in assertions
        yield instance


# ---------------------------------------------------------------------------
# Library loading
# ---------------------------------------------------------------------------


class TestLibraryLoading:
    def test_loads_from_project_root_lib_dir(self):
        """lib/ is one directory above bridges/, not inside it."""
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            mock_lib.CPURegs_create.return_value = 1
            mock_cdll.return_value = mock_lib
            Registers_Interface()

            called_path = mock_cdll.call_args[0][0]
            assert called_path == LIBREG_PATH

    def test_regs_pointer_uses_configured_restype(self):
        """CPURegs_create.restype must be set to c_void_p before it's called,
        otherwise ctypes truncates the pointer to a default int."""
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            mock_lib.CPURegs_create.return_value = (
                0x7F0000000000  # doesn't fit in 32-bit int
            )
            mock_cdll.return_value = mock_lib
            instance = Registers_Interface()

            assert mock_lib.CPURegs_create.restype == ctypes.c_void_p
            assert instance.regs == 0x7F0000000000


# ---------------------------------------------------------------------------
# get_register_parent / is_high
# ---------------------------------------------------------------------------


class TestRegisterResolution:
    @pytest.mark.parametrize(
        "expression,expected_parent,expected_size",
        [
            # 64-bit
            ("rax", "rax", 8),
            ("r8", "r8", 8),
            # 32-bit
            ("eax", "rax", 4),
            ("r8d", "r8", 4),
            # 16-bit, regular suffix pattern
            ("ax", "rax", 2),
            ("r8w", "r8", 2),
            # 16-bit, irregular names
            ("si", "rsi", 2),
            ("di", "rdi", 2),
            ("bp", "rbp", 2),
            ("sp", "rsp", 2),
            # 8-bit, regular suffix pattern
            ("al", "rax", 1),
            ("ah", "rax", 1),
            ("r8b", "r8", 1),
            # 8-bit, irregular names
            ("sil", "rsi", 1),
            ("dil", "rdi", 1),
            ("bpl", "rbp", 1),
            ("spl", "rsp", 1),
        ],
    )
    def test_resolves_correct_parent_and_size(
        self, regs, expression, expected_parent, expected_size
    ):
        parent, size = regs.get_register_parent(expression)
        assert parent == expected_parent
        assert size == expected_size

    @pytest.mark.parametrize(
        "expression,expected",
        [
            ("ah", 1),
            ("bh", 1),
            ("ch", 1),
            ("dh", 1),
            ("al", 0),
            ("bl", 0),
            ("r8b", 0),
            ("sil", 0),
        ],
    )
    def test_is_high(self, regs, expression, expected):
        assert regs.is_high(expression) == expected


# ---------------------------------------------------------------------------
# write_reg
# ---------------------------------------------------------------------------


class TestWriteReg:
    def test_calls_c_write_reg_with_regs_pointer(self, regs):
        regs.write_reg("eax", 42)
        regs.lib.write_reg.assert_called_once_with(
            regs.regs,  # this was missing before the fix
            0,  # rax's index in REGISTERS_MAP
            42,
            4,  # dword
            0,  # not high
        )

    def test_calls_c_set_reg_sign_with_regs_pointer(self, regs):
        regs.write_reg("al", 5, signed=True)
        regs.lib.set_reg_sign.assert_called_once_with(regs.regs, 0, 1)

    def test_unknown_register_raises(self, regs):
        with pytest.raises(ValueError):
            regs.write_reg("notareg", 1)

    @pytest.mark.parametrize("value", [0, 255])
    def test_unsigned_byte_in_range_ok(self, regs, value):
        regs.write_reg("al", value, signed=False)  # should not raise

    @pytest.mark.parametrize("value", [-1, 256])
    def test_unsigned_byte_out_of_range_raises(self, regs, value):
        with pytest.raises(ValueError):
            regs.write_reg("al", value, signed=False)

    @pytest.mark.parametrize("value", [-128, 127])
    def test_signed_byte_in_range_ok(self, regs, value):
        regs.write_reg("al", value, signed=True)  # should not raise

    @pytest.mark.parametrize("value", [-129, 128])
    def test_signed_byte_out_of_range_raises(self, regs, value):
        """128 previously slipped through due to an off-by-one bound."""
        with pytest.raises(ValueError):
            regs.write_reg("al", value, signed=True)


# ---------------------------------------------------------------------------
# read_reg
# ---------------------------------------------------------------------------


class TestReadReg:
    def test_calls_c_read_fn_with_regs_pointer(self, regs):
        regs.lib.read_4b_reg.return_value = 7
        regs.lib.is_signed.return_value = 0
        value = regs.read_reg("eax")
        regs.lib.read_4b_reg.assert_called_once_with(regs.regs, 0)
        assert value == 7

    def test_unsigned_value_passthrough(self, regs):
        regs.lib.read_1b_reg.return_value = 0xFF
        regs.lib.is_signed.return_value = 0
        assert regs.read_reg("al") == 0xFF

    def test_signed_value_two_complement_conversion(self, regs):
        regs.lib.read_1b_reg.return_value = 0xFF  # -1 as a signed byte
        regs.lib.is_signed.return_value = 1
        assert regs.read_reg("al") == -1

    def test_unknown_register_raises(self, regs):
        with pytest.raises(ValueError):
            regs.read_reg("notareg")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


class TestFlags:
    def test_read_flags_returns_actual_byte_encoding(self, regs):
        regs.lib.read_rflags.return_value = 0x12345678
        assert regs.read_flags() == (0x12345678).to_bytes(4, "little")

    @pytest.mark.parametrize(
        "fn_name,method_name",
        [
            ("read_carry_flag", "read_carry"),
            ("read_zero_flag", "read_zero"),
            ("read_sign_flag", "read_sign"),
            ("read_overflow_flag", "read_overflow"),
            ("read_parity_flag", "read_parity"),
            ("read_trap_flag", "read_trap_flag"),
        ],
    )
    def test_bool_flags_true(self, regs, fn_name, method_name):
        getattr(regs.lib, fn_name).return_value = 1
        assert getattr(regs, method_name)() is True

    @pytest.mark.parametrize(
        "fn_name,method_name",
        [
            ("read_carry_flag", "read_carry"),
            ("read_zero_flag", "read_zero"),
            ("read_sign_flag", "read_sign"),
            ("read_overflow_flag", "read_overflow"),
            ("read_parity_flag", "read_parity"),
            ("read_trap_flag", "read_trap_flag"),
        ],
    )
    def test_bool_flags_false(self, regs, fn_name, method_name):
        getattr(regs.lib, fn_name).return_value = 0
        assert getattr(regs, method_name)() is False

    def test_exch_flag_calls_correct_symbol(self, regs):
        """exch_flag must call exch_rflag (singular) -- the symbol that
        actually has argtypes configured -- not exch_rflags."""
        regs.exch_flag(5)
        regs.lib.exch_rflag.assert_called_once()
        args = regs.lib.exch_rflag.call_args[0]
        assert args[0] == regs.regs
        assert args[1].value == 5

    @pytest.mark.parametrize("flag_id", [-1, 32])
    def test_exch_flag_bounds(self, regs, flag_id):
        with pytest.raises(ValueError):
            regs.exch_flag(flag_id)

    @pytest.mark.parametrize("flag_id", [0, 31])
    def test_exch_flag_bounds_edges_ok(self, regs, flag_id):
        regs.exch_flag(flag_id)  # should not raise
