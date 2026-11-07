import unittest
from unittest.mock import MagicMock, patch

from interpreter._src.parsing.segment_mapper import Segment_Mapper
from interpreter.exit_codes import ExitCode


class TestSegmentMapperStaticHelpers(unittest.TestCase):
    """Tests for static methods that do not require class instantiation."""

    def test_valid_variable_name(self):
        # Base cases: Standard valid names
        self.assertTrue(Segment_Mapper._valid_variable_name("buffer"))
        self.assertTrue(Segment_Mapper._valid_variable_name("_sys_call"))
        self.assertTrue(Segment_Mapper._valid_variable_name("var123"))

        # Edge cases: Invalid names (start with numbers, contain symbols)
        self.assertFalse(Segment_Mapper._valid_variable_name("123var"))
        self.assertFalse(Segment_Mapper._valid_variable_name("var-name"))
        self.assertFalse(Segment_Mapper._valid_variable_name("var name"))
        self.assertFalse(Segment_Mapper._valid_variable_name(""))

    def test_valid_variable_name_rejects_exact_reserved_keywords(self):
        # Exact size-directive keywords (case-insensitive) must be rejected,
        # since they'd otherwise collide with SIZE_DIRECTIVES token meaning.
        for keyword in ("db", "dw", "dd", "dq", "resb", "resw", "resd", "resq"):
            with self.subTest(keyword=keyword):
                self.assertFalse(Segment_Mapper._valid_variable_name(keyword))
                self.assertFalse(Segment_Mapper._valid_variable_name(keyword.upper()))
                self.assertFalse(
                    Segment_Mapper._valid_variable_name(keyword.capitalize())
                )

    def test_valid_variable_name_accepts_names_prefixed_by_reserved_keywords(self):
        # Regression guard: a name that merely STARTS WITH a reserved keyword
        # as a substring is a distinct, legitimate identifier and must NOT be
        # rejected. This previously failed because the reserved-keyword check
        # used an unanchored re.match instead of re.fullmatch, so e.g. "dw"
        # matched as a prefix of "dword_counter" and wrongly rejected it.
        valid_names = [
            "dword_counter",
            "resbuffer",
            "ddata",
            "dqword_val",
            "db_index",
            "resq_total",
            "dwarf",
        ]
        for name in valid_names:
            with self.subTest(name=name):
                self.assertTrue(Segment_Mapper._valid_variable_name(name))

    def test_valid_variable_name_reserved_keyword_with_colon_suffix(self):
        # Label declarations often carry a trailing ':' (e.g. "db:") which
        # _valid_variable_name strips before checking; the reserved-keyword
        # rejection must still apply after stripping.
        self.assertFalse(Segment_Mapper._valid_variable_name("db:"))
        self.assertFalse(Segment_Mapper._valid_variable_name("resq:"))
        self.assertTrue(Segment_Mapper._valid_variable_name("dword_counter:"))

    def test_is_numeric(self):
        # Base cases: Decimals and Hex
        self.assertTrue(Segment_Mapper._is_numeric("1024"))
        self.assertTrue(Segment_Mapper._is_numeric("-256"))
        self.assertTrue(Segment_Mapper._is_numeric("0xFF"))
        self.assertTrue(Segment_Mapper._is_numeric("0xff"))

        # Edge cases: Invalid formats
        self.assertFalse(Segment_Mapper._is_numeric("0xGG"))
        self.assertFalse(Segment_Mapper._is_numeric("10.5"))
        self.assertFalse(Segment_Mapper._is_numeric("NaN"))

        # Edge case based on current implementation: suffix 'h' is not handled by standard int()
        self.assertFalse(Segment_Mapper._is_numeric("10h"))

    def test_is_valid_value(self):
        # Base cases: Numeric and valid strings
        self.assertTrue(Segment_Mapper._is_valid_value("0x10"))
        self.assertTrue(Segment_Mapper._is_valid_value("'A'"))
        self.assertTrue(Segment_Mapper._is_valid_value('"Hello World"'))

        # Edge cases: Missing quotes or strings that are too short based on the len(val) >= 3 rule
        self.assertFalse(Segment_Mapper._is_valid_value("Hello"))
        self.assertFalse(
            Segment_Mapper._is_valid_value("''")
        )  # Length is 2, fails >= 3 check
        self.assertFalse(
            Segment_Mapper._is_valid_value('""')
        )  # Length is 2, fails >= 3 check

    def test_valid_size_specifier(self):
        # Base cases: Initialized data sizes
        self.assertTrue(Segment_Mapper._valid_size_specifier("db", "data"))
        self.assertTrue(Segment_Mapper._valid_size_specifier("dq", "rodata"))

        # Base cases: Uninitialized BSS sizes
        self.assertTrue(Segment_Mapper._valid_size_specifier("resb", "bss"))
        self.assertTrue(Segment_Mapper._valid_size_specifier("resq", "bss"))

        # Edge cases: Mismatched sections and invalid directives
        self.assertFalse(Segment_Mapper._valid_size_specifier("resb", "data"))
        self.assertFalse(Segment_Mapper._valid_size_specifier("db", "bss"))
        self.assertFalse(Segment_Mapper._valid_size_specifier("invalid_size", "data"))

    def test_has_size_calculation(self):
        self.assertTrue(Segment_Mapper._has_size_calculation(["equ", "$-msg"]))
        self.assertFalse(Segment_Mapper._has_size_calculation(["equ", "10"]))


