"""
Integration test suite for bridges/register_manager.py and bridges/data_memory.py.

This file has two halves, and they run under different conditions:

1. Property and corner-case tests (TestRoundTripProperty, TestByteIndependence,
   TestBoundsCornerCases, TestSignExtensionCornerCases, TestFlagCornerCases,
   TestMemoryCornerCases, TestStackBoundaryCornerCases) run against a small
   fake C model -- a plain Python object that actually stores register/memory
   bytes, standing in for libreg.so/libmmu.so. These always run, with no
   dependency on a compiled library, and check real properties (round-trips,
   byte independence between sub-registers, boundary values) that a plain
   MagicMock (see test_register_manager.py / test_data_memory.py) can't --
   a MagicMock has no memory of its own, so it can only prove "Python calls
   C with the right shape," not "the values actually come back right."

2. Real integration tests (TestRegisterRoundTrip, TestFlagsIntegration,
   TestMemoryRoundTrip, TestStackIntegration, TestRegisterCrossTalk) run
   against the REAL compiled libraries in lib/. These are skipped
   automatically until lib/libreg.so and lib/libmmu.so exist (e.g. after
   `make` at the project root). Once built, these are what actually confirms
   the C implementation behaves the way the fake model assumes it does --
   the fake model encodes assumptions (like "writing al doesn't touch ah or
   the rest of rax"), it doesn't verify them.

Run with: pytest tests/bridge/test_integration.py -v
"""

import ctypes
import os
import sys
from unittest.mock import patch

import pytest

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_BRIDGES_DIR = os.path.join(_PROJECT_ROOT, "bridges")
if _BRIDGES_DIR not in sys.path:
    sys.path.insert(0, _BRIDGES_DIR)

from interpreter._src.bridges.data_memory import Data_Memory
from interpreter._src.bridges.register_manager import Registers_Interface

_LIBS_PRESENT = os.path.exists(
    os.path.join(_PROJECT_ROOT, "lib", "libreg.so")
) and os.path.exists(os.path.join(_PROJECT_ROOT, "lib", "libmmu.so"))
_needs_real_libs = pytest.mark.skipif(
    not _LIBS_PRESENT,
    reason="lib/libreg.so and lib/libmmu.so not built yet -- run `make` at the project root first",
)


# ===========================================================================
# PART 1 -- fake C model, property and corner-case tests (always run)
# ===========================================================================


class FakeRegLib:
    """
    Minimal, faithful-enough model of libreg.so:
    - 16 registers, 8 bytes each, little-endian.
    - A write of `size` bytes touches only bytes [0:size) of that register,
      or byte [1:2) when is_high is set (the AH/BH/CH/DH case) -- nothing
      else in the register is disturbed.
    - Sign flags are tracked per register.
    """

    def __init__(self):
        self._regs = [bytearray(8) for _ in range(16)]
        self._signed = [0] * 16
        self._rflags = 0

    def CPURegs_create(self):
        return 1  # opaque token, unused by this fake

    def CPURegs_free(self, _regs):
        pass

    def write_reg(self, _regs, reg_id, value, size, is_high):
        raw = value & (
            (1 << (8 * size)) - 1
        )  # low `size` bytes, two's-complement pattern
        chunk = raw.to_bytes(size, "little")
        start = 1 if (size == 1 and is_high) else 0
        self._regs[reg_id][start : start + size] = chunk

    def _read(self, reg_id, size, is_high=0):
        start = 1 if (size == 1 and is_high) else 0
        return int.from_bytes(self._regs[reg_id][start : start + size], "little")

    def read_8b_reg(self, _regs, reg_id):
        return self._read(reg_id, 8)

    def read_4b_reg(self, _regs, reg_id):
        return self._read(reg_id, 4)

    def read_2b_reg(self, _regs, reg_id):
        return self._read(reg_id, 2)

    def read_1b_reg(self, _regs, reg_id, is_high):
        return self._read(reg_id, 1, is_high)

    def set_reg_sign(self, _regs, reg_id, is_signed):
        self._signed[reg_id] = is_signed

    def is_signed(self, _regs, reg_id):
        return self._signed[reg_id]

    def read_rflags(self, _regs):
        return self._rflags

    def write_rflags(self, _regs, value):
        self._rflags = value

    def exch_rflag(self, _regs, flag_id):
        self._rflags ^= 1 << int(
            flag_id.value if hasattr(flag_id, "value") else flag_id
        )

    def read_trap_flag(self, _regs):
        return (self._rflags >> 8) & 1

    def set_trap_flag(self, _regs):
        self._rflags ^= 1 << 8

    def read_carry_flag(self, _regs):
        return self._rflags & 1

    def read_parity_flag(self, _regs):
        return (self._rflags >> 2) & 1

    def read_zero_flag(self, _regs):
        return (self._rflags >> 6) & 1

    def read_sign_flag(self, _regs):
        return (self._rflags >> 7) & 1

    def read_overflow_flag(self, _regs):
        return (self._rflags >> 11) & 1

    # ctypes bookkeeping no-ops -- setting .argtypes/.restype on bound
    # methods isn't meaningful for a plain Python fake, so just swallow it.
    def __getattr__(self, name):
        raise AttributeError(name)


