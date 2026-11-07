"""
Unit tests for bridges/data_memory.py

Strategy
--------
Data_Memory.__init__ loads a real compiled shared library via ctypes.CDLL,
which we don't have at unit-test time -- so we patch ctypes.CDLL with a
MagicMock, same as in test_register_manager.py.

Data_Memory also depends on a Registers_Interface instance (for rsp during
stack ops). Rather than dragging in the full register logic, we hand it a
MagicMock(spec=Registers_Interface) so we can control read_reg/write_reg
return values and assert on how they're called, in isolation from register
internals (those have their own test file).

Run with: pytest tests/bridge/test_data_memory.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_BRIDGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bridges",
)
if _BRIDGES_DIR not in sys.path:
    sys.path.insert(0, _BRIDGES_DIR)

from interpreter._src.bridges.data_memory import Data_Memory
from interpreter._src.bridges.register_manager import Registers_Interface


@pytest.fixture
def mock_registers():
    regs = MagicMock(spec=Registers_Interface)
    return regs


@pytest.fixture
def mem(mock_registers):
    """A Data_Memory backed by a MagicMock instead of a real .so."""
    with patch("ctypes.CDLL") as mock_cdll:
        mock_lib = MagicMock()
        mock_lib.table_init.return_value = 0xCAFEBABE
        mock_lib.write_mem.return_value = 0  # 0 == success
        mock_lib.read_mem.return_value = 0
        mock_cdll.return_value = mock_lib
        instance = Data_Memory(registers=mock_registers)
        yield instance


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_loads_from_project_root_lib_dir(self, mock_registers):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            mock_lib.table_init.return_value = 1
            mock_cdll.return_value = mock_lib
            Data_Memory(registers=mock_registers)

            called_path = mock_cdll.call_args[0][0]
            assert called_path.endswith(os.path.join("lib", "libmmu.so"))
            assert (
                os.path.basename(os.path.dirname(os.path.dirname(called_path)))
                != "bridges"
            )

    def test_raises_if_table_init_fails(self, mock_registers):
        with patch("ctypes.CDLL") as mock_cdll:
            mock_lib = MagicMock()
            mock_lib.table_init.return_value = 0  # NULL pointer
            mock_cdll.return_value = mock_lib
            with pytest.raises(MemoryError):
                Data_Memory(registers=mock_registers)


# ---------------------------------------------------------------------------
# Byte-level read/write
# ---------------------------------------------------------------------------


class TestReadWriteBytes:
    def test_read_bytes_returns_data_from_buffer(self, mem):
        expected = bytes([0xDE, 0xAD, 0xBE, 0xEF])

        def fake_read_mem(table, addr, buffer, size):
            for i, b in enumerate(expected):
                buffer[i] = b
            return 0

        mem.lib.read_mem.side_effect = fake_read_mem
        result = mem.read_bytes(0x1000, 4)
        assert result == expected

    def test_read_bytes_segfault_raises(self, mem):
        mem.lib.read_mem.return_value = 1  # 1 == fault
        with pytest.raises(MemoryError):
            mem.read_bytes(0x1000, 4)

    def test_write_bytes_pads_short_data(self, mem):
        mem.write_bytes(0x1000, b"\x01\x02", 4)
        args = mem.lib.write_mem.call_args[0]
        c_data = args[2]
        assert bytes(c_data) == b"\x01\x02\x00\x00"

    def test_write_bytes_truncates_long_data(self, mem):
        mem.write_bytes(0x1000, b"\x01\x02\x03\x04\x05", 4)
        args = mem.lib.write_mem.call_args[0]
        c_data = args[2]
        assert bytes(c_data) == b"\x01\x02\x03\x04"

    def test_write_bytes_segfault_raises(self, mem):
        mem.lib.write_mem.return_value = 1
        with pytest.raises(MemoryError):
            mem.write_bytes(0x1000, b"\x01\x02\x03\x04", 4)

    def test_write_bytes_create_page_flag_passed_through(self, mem):
        mem.write_bytes(0x1000, b"\x01\x02\x03\x04", 4, create_page=False)
        args = mem.lib.write_mem.call_args[0]
        assert args[4] == 0
        mem.write_bytes(0x1000, b"\x01\x02\x03\x04", 4, create_page=True)
        args = mem.lib.write_mem.call_args[0]
        assert args[4] == 1


# ---------------------------------------------------------------------------
# Data validation helpers
# ---------------------------------------------------------------------------


class TestDataHelpers:
    def test_valid_data_length(self, mem):
        assert mem.valid_data_length(b"\x01\x02", 2) is True
        assert mem.valid_data_length(b"\x01\x02", 4) is False

    def test_get_valid_data_pads(self, mem):
        assert mem.get_valid_data(b"\x01", 4) == b"\x01\x00\x00\x00"

    def test_get_valid_data_truncates(self, mem):
        assert mem.get_valid_data(b"\x01\x02\x03\x04\x05", 4) == b"\x01\x02\x03\x04"


# ---------------------------------------------------------------------------
# Stack operations
# ---------------------------------------------------------------------------


class TestPush:
    def test_value_over_8_bytes_raises_regardless_of_stack_state(
        self, mem, mock_registers
    ):
        with pytest.raises(ValueError):
            mem.push(b"\x01" * 9)
        mock_registers.read_reg.assert_not_called()

    def test_overflow_raises(self, mem, mock_registers):
        mock_registers.read_reg.return_value = (
            Data_Memory.STACK_LIMIT + 4
        )  # rsp - 8 < STACK_LIMIT
        with pytest.raises(MemoryError):
            mem.push(b"\x01" * 8)

    def test_normal_push_updates_rsp_and_writes_memory(self, mem, mock_registers):
        rsp = 0x7FFFFFFFD000
        mock_registers.read_reg.return_value = rsp

        mem.push(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        mock_registers.write_reg.assert_called_once_with("rsp", rsp - 8)
        write_args = mem.lib.write_mem.call_args[0]
        assert write_args[1].value == rsp - 8
        assert bytes(write_args[2]) == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    def test_short_value_padded_before_push(self, mem, mock_registers):
        rsp = 0x7FFFFFFFD000
        mock_registers.read_reg.return_value = rsp

        mem.push(b"\x01\x02")

        write_args = mem.lib.write_mem.call_args[0]
        assert bytes(write_args[2]) == b"\x01\x02\x00\x00\x00\x00\x00\x00"


class TestPop:
    def test_underflow_raises(self, mem, mock_registers):
        mock_registers.read_reg.return_value = Data_Memory.STACK_START
        with pytest.raises(MemoryError):
            mem.pop()

    def test_normal_pop_returns_value_and_updates_rsp(self, mem, mock_registers):
        rsp = 0x7FFFFFFFD000
        mock_registers.read_reg.return_value = rsp
        expected = bytes([1, 2, 3, 4, 5, 6, 7, 8])

        def fake_read_mem(table, addr, buffer, size):
            for i, b in enumerate(expected):
                buffer[i] = b
            return 0

        mem.lib.read_mem.side_effect = fake_read_mem

        result = mem.pop()

        assert result == expected
        mock_registers.write_reg.assert_called_once_with("rsp", rsp + 8)

    def test_pop_clears_the_slot(self, mem, mock_registers):
        rsp = 0x7FFFFFFFD000
        mock_registers.read_reg.return_value = rsp
        mem.lib.read_mem.return_value = 0

        mem.pop()

        # write_mem should have been called once, to zero out the popped slot
        mem.lib.write_mem.assert_called_once()
        write_args = mem.lib.write_mem.call_args[0]
        assert bytes(write_args[2]) == b"\x00" * 8