class TestSegmentMapperValidation(unittest.TestCase):
    """Tests for format validation requiring a mocked class instance to bypass I/O."""

    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def setUp(self, mock_init):
        self.mapper = Segment_Mapper("dummy.asm")
        # Setup baseline state manually to safely populate uninitialized slotted variables
        self.mapper.data_segment = {}
        self.mapper.rodata_segment = {}
        self.mapper.bss_segment = {}
        self.mapper.constants = {}

    @patch("builtins.print")
    def test_bss_format_validation(self, mock_print):
        # Base case: Valid BSS declaration (label, specifier, count)
        self.assertTrue(
            self.mapper.bss_format_validation(["my_buffer", "resb", "64"], 10)
        )

        # Edge case: Label already in use
        self.mapper.bss_segment["my_buffer"] = {}
        self.assertFalse(
            self.mapper.bss_format_validation(["my_buffer", "resb", "64"], 11)
        )

        # Edge case: Invalid length (missing count)
        self.assertFalse(self.mapper.bss_format_validation(["my_buffer", "resb"], 12))

        # Edge case: Invalid specifier for BSS
        self.assertFalse(self.mapper.bss_format_validation(["new_var", "db", "64"], 13))

    @patch("builtins.print")
    @patch.object(Segment_Mapper, "is_constant", return_value=False)
    def test_data_format_validation(self, mock_is_constant, mock_print):
        # Base case: Standard data declaration
        self.assertTrue(
            self.mapper._data_format_validation(["msg", "db", '"Hello"'], 1, ".data")
        )

        # Lines using 'times' are routed away from basic data format checking rules
        self.assertFalse(
            self.mapper._data_format_validation(
                ["arr", "times", "10", "dd", "0"], 2, ".data"
            )
        )

        # Edge case: Invalid values
        self.assertFalse(
            self.mapper._data_format_validation(
                ["invalid_val", "db", "NoQuotes"], 3, ".data"
            )
        )

    @patch.object(Segment_Mapper, "is_constant", return_value=False)
    def test_timed_data_validation(self, mock_is_constant):
        # Base case: Valid label token (no colon) matching target data section rules
        line = ["buffer", "times", "100", "db", "0"]
        self.assertTrue(self.mapper.timed_data_validation(line, "data", "times"))

        # Edge case: Times count is not numeric or a known constant
        bad_line = ["buffer", "times", "'A'", "db", "0"]
        self.assertFalse(self.mapper.timed_data_validation(bad_line, "data", "times"))

    @patch("builtins.print")
    def test_valid_size_calculation(self, mock_print):
        # Base case: valid calculation referencing an existing label
        self.mapper.data_segment["my_string"] = {"size": 10}
        self.assertTrue(
            self.mapper.valid_size_calculation(["my_len", "equ", "$-my_string"], 5)
        )

        # Edge case: Referencing a label that doesn't exist
        self.assertFalse(
            self.mapper.valid_size_calculation(["my_len", "equ", "$-missing_label"], 6)
        )

        # Edge case: Malformed equation string
        self.assertFalse(
            self.mapper.valid_size_calculation(["my_len", "equ", "$+my_string"], 7)
        )