class _FnWrapper:
    """Wraps a bound method so `.argtypes` / `.restype` can be set on it
    (like a real ctypes function) without affecting behavior, and unwraps
    plain ctypes scalar values (c_uint8(5) -> 5) the way a real ctypes FFI
    call would -- a raw Python function call doesn't do that unwrapping
    automatically, but the actual C boundary always would."""

    def __init__(self, fn):
        self._fn = fn
        self.argtypes = None
        self.restype = None

    @staticmethod
    def _unwrap(arg):
        if isinstance(arg, ctypes.Array):
            return arg  # buffers stay as-is, indexing works normally
        if isinstance(arg, ctypes._SimpleCData):
            return arg.value
        return arg

    def __call__(self, *args, **kwargs):
        return self._fn(*(self._unwrap(a) for a in args), **kwargs)


def _configure_fake(lib):
    for fn_name in [
        "CPURegs_create",
        "CPURegs_free",
        "write_reg",
        "read_8b_reg",
        "read_4b_reg",
        "read_2b_reg",
        "read_1b_reg",
        "set_reg_sign",
        "is_signed",
        "read_rflags",
        "read_trap_flag",
        "read_carry_flag",
        "read_zero_flag",
        "read_sign_flag",
        "read_overflow_flag",
        "read_parity_flag",
        "write_rflags",
        "exch_rflag",
        "set_trap_flag",
    ]:
        setattr(lib, fn_name, _FnWrapper(getattr(lib, fn_name)))
    return lib


@pytest.fixture
def fake_regs():
    lib = _configure_fake(FakeRegLib())
    with patch("ctypes.CDLL", return_value=lib):
        yield Registers_Interface()


class FakeMMULib:
    """Faithful-enough model of libmmu.so: a flat dict of addr -> byte."""

    def __init__(self):
        self._mem = {}

    def table_init(self):
        return 1

    def free_table(self, _table):
        pass

    def write_mem(self, _table, addr, data, size, create_page):
        for i in range(size):
            self._mem[addr + i] = data[i]
        return 0

    def read_mem(self, _table, addr, buffer, size):
        for i in range(size):
            if (addr + i) not in self._mem:
                return 1  # unmapped -> segfault
            buffer[i] = self._mem[addr + i]
        return 0

    def __getattr__(self, name):
        raise AttributeError(name)


def _configure_fake_mmu(lib):
    for fn_name in ["table_init", "free_table", "write_mem", "read_mem"]:
        setattr(lib, fn_name, _FnWrapper(getattr(lib, fn_name)))
    return lib


@pytest.fixture
def fake_mem(fake_regs):
    lib = _configure_fake_mmu(FakeMMULib())
    with patch("ctypes.CDLL", return_value=lib):
        yield Data_Memory(registers=fake_regs)


# --- Property: write then read gives back the same value ---


