"""
Tests for the Syscall class (control_unit-level syscall dispatcher).

All tests bypass Syscall.__init__ via object.__new__ to avoid loading the
real libscl.so, and use unittest.mock.Mock for registers/memory/lib so no
real ctypes calls, real files, or real host I/O happen during the test run.
"""

from unittest.mock import Mock

import pytest

from interpreter._src.bridges.syscall import Syscall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registers():
    """
    A Mock standing in for Registers_Interface. Backed by a plain dict so
    read_reg/write_reg behave consistently across a test without needing to
    hand-configure return values for every register read.
    """
    regs = Mock()
    state = {}

    def read_reg(name):
        return state.get(name, 0)

    def write_reg(name, value, signed=False):
        state[name] = value

    regs.read_reg.side_effect = read_reg
    regs.write_reg.side_effect = write_reg
    regs._state = state  # exposed for assertions
    return regs


@pytest.fixture
def mock_memory():
    """
    A Mock standing in for Data_Memory. read_bytes/write_bytes are backed by
    a dict-of-bytes so multi-call sequences (e.g. write a path string, then
    read it back) behave consistently.
    """
    mem = Mock()
    mem.RODATA_BASE = 0x500000
    store = {}

    def read_bytes(addr, size):
        return bytes(store.get(addr + i, 0) for i in range(size))

    def write_bytes(addr, data, size, create_page=True):
        for i in range(size):
            store[addr + i] = data[i]

    mem.read_bytes.side_effect = read_bytes
    mem.write_bytes.side_effect = write_bytes
    mem._store = store  # exposed for assertions
    return mem


@pytest.fixture
def syscall(mock_registers, mock_memory):
    """
    Builds a Syscall instance without running __init__, so no real
    ctypes.CDLL(libscl.so) load happens. `lib` is a bare Mock; individual
    tests configure whichever lib.sys_* methods they need.
    """
    scl = object.__new__(Syscall)
    scl.registers = mock_registers
    scl.memory = mock_memory
    scl.lib = Mock()
    return scl


def set_call(regs, rax, rdi=0, rsi=0, rdx=0):
    """Helper to load rax/rdi/rsi/rdx like control_unit would before dispatch."""
    regs.write_reg("rax", rax)
    regs.write_reg("rdi", rdi)
    regs.write_reg("rsi", rsi)
    regs.write_reg("rdx", rdx)


# ---------------------------------------------------------------------------
# syscall() dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatches_write_and_writes_result_to_rax(self, syscall, mock_registers):
        syscall.lib.sys_write.return_value = 5
        set_call(mock_registers, rax=Syscall.SYS_WRITE, rdi=1, rsi=0x1000, rdx=5)

        syscall.syscall()

        assert mock_registers.read_reg("rax") == 5

    def test_unknown_syscall_number_is_a_noop(self, syscall, mock_registers):
        set_call(mock_registers, rax=9999)

        syscall.syscall()  # must not raise

        assert mock_registers.read_reg("rax") == 9999  # untouched, no handler ran
        syscall.lib.sys_write.assert_not_called()
        syscall.lib.sys_read.assert_not_called()

    def test_exit_does_not_write_to_rax(self, syscall, mock_registers):
        set_call(mock_registers, rax=Syscall.SYS_EXIT)

        result = syscall.syscall()

        assert result == 1
        assert mock_registers.read_reg("rax") == Syscall.SYS_EXIT  # untouched

    def test_reads_registers_before_dispatch(self, syscall, mock_registers):
        syscall.lib.sys_write.return_value = 0
        set_call(mock_registers, rax=Syscall.SYS_WRITE, rdi=1, rsi=0x2000, rdx=0)

        syscall.syscall()

        mock_registers.read_reg.assert_any_call("rax")
        mock_registers.read_reg.assert_any_call("rdi")
        mock_registers.read_reg.assert_any_call("rsi")
        mock_registers.read_reg.assert_any_call("rdx")


# ---------------------------------------------------------------------------
# exit
# ---------------------------------------------------------------------------