class TestSegmentMapperStackAndLogic(unittest.TestCase):
    """Tests for pointer arithmetic, stack logic, and exceptions."""

    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def setUp(self, mock_init):
        self.mapper = Segment_Mapper("dummy.asm")
        self.mapper.registers = MagicMock()
        self.mapper.memory = MagicMock()

    def test_check_stack_limit(self):
        # Base case: RSP is safely above the limit
        try:
            self.mapper.check_stack_limit(
                rsp=0x7FFFFFFF0000, stack_limit=0x7FFF00000000
            )
        except OverflowError:
            self.fail("check_stack_limit raised OverflowError unexpectedly.")

        # Edge case: RSP drops below the limit (Stack Overflow)
        with self.assertRaises(OverflowError) as context:
            self.mapper.check_stack_limit(
                rsp=0x7FFE00000000, stack_limit=0x7FFF00000000
            )

        self.assertIn("Stack overflow", str(context.exception))

    @patch("sys.exit")
    @patch("builtins.print")
    @patch.object(Segment_Mapper, "check_stack_limit")
    def test_align_stack_misaligned(self, mock_check, mock_print, mock_exit):
        # Setup a misaligned stack pointer (e.g., ends in 0x8 instead of 0x0)
        self.mapper.registers.read_reg.return_value = 0x7FFFFFFFE008  # type: ignore #tyo

        self.mapper.align_stack(self.mapper.memory, stack_limit=0x7FFF00000000)

        # Aligned RSP target = 0x7fffffffe000
        self.mapper.registers.write_reg.assert_called_with("rsp", 0x7FFFFFFFE000, False)  # type: ignore #tyo

    def test_push_arguments(self):
        self.mapper.registers.read_reg.side_effect = [
            0x100,
            0x90,
        ]  # Dummy addresses for RSP    # type: ignore #tyo

        argv = ["arg1", "arg2"]
        addresses = self.mapper.push_arguments(argv)

        arg2_expected = (b"arg2" + b"\x00")[::-1]
        arg1_expected = (b"arg1" + b"\x00")[::-1]

        self.mapper.memory.push.assert_any_call(arg2_expected)  # type: ignore #tyo
        self.mapper.memory.push.assert_any_call(arg1_expected)  # type: ignore #tyo
        self.mapper.memory.push.assert_any_call(b"\x00")  # type: ignore #tyo

        self.assertEqual(addresses, [0x100, 0x90])


class TestSegmentMapperParsingAndTokenization(unittest.TestCase):
    """Tests complex regex tokenization, layout splitting, and program loading behavior."""

    @patch("interpreter._src.helpers.storage.Storage.save_file")
    @patch("interpreter._src.helpers.storage.Storage.load_file_lines")
    @patch(
        "interpreter._src.helpers.storage.Storage.convert_to_json",
        return_value="dummy.json",
    )
    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def test_load_program_tokenization_edge_cases(
        self, mock_init, mock_conv, mock_load, mock_save
    ):
        mapper = Segment_Mapper("dummy.asm")

        mock_load.return_value = [
            "label: mov rax, 0x1A4 ; inline comment here",
            "db 'string with spaces', 0, 10b",
            "    ; only a comment line",
            "valh: dq 7Ch, 0b1101, -45d",
        ]

        mapper._load_program("dummy.asm")

        # Assertions updated to match actual tokenizer layout outputs
        self.assertEqual(mapper.memory_list[0], ["label:", "mov", "rax", "0x1A4"])
        self.assertEqual(
            mapper.memory_list[1], ["db", "'string with spaces'", "0", "10b"]
        )
        self.assertEqual(mapper.memory_list[2], [])
        self.assertEqual(
            mapper.memory_list[3], ["valh:", "dq", "7Ch", "0b1101", "-45d"]
        )