class TestRoundTripProperty:
    @pytest.mark.parametrize(
        "reg,bits,signed",
        [
            ("al", 8, False),
            ("al", 8, True),
            ("ax", 16, False),
            ("ax", 16, True),
            ("eax", 32, False),
            ("eax", 32, True),
            ("rax", 64, False),
            ("rax", 64, True),
        ],
    )
    def test_round_trip_across_full_range_samples(self, fake_regs, reg, bits, signed):
        if signed:
            lo, hi = -(2 ** (bits - 1)), (2 ** (bits - 1)) - 1
        else:
            lo, hi = 0, (2**bits) - 1
        for value in {lo, hi, lo + 1, hi - 1, 0 if lo <= 0 <= hi else lo}:
            fake_regs.write_reg(reg, value, signed=signed)
            assert fake_regs.read_reg(reg) == value

    def test_round_trip_all_extended_subregisters(self, fake_regs):
        for reg in ["r8", "r8d", "r8w", "r8b"]:
            fake_regs.write_reg(reg, 1)
            assert fake_regs.read_reg(reg) == 1

    def test_round_trip_irregular_subregisters(self, fake_regs):
        for reg in ["rsi", "si", "sil"]:
            fake_regs.write_reg(reg, 1)
            assert fake_regs.read_reg(reg) == 1


# --- Property: writing a sub-register doesn't disturb unrelated bytes ---


class TestByteIndependence:
    def test_writing_al_preserves_rest_of_rax(self, fake_regs):
        fake_regs.write_reg("rax", 0x1122334455667788)
        fake_regs.write_reg("al", 0xFF)
        assert fake_regs.read_reg("rax") == 0x11223344556677FF

    def test_writing_ah_preserves_rest_of_rax(self, fake_regs):
        fake_regs.write_reg("rax", 0x1122334455667788)
        fake_regs.write_reg("ah", 0xFF)
        assert fake_regs.read_reg("rax") == 0x112233445566FF88

    def test_al_and_ah_are_independent(self, fake_regs):
        fake_regs.write_reg("rax", 0)
        fake_regs.write_reg("al", 0x11)
        fake_regs.write_reg("ah", 0x22)
        assert fake_regs.read_reg("al") == 0x11
        assert fake_regs.read_reg("ah") == 0x22
        assert fake_regs.read_reg("ax") == 0x2211

    def test_writing_one_register_never_touches_another(self, fake_regs):
        fake_regs.write_reg("rax", 0x1111111111111111)
        fake_regs.write_reg("rbx", 0x2222222222222222)
        fake_regs.write_reg("al", 0xFF)
        assert fake_regs.read_reg("rbx") == 0x2222222222222222

    def test_writing_eax_preserves_upper_32_bits_of_rax(self, fake_regs):
        """CONFIRMED against registers.c: write_reg's size==4 branch is a
        plain union member write (target->e32 = value), nothing clears the
        rest of the 8-byte union. So this is no longer just an assumption
        baked into the fake model -- it matches the real C source. Note
        this differs from real x86-64 hardware, which always zero-extends
        on a 32-bit write."""
        fake_regs.write_reg("rax", 0x1122334455667788)
        fake_regs.write_reg("eax", 0xAABBCCDD)
        assert fake_regs.read_reg("rax") == 0x11223344AABBCCDD


# --- Corner cases: bounds checking ---


class TestBoundsCornerCases:
    @pytest.mark.parametrize(
        "reg,bits", [("al", 8), ("ax", 16), ("eax", 32), ("rax", 64)]
    )
    def test_unsigned_min_and_max_accepted(self, fake_regs, reg, bits):
        fake_regs.write_reg(reg, 0, signed=False)
        fake_regs.write_reg(reg, (2**bits) - 1, signed=False)

    @pytest.mark.parametrize(
        "reg,bits", [("al", 8), ("ax", 16), ("eax", 32), ("rax", 64)]
    )
    def test_unsigned_just_out_of_range_rejected(self, fake_regs, reg, bits):
        with pytest.raises(ValueError):
            fake_regs.write_reg(reg, -1, signed=False)
        with pytest.raises(ValueError):
            fake_regs.write_reg(reg, 2**bits, signed=False)

    @pytest.mark.parametrize(
        "reg,bits", [("al", 8), ("ax", 16), ("eax", 32), ("rax", 64)]
    )
    def test_signed_min_and_max_accepted(self, fake_regs, reg, bits):
        fake_regs.write_reg(reg, -(2 ** (bits - 1)), signed=True)
        fake_regs.write_reg(reg, (2 ** (bits - 1)) - 1, signed=True)

    @pytest.mark.parametrize(
        "reg,bits", [("al", 8), ("ax", 16), ("eax", 32), ("rax", 64)]
    )
    def test_signed_just_out_of_range_rejected(self, fake_regs, reg, bits):
        with pytest.raises(ValueError):
            fake_regs.write_reg(reg, -(2 ** (bits - 1)) - 1, signed=True)
        with pytest.raises(ValueError):
            fake_regs.write_reg(reg, 2 ** (bits - 1), signed=True)

    @pytest.mark.parametrize(
        "bad_name", ["", "notareg", "rax1", "r17", "AX ", " al", "rax\n"]
    )
    def test_garbage_register_names_rejected(self, fake_regs, bad_name):
        with pytest.raises(ValueError):
            fake_regs.write_reg(bad_name, 0)
        with pytest.raises(ValueError):
            fake_regs.read_reg(bad_name)

    def test_register_names_are_case_insensitive(self, fake_regs):
        fake_regs.write_reg("RAX", 5)
        assert fake_regs.read_reg("rax") == 5
        assert fake_regs.read_reg("RaX") == 5


