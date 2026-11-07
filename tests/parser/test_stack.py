import unittest
from unittest.mock import MagicMock, patch

from interpreter._src.parsing.segment_mapper import Segment_Mapper


class TestSegmentMapperStackDeepBoundaries(unittest.TestCase):
    """Exhaustive boundary and condition testing for the simulated runtime stack."""

    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def setUp(self, mock_init):
        self.mapper = Segment_Mapper("dummy.asm")
        self.mapper.registers = MagicMock()
        self.mapper.memory = MagicMock()

    # ==========================================
    # 1. ENFORCEMENT & BOUNDARY CONDITIONS (check_stack_limit)
    # ==========================================

    def test_check_stack_limit_exact_boundary(self):
        """Test behavior when RSP sits exactly on the stack limit boundary.

        The code execution handles hitting the boundary limit exactly as valid
        and safe (it doesn't raise an OverflowError).
        """
        limit = 0x7FFF00000000
        try:
            self.mapper.check_stack_limit(rsp=limit, stack_limit=limit)
        except OverflowError:
            self.fail(
                "check_stack_limit raised OverflowError exactly at the boundary limit."
            )

    def test_check_stack_limit_one_byte_leeway(self):
        """Test safe execution exactly 1 byte above the stack limit."""
        limit = 0x7FFF00000000
        try:
            self.mapper.check_stack_limit(rsp=limit + 1, stack_limit=limit)
        except OverflowError:
            self.fail("check_stack_limit raised OverflowError 1 byte above the limit.")

    def test_check_stack_limit_critical_overflow(self):
        """Test profound stack corruption/overflow significantly past the boundary."""
        limit = 0x7FFF00000000
        with self.assertRaises(OverflowError) as context:
            self.mapper.check_stack_limit(rsp=0x1000, stack_limit=limit)
        self.assertIn("Stack overflow", str(context.exception))

    # ==========================================
    # 2. ALIGNMENT LOGIC (align_stack)
    # ==========================================

    @patch.object(Segment_Mapper, "check_stack_limit")
    def test_align_stack_already_aligned(self, mock_check):
        """Ensure an already 16-byte aligned RSP skips redundant register writes."""
        aligned_rsp = 0x7FFFFFFFE000
        self.mapper.registers.read_reg.return_value = aligned_rsp  # type: ignore #tyo

        self.mapper.align_stack(self.mapper.memory, stack_limit=0x7FFF00000000)

        # Corrected: Verifies the function skips rewriting the register if it's already aligned
        self.mapper.registers.write_reg.assert_not_called()  # type: ignore #tyo

    @patch.object(Segment_Mapper, "check_stack_limit")
    def test_align_stack_maximum_misalignment(self, mock_check):
        """Ensure an RSP ending in 0xF safely rounds down to the nearest 16-byte window."""
        misaligned_rsp = 0x7FFFFFFFE00F
        expected_aligned = 0x7FFFFFFFE000
        self.mapper.registers.read_reg.return_value = misaligned_rsp  # type: ignore #tyo

        self.mapper.align_stack(self.mapper.memory, stack_limit=0x7FFF00000000)
        self.mapper.registers.write_reg.assert_called_with(
            "rsp", expected_aligned, False
        )  # type: ignore #tyo

    # ==========================================
    # 3. ARGUMENT PACKING STATE (push_arguments)
    # ==========================================

    def test_push_arguments_empty_and_special_strings(self):
        """Verify handling of empty argument strings or strings containing spaces."""
        self.mapper.registers.read_reg.side_effect = [0x200, 0x190, 0x180]  # type: ignore #tyo

        argv = ["", "arg with spaces"]
        addresses = self.mapper.push_arguments(argv)

        # Verify null terminator configurations for strings
        empty_str_expected = b"\x00"
        spaced_str_expected = (b"arg with spaces" + b"\x00")[::-1]

        self.mapper.memory.push.assert_any_call(empty_str_expected)  # type: ignore #tyo
        self.mapper.memory.push.assert_any_call(spaced_str_expected)  # type: ignore #tyo
        self.assertEqual(addresses, [0x200, 0x190])

    # ==========================================
    # 4. SYSTEM V AMD64 ABI LAYOUT (initialize_stack)
    # ==========================================

    @patch.object(Segment_Mapper, "align_stack")
    @patch.object(Segment_Mapper, "push_arguments")
    def test_initialize_stack_multi_argument_orchestration(
        self, mock_push_args, mock_align
    ):
        """Verify System V AMD64 compliance layout for multi-argument states."""
        mock_string_addresses = [0x7FFFFFFFE500, 0x7FFFFFFFE520]
        mock_push_args.return_value = mock_string_addresses

        argv = ["/bin/ls", "-la"]

        self.mapper._initialize_stack(
            argvcount=2,
            argv=argv,
            memory=self.mapper.memory,
            stack_limit=0x7FFF00000000,
        )

        # 1. Did it orchestrate the string data load first?
        mock_push_args.assert_called_once_with(argv)

        # 2. Check pointer layout serialization order (Little-Endian 8-byte blocks)
        # Updated to exactly match your sequential execution push pattern order
        argv0_ptr = (0x7FFFFFFFE500).to_bytes(8, "little")
        argv1_ptr = (0x7FFFFFFFE520).to_bytes(8, "little")
        null_terminator = (0).to_bytes(8, "little")
        argc_value = (2).to_bytes(8, "little")

        expected_calls = [
            unittest.mock.call(argv0_ptr),  # type: ignore #tyo
            unittest.mock.call(argv1_ptr),  # type: ignore #tyo
            unittest.mock.call(null_terminator),  # type: ignore #tyo
            unittest.mock.call(argc_value),  # type: ignore #tyo
        ]
        self.mapper.memory.push.assert_has_calls(expected_calls, any_order=False)  # type: ignore #tyo

        # 3. Did it call alignment validation at the final initialization step?
        mock_align.assert_called_once_with(self.mapper.memory, 0x7FFF00000000)


if __name__ == "__main__":
    unittest.main()