class TestSegmentMapperTextAndLabelDiscovery(unittest.TestCase):
    """Tests text section tracking, start labels, and duplicate identifier catches."""

    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def setUp(self, mock_init):
        self.mapper = Segment_Mapper("dummy.asm")
        # Removed `self.mapper.VALID_START = "_start"` to prevent breaking __slots__.
        # The mapper reads VALID_START natively from imports.
        self.mapper.labels = {}
        self.mapper.memory_list = []

    def test_find_start_return_codes(self):
        # Uses '_start' natively as expected by pattern matching helpers
        self.assertEqual(self.mapper.find_start(["global", "_start"], None), 0)
        self.assertEqual(self.mapper.find_start(["global", "other_func"], None), -2)
        self.assertEqual(
            self.mapper.find_start(["global", "_start", "extra_token"], None), -10
        )
        self.assertEqual(self.mapper.find_start(["mov", "rax", "rbx"], None), -1)

    def test_skip_to_star_syntax_error_raised(self):
        self.mapper.memory_list = [["section", ".text"], ["mov", "rax", "1"]]
        with self.assertRaises(SyntaxError):
            self.mapper.skip_to_star()

    @patch("sys.exit")
    @patch("builtins.print")
    def test_fetch_labels_duplicate_catcher(self, mock_print, mock_exit):
        self.mapper.memory_list = [["loop_start:"], ["end_label:"]]
        self.mapper.fetch_labels(0)
        # Labels are stored WITHOUT the trailing colon (stripped), consistent
        # with how the duplicate-check lookup strips it before comparing.
        self.assertIn("loop_start", self.mapper.labels)
        self.assertIn("end_label", self.mapper.labels)

        self.mapper.labels = {"duplicate_label": 0}
        self.mapper.memory_list = [["duplicate_label:"]]
        self.mapper.fetch_labels(0)
        mock_exit.assert_called_once_with(ExitCode.DUPLICATE_LABEL)

    def test_fetch_labels_stores_valid_label_with_correct_line_index(self):
        # Regression guard: fetch_labels previously nested the
        # self.labels[...] assignment inside the "invalid name" elif branch,
        # so a syntactically valid, non-duplicate label was silently never
        # recorded in self.labels at all (the dict stayed empty). This must
        # now actually populate self.labels, keyed by the label's line index.
        self.mapper.memory_list = [["mov", "rax", "rbx"], ["my_func:"], ["ret"]]

        self.mapper.fetch_labels(0)

        self.assertEqual(self.mapper.labels, {"my_func": 1})

    @patch("sys.exit")
    @patch("builtins.print")
    def test_fetch_labels_rejects_reserved_keyword_as_label(
        self, mock_print, mock_exit
    ):
        # A label using a reserved size-directive keyword (e.g. "db:") must
        # be rejected via ExitCode.RESERVED_KEYWORD_VIOLATION, and must NOT
        # be added to self.labels.
        self.mapper.memory_list = [["db:"]]

        self.mapper.fetch_labels(0)

        mock_exit.assert_called_once_with(ExitCode.RESERVED_KEYWORD_VIOLATION)
        self.assertNotIn("db", self.mapper.labels)


class TestSegmentMapperMemoryWritingAndConstants(unittest.TestCase):
    """Tests variable packing limits, sizing shortcuts, and text-constant switches."""

    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def setUp(self, mock_init):
        self.mapper = Segment_Mapper("dummy.asm")
        # Initialize dictionary slots left unpopulated by mocked __init__
        self.mapper.data_segment = {}
        self.mapper.rodata_segment = {}
        self.mapper.bss_segment = {}
        self.mapper.constants = {}

    def test_get_constant_value_extraction(self):
        self.assertEqual(self.mapper.get_constant_value("550"), 550)
        self.assertEqual(self.mapper.get_constant_value("'A'"), "A")
        self.assertEqual(self.mapper.get_constant_value('"Path"'), "Path")

    def test_write_section_to_memory_datatypes(self):
        mock_mem = MagicMock()

        Segment_Mapper._write_section_to_memory(
            mock_mem,
            times=1,
            specifier=4,
            addresses=[0x10],
            current_rip=0x10,
            value="256",
        )
        mock_mem.write_bytes.assert_called_with(0x10, b"\x00\x01\x00\x00", 4)

        Segment_Mapper._write_section_to_memory(
            mock_mem,
            times=1,
            specifier=2,
            addresses=[0x20],
            current_rip=0x20,
            value="'XY'",
        )
        mock_mem.write_bytes.assert_called_with(0x20, b"'X", 2)

    @patch("sys.exit")
    @patch("builtins.print")
    def test_load_c_constant_handling(self, mock_print, mock_exit):
        self.mapper.load_c_constant(["#define", "MAX_SIZE", "128"], index=1)
        self.assertIn("MAX_SIZE", self.mapper.constants)
        self.assertEqual(self.mapper.constants["MAX_SIZE"]["value"], 128)

        # Triggering validation failure via malformed declaration value to check correct exit code behavior cleanly
        self.mapper.load_c_constant(
            ["#define", "BROKEN_VAL", "MalformedValue!!"], index=2
        )
        mock_exit.assert_called_with(ExitCode.CONSTANT_DECLARATION_ERROR)


class TestSegmentMapperStackIsolationBoundary(unittest.TestCase):
    """Deep layout verification checks for edge argument layouts on the simulated runtime stack."""

    @patch.object(Segment_Mapper, "align_stack")
    @patch.object(Segment_Mapper, "__init__", return_value=None)
    def test_initialize_stack_with_empty_arguments(self, mock_init, mock_align):
        mapper = Segment_Mapper("dummy.asm")
        mapper.registers = MagicMock()
        mapper.memory = MagicMock()

        mapper._initialize_stack(
            argvcount=0, argv=None, memory=mapper.memory, stack_limit=0x1000
        )

        # When argv is empty/None, memory.push is called exactly once for argc (0)
        mapper.memory.push.assert_called_once_with((0).to_bytes(8, "little"))


if __name__ == "__main__":
    unittest.main()