# --- Corner cases: sign extension at the boundary ---


class TestSignExtensionCornerCases:
    def test_msb_set_is_negative_when_signed(self, fake_regs):
        fake_regs.write_reg("al", 0x80, signed=False)  # 128 unsigned == -128 signed
        fake_regs.write_reg("al", -128, signed=True)
        assert fake_regs.read_reg("al") == -128

    def test_msb_clear_is_positive_boundary(self, fake_regs):
        fake_regs.write_reg("al", 127, signed=True)
        assert fake_regs.read_reg("al") == 127


# --- Corner cases: flags ---


class TestFlagCornerCases:
    @pytest.mark.parametrize("flag_id", [0, 31])
    def test_exch_flag_boundary_ids_accepted(self, fake_regs, flag_id):
        fake_regs.exch_flag(flag_id)  # should not raise

    @pytest.mark.parametrize("flag_id", [-1, 32, 1000])
    def test_exch_flag_out_of_range_rejected(self, fake_regs, flag_id):
        with pytest.raises(ValueError):
            fake_regs.exch_flag(flag_id)

    def test_exch_flag_toggles_and_is_reversible(self, fake_regs):
        fake_regs.write_flags(0)
        fake_regs.exch_flag(3)
        after_first = fake_regs.read_flags()
        fake_regs.exch_flag(3)
        after_second = fake_regs.read_flags()
        assert after_first != after_second
        assert after_second == (0).to_bytes(4, "little")


# --- Corner cases: memory ---


class TestMemoryCornerCases:
    def test_write_then_read_exact_bytes(self, fake_mem):
        fake_mem.write_bytes(0x1000, b"\xaa\xbb\xcc\xdd", 4)
        assert fake_mem.read_bytes(0x1000, 4) == b"\xaa\xbb\xcc\xdd"

    def test_reading_never_written_address_faults(self, fake_mem):
        with pytest.raises(MemoryError):
            fake_mem.read_bytes(0x123456, 1)

    def test_overlapping_writes_take_the_latest_value(self, fake_mem):
        fake_mem.write_bytes(0x2000, b"\x01\x02\x03\x04", 4)
        fake_mem.write_bytes(0x2001, b"\xff\xff", 2)
        assert fake_mem.read_bytes(0x2000, 4) == b"\x01\xff\xff\x04"

    def test_zero_data_gets_padded_to_full_size(self, fake_mem):
        fake_mem.write_bytes(0x3000, b"", 4)
        assert fake_mem.read_bytes(0x3000, 4) == b"\x00\x00\x00\x00"

    def test_oversized_data_gets_truncated_not_rejected(self, fake_mem):
        fake_mem.write_bytes(0x4000, b"\x01\x02\x03\x04\x05\x06", 2)
        assert fake_mem.read_bytes(0x4000, 2) == b"\x01\x02"


# --- Corner cases: the stack, at its exact boundaries ---