class TestExit:
    def test_exit_returns_one(self, syscall):
        result = syscall.exit()
        assert result == 1


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestRead:
    def test_read_writes_bytes_into_simulated_memory(self, syscall, mock_memory):
        data = b"hello world"
        syscall.lib.sys_read.side_effect = lambda fd, buf, size: (
            [buf.__setitem__(i, b) for i, b in enumerate(data)],
            len(data),
        )[-1]

        result = syscall.read(fd=0, addr=0x1000, size=len(data))

        assert result == len(data)
        assert mock_memory.read_bytes(0x1000, len(data)) == data

    def test_read_returns_negative_one_on_error(self, syscall):
        syscall.lib.sys_read.return_value = -1

        result = syscall.read(fd=99, addr=0x1000, size=10)

        assert result == -1

    def test_read_zero_bytes_does_not_touch_memory(self, syscall, mock_memory):
        syscall.lib.sys_read.return_value = 0

        result = syscall.read(fd=0, addr=0x1000, size=10)

        assert result == 0
        mock_memory.write_bytes.assert_not_called()

    def test_read_short_count_pads_remaining_bytes_with_zero(
        self, syscall, mock_memory
    ):
        # Simulate a short read: asked for 10 bytes, only got 4
        partial = b"abcd"

        def fake_read(fd, buf, size):
            for i, b in enumerate(partial):
                buf[i] = b
            return len(partial)

        syscall.lib.sys_read.side_effect = fake_read

        result = syscall.read(fd=0, addr=0x1000, size=10)

        assert result == 4
        written = mock_memory.read_bytes(0x1000, 10)
        assert written == b"abcd" + b"\x00" * 6


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


class TestWrite:
    def test_write_reads_bytes_from_simulated_memory_and_passes_to_lib(
        self, syscall, mock_memory
    ):
        mock_memory.write_bytes(0x2000, b"payload!", 8)
        syscall.lib.sys_write.return_value = 8

        result = syscall.write(fd=1, addr=0x2000, size=8)

        assert result == 8
        syscall.lib.sys_write.assert_called_once()
        args = syscall.lib.sys_write.call_args[0]
        assert args[0] == 1  # fd
        assert bytes(args[1][:8]) == b"payload!"
        assert args[2] == 8

    def test_write_returns_negative_one_on_error(self, syscall, mock_memory):
        mock_memory.write_bytes(0x2000, b"x", 1)
        syscall.lib.sys_write.return_value = -1

        result = syscall.write(fd=99, addr=0x2000, size=1)

        assert result == -1


# ---------------------------------------------------------------------------
# open
# ---------------------------------------------------------------------------


class TestOpen:
    def test_open_reads_nul_terminated_path_from_memory(self, syscall, mock_memory):
        path = b"/tmp/test.txt"
        for i, b in enumerate(path + b"\x00"):
            mock_memory.write_bytes(0x3000 + i, bytes([b]), 1)
        syscall.lib.sys_open.return_value = 3

        result = syscall.open(path_addr=0x3000, flags=0, mode=0)

        assert result == 3
        called_path = syscall.lib.sys_open.call_args[0][0]
        assert called_path == path

    def test_open_stops_at_nul_and_does_not_overrun(self, syscall, mock_memory):
        # Deliberately put extra bytes after the NUL to prove they're ignored
        path = b"/a/b\x00garbage_after_nul"
        for i, b in enumerate(path):
            mock_memory.write_bytes(0x3000 + i, bytes([b]), 1)
        syscall.lib.sys_open.return_value = 3

        syscall.open(path_addr=0x3000, flags=0, mode=0)

        called_path = syscall.lib.sys_open.call_args[0][0]
        assert called_path == b"/a/b"

    def test_open_returns_negative_one_on_error(self, syscall, mock_memory):
        mock_memory.write_bytes(0x3000, b"\x00", 1)  # empty path
        syscall.lib.sys_open.return_value = -1

        result = syscall.open(path_addr=0x3000, flags=0, mode=0)

        assert result == -1

    def test_open_passes_flags_and_mode_through(self, syscall, mock_memory):
        mock_memory.write_bytes(0x3000, b"\x00", 1)
        syscall.lib.sys_open.return_value = 3

        syscall.open(path_addr=0x3000, flags=577, mode=0o644)

        args = syscall.lib.sys_open.call_args[0]
        assert args[1] == 577
        assert args[2] == 0o644


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_delegates_to_lib_and_returns_result(self, syscall):
        syscall.lib.sys_close.return_value = 0

        result = syscall.close(fd=3)

        assert result == 0
        syscall.lib.sys_close.assert_called_once_with(3)

    def test_close_propagates_error_from_lib(self, syscall):
        # e.g. closing 0/1/2 is rejected at the C layer
        syscall.lib.sys_close.return_value = -1

        result = syscall.close(fd=0)

        assert result == -1