class TestStackBoundaryCornerCases:
    def test_push_at_the_very_top_of_the_stack(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_START)
        fake_mem.push(b"\x01" * 8)
        assert fake_regs.read_reg("rsp") == Data_Memory.STACK_START - 8

    def test_pop_right_back_to_stack_start_then_underflows(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_START)
        fake_mem.push(
            b"\x01" * 8
        )  # rsp now at STACK_START - 8, with something actually mapped there
        fake_mem.pop()
        assert fake_regs.read_reg("rsp") == Data_Memory.STACK_START
        with pytest.raises(MemoryError):
            fake_mem.pop()  # rsp == STACK_START -> underflow, not a segfault

    def test_push_exactly_8_bytes_is_allowed(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_START)
        fake_mem.push(b"\x01" * 8)  # should not raise

    def test_push_9_bytes_rejected(self, fake_mem, fake_regs):
        with pytest.raises(ValueError):
            fake_mem.push(b"\x01" * 9)

    def test_push_0_bytes_is_padded_to_all_zero(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_START)
        fake_mem.push(b"")
        assert fake_mem.pop() == b"\x00" * 8

    def test_deep_push_pop_sequence_stays_lifo(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_START)
        values = [bytes([i]) * 8 for i in range(1, 6)]
        for v in values:
            fake_mem.push(v)
        for v in reversed(values):
            assert fake_mem.pop() == v
        assert fake_regs.read_reg("rsp") == Data_Memory.STACK_START

    def test_push_right_at_stack_limit_boundary(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_LIMIT + 8)
        fake_mem.push(
            b"\x01" * 8
        )  # lands exactly on STACK_LIMIT -- should still be allowed
        assert fake_regs.read_reg("rsp") == Data_Memory.STACK_LIMIT

    def test_push_one_byte_past_stack_limit_overflows(self, fake_mem, fake_regs):
        fake_regs.write_reg("rsp", Data_Memory.STACK_LIMIT + 7)
        with pytest.raises(MemoryError):
            fake_mem.push(b"\x01" * 8)


# ===========================================================================
# PART 2 -- real compiled library, integration tests
# (skipped until lib/libreg.so and lib/libmmu.so are built)
# ===========================================================================


@pytest.fixture
def regs():
    return Registers_Interface()


@pytest.fixture
def mem(regs):
    return Data_Memory(registers=regs)


@_needs_real_libs
class TestRegisterRoundTrip:
    def test_write_then_read_64bit(self, regs):
        regs.write_reg("rax", 0x1122334455667788)
        assert regs.read_reg("rax") == 0x1122334455667788

    def test_write_then_read_32bit_subregister(self, regs):
        regs.write_reg("eax", 0xDEADBEEF)
        assert regs.read_reg("eax") == 0xDEADBEEF

    def test_write_low_byte_preserves_rest_of_register(self, regs):
        regs.write_reg("rax", 0x1122334455667788)
        regs.write_reg("al", 0xFF)
        assert regs.read_reg("rax") == 0x11223344556677FF

    def test_write_high_byte_preserves_rest_of_register(self, regs):
        regs.write_reg("rax", 0x0000000000000000)
        regs.write_reg("ah", 0xFF)
        assert regs.read_reg("ax") == 0xFF00

    def test_signed_negative_round_trip(self, regs):
        regs.write_reg("al", -1, signed=True)
        assert regs.read_reg("al") == -1

    def test_extended_registers_r8_family(self, regs):
        regs.write_reg("r8", 0x42)
        assert regs.read_reg("r8") == 0x42
        regs.write_reg("r8d", 0x1234)
        assert regs.read_reg("r8d") == 0x1234

    def test_si_di_bp_sp_subregisters(self, regs):
        regs.write_reg("rsi", 0x1111111111111111)
        regs.write_reg("si", 0x2222)
        assert regs.read_reg("rsi") == 0x1111111111112222


@_needs_real_libs
class TestFlagsIntegration:
    def test_write_then_read_flags(self, regs):
        regs.write_flags(0x00000246)  # arbitrary flags pattern
        assert regs.read_flags() == (0x00000246).to_bytes(4, "little")

    def test_exch_flag_toggles_bit(self, regs):
        regs.write_flags(0)
        regs.exch_flag(6)  # zero flag bit, per standard RFLAGS layout
        assert regs.read_zero() is True
        regs.exch_flag(6)
        assert regs.read_zero() is False


@_needs_real_libs
class TestMemoryRoundTrip:
    def test_write_then_read_bytes(self, mem):
        mem.write_bytes(0x500000, b"\x01\x02\x03\x04", 4)
        assert mem.read_bytes(0x500000, 4) == b"\x01\x02\x03\x04"

    def test_read_unmapped_address_raises(self, mem):
        with pytest.raises(MemoryError):
            mem.read_bytes(0x999999999, 4)

    # --- Non-page-aligned addresses ---
    #
    # RODATA_BASE (0x500000) and STACK_START (0x7fffffffe000) are both
    # exactly page-aligned (offset 0 within their 4KB page), which hides a
    # bug in read_block: it adds the in-page offset a second time on top of
    # decompose_address's already-offset-adjusted pointer. That only shows
    # up for a non-page-aligned address with size > 1 -- these tests target
    # that directly.
    @pytest.mark.parametrize("offset", [1, 17, 4095])
    def test_multibyte_read_at_non_page_aligned_address(self, mem, offset):
        addr = 0x500000 + offset
        data = bytes(range(1, 5))
        mem.write_bytes(addr, data, 4)
        assert mem.read_bytes(addr, 4) == data

    def test_multibyte_read_write_at_every_byte_offset_in_a_page(self, mem):
        """Sweep every possible in-page offset for a 2-byte value -- if
        read_block's double-offset bug is present, this will fail for every
        offset except 0."""
        base = 0x600000
        for offset in range(0, 4096, 512):
            addr = base + offset
            mem.write_bytes(addr, b"\xab\xcd", 2)
            assert mem.read_bytes(addr, 2) == b"\xab\xcd", f"failed at offset {offset}"

    def test_write_crossing_a_page_boundary(self, mem):
        """4 bytes straddling two pages -- exercises write_block's/read_block's
        page-crossing chunking logic specifically."""
        addr = 0x500000 + 4094  # 2 bytes left in this page, 2 bytes spill into the next
        data = b"\x11\x22\x33\x44"
        mem.write_bytes(addr, data, 4)
        assert mem.read_bytes(addr, 4) == data

    def test_multibyte_write_to_unmapped_address_raises(self, mem):
        """write_mem discards write_block's return value for size > 1, so a
        failed write (create_page=False, address never mapped) can silently
        report success instead of raising. This should raise -- if it
        doesn't, that's the write_mem bug from the C review."""
        with pytest.raises(MemoryError):
            mem.write_bytes(0x777777000, b"\x01\x02\x03\x04", 4, create_page=False)


@_needs_real_libs
class TestStackIntegration:
    def test_push_then_pop_round_trip(self, regs, mem):
        regs.write_reg("rsp", Data_Memory.STACK_START)
        mem.push(b"\x01\x02\x03\x04\x05\x06\x07\x08")
        assert mem.pop() == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    def test_push_pop_is_lifo(self, regs, mem):
        regs.write_reg("rsp", Data_Memory.STACK_START)
        mem.push(b"\x01" * 8)
        mem.push(b"\x02" * 8)
        assert mem.pop() == b"\x02" * 8
        assert mem.pop() == b"\x01" * 8

    def test_pop_updates_rsp(self, regs, mem):
        regs.write_reg("rsp", Data_Memory.STACK_START)
        mem.push(b"\x00" * 8)
        rsp_after_push = regs.read_reg("rsp")
        mem.pop()
        assert regs.read_reg("rsp") == rsp_after_push + 8


@_needs_real_libs
class TestRegisterCrossTalk:
    """Cross-register independence -- the property that would actually catch
    a wrong REGISTERS_MAP ordering. Round-tripping a single register against
    itself can look fine even with a shifted mapping, since a register would
    still read back whatever it was just written -- just under the wrong
    name. This only shows up by checking registers *don't* affect each
    other."""

    def test_writing_one_register_does_not_affect_its_neighbors(self, regs):
        names = [
            "rax",
            "rbx",
            "rcx",
            "rdx",
            "rsi",
            "rdi",
            "rbp",
            "rsp",
            "r8",
            "r9",
            "r10",
            "r11",
            "r12",
            "r13",
            "r14",
            "r15",
        ]
        for i, name in enumerate(names):
            regs.write_reg(name, i + 1)
        for i, name in enumerate(names):
            assert regs.read_reg(name) == i + 1, f"{name} was clobbered"