# ---------------------------------------------------------------------------
# getrandom
# ---------------------------------------------------------------------------


class TestGetrandom:
    def test_getrandom_writes_random_bytes_into_simulated_memory(
        self, syscall, mock_memory
    ):
        random_bytes = b"\xde\xad\xbe\xef"

        def fake_getrandom(buf, size):
            for i, b in enumerate(random_bytes):
                buf[i] = b
            return len(random_bytes)

        syscall.lib.sys_getrandom.side_effect = fake_getrandom

        result = syscall.getrandom(addr=0x4000, size=4)

        assert result == 4
        assert mock_memory.read_bytes(0x4000, 4) == random_bytes

    def test_getrandom_returns_negative_one_on_error(self, syscall):
        syscall.lib.sys_getrandom.return_value = -1

        result = syscall.getrandom(addr=0x4000, size=16)

        assert result == -1

    def test_getrandom_short_result_pads_remaining_bytes_with_zero(
        self, syscall, mock_memory
    ):
        partial = b"\x01\x02"

        def fake_getrandom(buf, size):
            for i, b in enumerate(partial):
                buf[i] = b
            return len(partial)

        syscall.lib.sys_getrandom.side_effect = fake_getrandom

        result = syscall.getrandom(addr=0x4000, size=8)

        assert result == 2
        written = mock_memory.read_bytes(0x4000, 8)
        assert written == b"\x01\x02" + b"\x00" * 6

    def test_getrandom_passes_exact_requested_size_to_lib(self, syscall):
        # Guards against the size argument being silently dropped, doubled,
        # or off-by-one'd on the way to the C layer.
        syscall.lib.sys_getrandom.return_value = 0

        syscall.getrandom(addr=0x4000, size=13)

        args = syscall.lib.sys_getrandom.call_args[0]
        assert args[1] == 13

    def test_getrandom_zero_result_does_not_touch_memory(self, syscall, mock_memory):
        syscall.lib.sys_getrandom.return_value = 0

        result = syscall.getrandom(addr=0x4000, size=8)

        assert result == 0
        mock_memory.write_bytes.assert_not_called()


# ---------------------------------------------------------------------------
# _read_c_string
# ---------------------------------------------------------------------------


class TestReadCString:
    def test_reads_up_to_nul_terminator(self, syscall, mock_memory):
        path = b"/usr/bin/ls"
        for i, b in enumerate(path + b"\x00"):
            mock_memory.write_bytes(0x5000 + i, bytes([b]), 1)

        result = syscall._read_c_string(0x5000)

        assert result == path

    def test_empty_string_at_immediate_nul(self, syscall, mock_memory):
        mock_memory.write_bytes(0x5000, b"\x00", 1)

        result = syscall._read_c_string(0x5000)

        assert result == b""

    def test_respects_max_len_safety_cap(self, syscall, mock_memory):
        # No NUL anywhere in range; should stop at max_len instead of looping forever
        for i in range(20):
            mock_memory.write_bytes(0x5000 + i, b"A", 1)

        result = syscall._read_c_string(0x5000, max_len=10)

        assert result == b"A" * 10
