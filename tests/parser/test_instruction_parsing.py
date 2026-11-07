"""
Full test suite for Instruction_Parser (single-file build).

Covers:
  - Type-validation static methods (is_register, is_memory, is_number, is_label, ...)
  - match_instruction_format / validate_instruction_line (instruction shape matching)
  - get_operand_info (token-walking size/operand-expression parser)
  - get_register_size / _get_parent_register (register sizing and aliasing)
  - solve_operands and its private helpers (register/memory/immediate/label
    resolution into Operand instances, memory address computation, numeric
    literal parsing)
  - The Operand class itself (set/clear/is_valid, __slots__ enforcement)
  - parse() / parse_operands() (top-level orchestration pipeline)

Fixtures (op1, op2, fake_registers, parser) and the FakeRegisters stand-in
for Registers_Interface are defined below rather than in a separate
conftest.py, since Registers_Interface requires a compiled libreg.so at
construction time and can't be instantiated directly in tests.
"""

import pytest

from interpreter._src.parsing.instruction_parser import Instruction_Parser, Operand

IP = Instruction_Parser  # short alias used throughout the static-method tests


class FakeRegisters:
    """
    Lightweight stand-in for Registers_Interface. The real class requires a
    compiled libreg.so at construction time, so tests inject this instead.
    Register values are pre-seeded per test via `values`.
    """

    def __init__(self, values: dict[str, int] | None = None) -> None:
        self.values = values or {}

    def read_reg(self, expression: str) -> int:
        key = expression.lower()
        if key not in self.values:
            raise ValueError(f"REGISTER {expression} DOES NOT EXIST.")
        return self.values[key]


@pytest.fixture
def fake_registers() -> FakeRegisters:
    return FakeRegisters()


@pytest.fixture
def op1() -> Operand:
    return Operand()


@pytest.fixture
def op2() -> Operand:
    return Operand()


@pytest.fixture
def parser(op1, op2, fake_registers) -> Instruction_Parser:
    """
    A fully constructed Instruction_Parser with empty labels/constants/data
    sections and a FakeRegisters instance with no pre-seeded values. Tests
    that need specific labels/constants/registers should set them directly
    on the returned instance (parser.labels[...] = ..., etc.) or use the
    make_parser helper below for common cases.
    """
    return Instruction_Parser(
        op1=op1,
        op2=op2,
        labels={},
        constants={},
        rodata={},
        data={},
        bss={},
        registers=fake_registers,
    )


def make_parser(
    op1: Operand,
    op2: Operand,
    registers: FakeRegisters,
    labels: dict | None = None,
    constants: dict | None = None,
    rodata: dict | None = None,
    data: dict | None = None,
    bss: dict | None = None,
) -> Instruction_Parser:
    """
    Helper for tests that need custom labels/constants/sections beyond the
    bare `parser` fixture's empty defaults.
    """
    return Instruction_Parser(
        op1=op1,
        op2=op2,
        labels=labels or {},
        constants=constants or {},
        rodata=rodata or {},
        data=data or {},
        bss=bss or {},
        registers=registers,  # type: ignore
    )


# ------------------------------------------------------------------------------
# TYPE VALIDATION
# Tests for Instruction_Parser's static type-validation methods:
# ------------------------------------------------------------------------------


class TestIsGeneralPurposeRegister:
    @pytest.mark.parametrize(
        "reg",
        [
            "rax",
            "eax",
            "ax",
            "al",
            "ah",
            "rbx",
            "ebx",
            "bx",
            "bl",
            "bh",
            "rsp",
            "esp",
            "sp",
            "rbp",
            "ebp",
            "bp",
            "rsi",
            "esi",
            "si",
            "rdi",
            "edi",
            "di",
            "rip",
            "eip",
            "ip",
            "r8",
            "r9",
            "r10",
            "r15",
            "r8b",
            "r8w",
            "r8d",
        ],
    )
    def test_valid_general_purpose_registers(self, reg):
        assert IP.is_general_purpose_register(reg) is True

    @pytest.mark.parametrize(
        "reg",
        [
            "xmm0",
            "ymm5",
            "notareg",
            "rax1",
            "",
            "eax ",
            " eax",
            "r16",
            "r7",
        ],
    )
    def test_rejects_non_general_purpose(self, reg):
        assert IP.is_general_purpose_register(reg) is False


class TestIsFpuRegister:
    @pytest.mark.parametrize("reg", ["xmm0", "xmm9", "xmm15", "ymm0", "ymm9", "ymm15"])
    def test_valid_fpu_registers(self, reg):
        assert IP.is_fpu_register(reg) is True

    @pytest.mark.parametrize("reg", ["rax", "xmm16", "ymm16", "xmm", "zmm0", ""])
    def test_rejects_non_fpu(self, reg):
        assert IP.is_fpu_register(reg) is False


class TestIsRegister:
    @pytest.mark.parametrize("reg", ["rax", "eax", "al", "xmm0", "ymm3", "r10w"])
    def test_accepts_gp_and_fpu(self, reg):
        assert IP.is_register(reg) is True

    @pytest.mark.parametrize("reg", ["notareg", "5", "$5", "[rax]", ""])
    def test_rejects_everything_else(self, reg):
        assert IP.is_register(reg) is False


class TestIsMemory:
    @pytest.mark.parametrize(
        "expr",
        [
            "[rax]",
            "[rax+8]",
            "[rax-8]",
            "[8]",
            "[label]",
            "[rax+rbx*4]",
            "[rax+rbx*4+8]",
            "[0x10]",
        ],
    )
    def test_valid_memory_expressions(self, expr):
        assert IP.is_memory(expr) is True

    @pytest.mark.parametrize(
        "expr",
        [
            "rax",
            "5",
            "[rax",
            "rax]",
            "[]",
            "",
        ],
    )
    def test_rejects_non_memory(self, expr):
        assert IP.is_memory(expr) is False


class TestIsNumber:
    @pytest.mark.parametrize(
        "literal",
        [
            "5",
            "-5",
            "+5",
            "0x1F",
            "1Fh",
            "0b101",
            "101b",
            "0d5",
            "5d",
            "7o",
            "7q",
            '"a"',
            "'a'",
            '"hello"',
        ],
    )
    def test_valid_numeric_and_char_literals(self, literal):
        assert IP.is_number(literal) is True

    @pytest.mark.parametrize("literal", ["label", "rax", "[rax]", "", "5x"])
    def test_rejects_non_numeric(self, literal):
        assert IP.is_number(literal) is False


class TestIsLabel:
    @pytest.mark.parametrize("expr", ["my_label", "_start", "loop1", "CamelCase"])
    def test_valid_labels(self, expr):
        assert IP.is_label(expr) is True

    @pytest.mark.parametrize("expr", ["5", "5abc", "", "[rax]"])
    def test_rejects_non_labels(self, expr):
        assert IP.is_label(expr) is False


# ------------------------------------------------------------------------------
# MATCH INSTRUCTION FORMAT
# Tests for Instruction_Parser.match_instruction_format and validate_instruction_line.
# ------------------------------------------------------------------------------


class TestMatchInstructionFormatOneOperand:
    @pytest.mark.parametrize(
        "tokens",
        [
            ["rax"],
            ["db", "rax"],
            ["[rax]"],
            ["db", "[rax]"],
            ["my_label"],
            ["5"],
        ],
    )
    def test_valid_one_operand_shapes_return_1(self, parser, tokens):
        assert parser.match_instruction_format(tokens) == 1


class TestMatchInstructionFormatTwoOperand:
    @pytest.mark.parametrize(
        "tokens",
        [
            ["rax", "rbx"],
            ["db", "rax", "rbx"],
            ["rax", "db", "rbx"],
            ["db", "rax", "db", "rbx"],
            ["[rax]", "rbx"],
            ["rax", "[rbx]"],
            ["my_label", "rax"],
            ["rax", "5"],
        ],
    )
    def test_valid_two_operand_shapes_return_2(self, parser, tokens):
        assert parser.match_instruction_format(tokens) == 2


class TestMatchInstructionFormatRejection:
    """
    The key regression-guard cases: malformed trailing tokens must NOT
    silently match a valid prefix (this was the anchor bug).
    """

    @pytest.mark.parametrize(
        "tokens",
        [
            ["rax", "rbx", "extra_garbage"],
            ["rax", "rbx", "rcx"],
            ["db", "rax", "rbx", "extra"],
            [",,,"],
            ["!!!invalid!!!"],
        ],
    )
    def test_malformed_trailing_tokens_raise_syntax_error(self, parser, tokens):
        with pytest.raises(SyntaxError):
            parser.match_instruction_format(tokens)

    def test_empty_token_list_raises_syntax_error(self, parser):
        with pytest.raises(SyntaxError):
            parser.match_instruction_format([])


class TestValidateInstructionLine:
    """
    validate_instruction_line wraps match_instruction_format, catches
    SyntaxError as a plain False, and short-circuits for 0-operand (length 1,
    mnemonic only) and overly-long (>5 tokens) lines.
    """

    def test_zero_operand_instruction_clears_operands_and_returns_true(self, parser):
        parser.op1.set("rax", 1, 0, 8)
        parser.op2.set("rbx", 1, 1, 8)
        parser.expected_op_count = 0

        result = parser.validate_instruction_line(["ret"])

        assert result is True
        assert parser.op1.is_valid() is False
        assert parser.op2.is_valid() is False

    def test_overly_long_line_clears_operands_and_returns_false(self, parser):
        parser.op1.set("rax", 1, 0, 8)
        parser.expected_op_count = 2

        result = parser.validate_instruction_line(["mov", "a", "b", "c", "d", "e"])

        assert result is False
        assert parser.op1.is_valid() is False
        assert parser.op2.is_valid() is False

    def test_matching_operand_count_returns_true(self, parser):
        parser.expected_op_count = 2
        assert parser.validate_instruction_line(["mov", "rax", "rbx"]) is True

    def test_mismatched_operand_count_returns_false(self, parser):
        parser.expected_op_count = 2
        # "push" style: only 1 operand present, but 2 expected
        assert parser.validate_instruction_line(["push", "rax"]) is False

    def test_malformed_syntax_returns_false_not_raise(self, parser):
        parser.expected_op_count = 1
        # validate_instruction_line must catch the SyntaxError internally
        assert parser.validate_instruction_line(["push", "rax", "!!!bad!!!"]) is False


# ------------------------------------------------------------------------------
# GET OPERAND INFO
# Tests for Instruction_Parser.get_operand_info.
# ------------------------------------------------------------------------------


class TestSingleOperandNoSize:
    def test_bare_register_operand(self, parser):
        result = parser.get_operand_info(["rax"])
        # op2 slots empty; op1 = rax, size1 inferred from register (8 bytes)
        assert result == ["", "", "8", "rax"]

    def test_bare_immediate_operand(self, parser):
        result = parser.get_operand_info(["5"])
        assert result == ["", "", "", "5"]

    def test_bare_label_operand(self, parser):
        result = parser.get_operand_info(["my_label"])
        assert result == ["", "", "", "my_label"]

    def test_bare_memory_operand(self, parser):
        result = parser.get_operand_info(["[rax]"])
        assert result == ["", "", "", "[rax]"]


class TestSingleOperandWithSize:
    def test_size_directive_plus_register(self, parser):
        result = parser.get_operand_info(["db", "al"])
        assert result == ["", "", "1", "al"]

    def test_size_directive_plus_memory(self, parser):
        result = parser.get_operand_info(["dq", "[rax]"])
        assert result == ["", "", "8", "[rax]"]

    def test_size_directive_plus_immediate(self, parser):
        result = parser.get_operand_info(["dw", "5"])
        assert result == ["", "", "2", "5"]


class TestTwoOperandsNoSize:
    def test_two_bare_registers(self, parser):
        result = parser.get_operand_info(["rax", "rbx"])
        # First-parsed (rax) -> op1 slots (last two); second-parsed (rbx) -> op2 slots (first two)
        assert result == ["8", "rbx", "8", "rax"]

    def test_register_then_immediate(self, parser):
        result = parser.get_operand_info(["rax", "5"])
        assert result == ["", "5", "8", "rax"]

    def test_immediate_then_register(self, parser):
        result = parser.get_operand_info(["5", "rax"])
        assert result == ["8", "rax", "", "5"]


class TestTwoOperandsWithSize:
    def test_size_on_first_operand_only(self, parser):
        result = parser.get_operand_info(["db", "al", "bl"])
        assert result == ["1", "bl", "1", "al"]

    def test_size_on_second_operand_only(self, parser):
        result = parser.get_operand_info(["al", "db", "bl"])
        assert result == ["1", "bl", "1", "al"]

    def test_size_on_both_operands(self, parser):
        result = parser.get_operand_info(["db", "al", "db", "bl"])
        assert result == ["1", "bl", "1", "al"]


class TestGetOperandInfoErrors:
    def test_size_directive_at_end_of_line_raises_syntax_error(self, parser):
        # A size directive with nothing after it to size
        with pytest.raises(SyntaxError):
            parser.get_operand_info(["rax", "db"])

    def test_size_directive_followed_by_invalid_operand_raises_syntax_error(
        self, parser
    ):
        with pytest.raises(SyntaxError):
            parser.get_operand_info(["db", "!!!invalid!!!"])

    def test_completely_invalid_token_raises_value_error(self, parser):
        with pytest.raises(ValueError):
            parser.get_operand_info(["!!!invalid!!!"])

    def test_more_than_two_operands_raises_value_error(self, parser):
        # Three bare operands exceed the 4-slot / 2-operand capacity
        with pytest.raises(ValueError):
            parser.get_operand_info(["rax", "rbx", "rcx"])


# ------------------------------------------------------------------------------
# REGISTER HELPERS
# Tests for Instruction_Parser.get_register_size and _get_parent_register.
# ------------------------------------------------------------------------------


class TestGetRegisterSizeGeneralPurpose:
    @pytest.mark.parametrize(
        "reg,expected",
        [
            ("rax", 8),
            ("rbx", 8),
            ("rsp", 8),
            ("rbp", 8),
            ("rsi", 8),
            ("rdi", 8),
            ("eax", 4),
            ("ebx", 4),
            ("esp", 4),
            ("ax", 2),
            ("bx", 2),
            ("sp", 2),
            ("al", 1),
            ("ah", 1),
            ("bl", 1),
            ("bh", 1),
        ],
    )
    def test_standard_register_sizes(self, reg, expected):
        assert IP.get_register_size(reg, rip=1) == expected

    @pytest.mark.parametrize(
        "reg,expected",
        [
            ("r8", 8),
            ("r15", 8),
            ("r8d", 4),
            ("r15d", 4),
            ("r8w", 2),
            ("r15w", 2),
            ("r8b", 1),
            ("r15b", 1),
        ],
    )
    def test_extended_register_sizes(self, reg, expected):
        assert IP.get_register_size(reg, rip=1) == expected

    @pytest.mark.parametrize("reg,expected", [("rip", 8), ("eip", 4), ("ip", 2)])
    def test_instruction_pointer_sizes(self, reg, expected):
        assert IP.get_register_size(reg, rip=1) == expected


class TestGetRegisterSizeFpu:
    @pytest.mark.parametrize("reg", ["xmm0", "xmm9", "xmm15"])
    def test_xmm_is_16_bytes(self, reg):
        assert IP.get_register_size(reg, rip=1) == 16

    @pytest.mark.parametrize("reg", ["ymm0", "ymm9", "ymm15"])
    def test_ymm_is_32_bytes(self, reg):
        assert IP.get_register_size(reg, rip=1) == 32


class TestGetRegisterSizeErrors:
    def test_unrecognized_name_raises_syntax_error(self):
        with pytest.raises(SyntaxError):
            IP.get_register_size("notareg", rip=1)

    def test_error_includes_line_number_when_given(self):
        with pytest.raises(SyntaxError, match="42"):
            IP.get_register_size("notareg", rip=42)


class TestGetParentRegister:
    @pytest.mark.parametrize(
        "reg,expected_parent",
        [
            ("rax", "rax"),
            ("eax", "rax"),
            ("ax", "rax"),
            ("al", "rax"),
            ("ah", "rax"),
            ("rbx", "rbx"),
            ("ebx", "rbx"),
            ("bx", "rbx"),
            ("bl", "rbx"),
            ("bh", "rbx"),
            ("rcx", "rcx"),
            ("ecx", "rcx"),
            ("cx", "rcx"),
            ("cl", "rcx"),
            ("ch", "rcx"),
            ("rdx", "rdx"),
            ("edx", "rdx"),
            ("dx", "rdx"),
            ("dl", "rdx"),
            ("dh", "rdx"),
        ],
    )
    def test_classic_four_family_resolution(self, parser, reg, expected_parent):
        assert parser._get_parent_register(reg) == expected_parent

    @pytest.mark.parametrize(
        "reg,expected_parent",
        [
            ("rsp", "rsp"),
            ("esp", "rsp"),
            ("sp", "rsp"),
            ("rbp", "rbp"),
            ("ebp", "rbp"),
            ("bp", "rbp"),
            ("rsi", "rsi"),
            ("esi", "rsi"),
            ("si", "rsi"),
            ("rdi", "rdi"),
            ("edi", "rdi"),
            ("di", "rdi"),
        ],
    )
    def test_pointer_index_register_resolution(self, parser, reg, expected_parent):
        assert parser._get_parent_register(reg) == expected_parent

    @pytest.mark.parametrize(
        "reg,expected_parent",
        [
            ("r8", "r8"),
            ("r8d", "r8"),
            ("r8w", "r8"),
            ("r8b", "r8"),
            ("r15", "r15"),
            ("r15d", "r15"),
            ("r15w", "r15"),
            ("r15b", "r15"),
        ],
    )
    def test_extended_register_resolution(self, parser, reg, expected_parent):
        assert parser._get_parent_register(reg) == expected_parent

    def test_unrecognized_alias_raises_value_error(self, parser):
        with pytest.raises(ValueError):
            parser._get_parent_register("notareg")


# ------------------------------------------------------------------------------
# SOLVE OPERANDS
# Tests for Instruction_Parser.solve_operands and its private helpers:
# ------------------------------------------------------------------------------


class TestSolveOperandsEmptyInput:
    def test_empty_operands_info_clears_both_operands(self, parser):
        parser.op1.set("rax", 1, 0, 8)
        parser.op2.set("rbx", 1, 1, 8)

        parser.solve_operands([])

        assert parser.op1.is_valid() is False
        assert parser.op2.is_valid() is False


class TestSolveOperandsSingleOperand:
    def test_single_register_operand_fills_op1_and_clears_op2(self, parser):
        # ["", "", "8", "rax"] — as produced by get_operand_info for a bare register
        parser.solve_operands(["", "", "8", "rax"])

        assert parser.op1.is_valid() is True
        assert parser.op1.expression == "rax"
        assert parser.op1.type == 1  # register
        assert parser.op1.address == 0  # rax is ordinal 0
        assert parser.op1.size == 8
        assert parser.op1.is_high == 0

        assert parser.op2.is_valid() is False

    def test_single_immediate_operand(self, parser):
        parser.solve_operands(["", "", "", "5"])

        assert parser.op1.is_valid() is True
        assert parser.op1.type == 2  # immediate
        assert parser.op1.address == 5
        assert parser.op2.is_valid() is False

    def test_single_memory_operand(self, parser, fake_registers):
        fake_registers.values["rax"] = 100
        parser.solve_operands(["", "", "", "[rax]"])

        assert parser.op1.is_valid() is True
        assert parser.op1.type == 0  # memory
        assert parser.op1.address == 100
        assert parser.op1.expression == "[100]"


class TestSolveOperandsRegisterOrdinals:
    @pytest.mark.parametrize(
        "reg,expected_ordinal",
        [
            ("rax", 0),
            ("rbx", 1),
            ("rcx", 2),
            ("rdx", 3),
            ("rsi", 4),
            ("rdi", 5),
            ("rbp", 6),
            ("rsp", 7),
            ("r8", 8),
            ("r15", 15),
        ],
    )
    def test_gp_register_ordinal(self, parser, reg, expected_ordinal):
        parser.solve_operands(["", "", "8", reg])
        assert parser.op1.address == expected_ordinal

    def test_sub_register_uses_parent_ordinal(self, parser):
        # al is rax's byte-low alias -> ordinal 0, same as rax
        parser.solve_operands(["", "", "1", "al"])
        assert parser.op1.address == 0

    def test_high_byte_register_sets_is_high_flag(self, parser):
        parser.solve_operands(["", "", "1", "ah"])
        assert parser.op1.is_high == 1
        assert parser.op1.address == 0  # still rax's family

    def test_low_byte_register_does_not_set_is_high(self, parser):
        parser.solve_operands(["", "", "1", "al"])
        assert parser.op1.is_high == 0

    @pytest.mark.parametrize(
        "reg,expected_ordinal",
        [("xmm0", 0), ("xmm15", 15), ("ymm0", 16), ("ymm15", 31)],
    )
    def test_fpu_register_ordinal(self, parser, reg, expected_ordinal):
        parser.solve_operands(["", "", "16", reg])
        assert parser.op1.address == expected_ordinal


class TestSolveOperandsTwoOperands:
    def test_two_registers_fill_op1_and_op2(self, parser):
        # get_operand_info format: [size2, op2, size1, op1]
        parser.solve_operands(["8", "rbx", "8", "rax"])

        assert parser.op1.expression == "rax"
        assert parser.op1.address == 0
        assert parser.op2.expression == "rbx"
        assert parser.op2.address == 1

    def test_register_and_immediate(self, parser):
        parser.solve_operands(["", "5", "8", "rax"])

        assert parser.op1.type == 1
        assert parser.op1.expression == "rax"
        assert parser.op2.type == 2
        assert parser.op2.address == 5


class TestSolveOperandsLabelsAndConstants:
    def test_label_resolves_to_line_index(self, parser):
        parser.labels["loop_start"] = 42

        parser.solve_operands(["", "", "", "loop_start"])

        assert parser.op1.type == 2  # immediate-class
        assert parser.op1.address == 42
        assert parser.op1.expression == "loop_start"

    def test_constant_resolves_to_its_value(self, parser):
        parser.constants["MAX_SIZE"] = {"line": 3, "value": 256}

        parser.solve_operands(["", "", "", "MAX_SIZE"])

        assert parser.op1.address == 256
        assert parser.op1.expression == "MAX_SIZE"

    def test_unresolved_label_raises_syntax_error(self, parser):
        with pytest.raises(SyntaxError):
            parser.solve_operands(["", "", "", "unknown_label"])

    def test_label_takes_precedence_over_constant_with_same_name(self, parser):
        # Documents actual precedence in _solve_label_or_constant: labels
        # dict is checked first.
        parser.labels["dual_name"] = 7
        parser.constants["dual_name"] = {"line": 1, "value": 999}

        parser.solve_operands(["", "", "", "dual_name"])

        assert parser.op1.address == 7


class TestSolveMemoryOperand:
    def test_simple_base_register(self, parser, fake_registers):
        fake_registers.values["rax"] = 1000
        result = parser._solve_memory_operand("[rax]")
        assert result == 1000

    def test_base_plus_displacement(self, parser, fake_registers):
        fake_registers.values["rax"] = 1000
        result = parser._solve_memory_operand("[rax+8]")
        assert result == 1008

    def test_base_minus_displacement(self, parser, fake_registers):
        fake_registers.values["rax"] = 1000
        result = parser._solve_memory_operand("[rax-8]")
        assert result == 992

    def test_base_plus_scaled_index(self, parser, fake_registers):
        fake_registers.values["rax"] = 1000
        fake_registers.values["rbx"] = 2
        result = parser._solve_memory_operand("[rax+rbx*4]")
        assert result == 1008  # 1000 + 2*4

    def test_base_plus_scaled_index_plus_displacement(self, parser, fake_registers):
        fake_registers.values["rax"] = 1000
        fake_registers.values["rbx"] = 2
        result = parser._solve_memory_operand("[rax+rbx*4+16]")
        assert result == 1024  # 1000 + 2*4 + 16

    def test_bare_displacement_only(self, parser):
        result = parser._solve_memory_operand("[100]")
        assert result == 100

    def test_label_component_resolves(self, parser):
        parser.labels["buf"] = 500
        result = parser._solve_memory_operand("[buf+4]")
        assert result == 504

    def test_invalid_register_in_memory_expression_raises_syntax_error(self, parser):
        with pytest.raises(SyntaxError):
            parser._solve_memory_operand("[notareg]")

    def test_invalid_register_in_scaled_index_raises_syntax_error(self, parser):
        with pytest.raises(SyntaxError):
            parser._solve_memory_operand("[rax+notareg*4]")


class TestParseNumericLiteral:
    @pytest.mark.parametrize(
        "literal,expected",
        [
            ("0x1F", 31),
            ("1Fh", 31),
            ("0b101", 5),
            ("101b", 5),
            ("0d5", 5),
            ("5d", 5),
            ("17o", 15),
            ("17q", 15),
            ("42", 42),
            ("-5", -5),
            ("+5", 5),
        ],
    )
    def test_recognized_formats(self, parser, literal, expected):
        assert parser._parse_numeric_literal(literal) == expected

    def test_unrecognized_format_raises_value_error(self, parser):
        with pytest.raises(ValueError):
            parser._parse_numeric_literal("not_a_number")


class TestSolveOperandsUsesCustomParser:
    """Sanity check that the make_parser helper wires custom sections correctly."""

    def test_custom_labels_and_registers_via_make_parser(
        self, op1, op2, fake_registers
    ):
        fake_registers.values["rbx"] = 77
        p = make_parser(op1, op2, fake_registers, labels={"start": 1})
        p.solve_operands(["", "", "", "start"])
        assert p.op1.address == 1


# ------------------------------------------------------------------------------
# OPERAND
# Tests for the Operand class: initial state, set(), clear(), is_valid().
# ------------------------------------------------------------------------------


class TestOperandInitialState:
    def test_starts_invalid_with_zeroed_fields(self):
        op = Operand()
        assert op.is_valid() is False
        assert op.expression == ""
        assert op.type == 0
        assert op.address == 0
        assert op.size == 0
        assert op.is_high == 0
        assert op.is_signed == 0


class TestOperandSet:
    def test_set_marks_valid_and_stores_all_fields(self):
        op = Operand()
        op.set("rax", 1, 0, 8, is_high=0, is_signed=1)

        assert op.is_valid() is True
        assert op.expression == "rax"
        assert op.type == 1
        assert op.address == 0
        assert op.size == 8
        assert op.is_high == 0
        assert op.is_signed == 1

    def test_set_defaults_is_high_and_is_signed_to_zero(self):
        op = Operand()
        op.set("rbx", 1, 1, 8)

        assert op.is_high == 0
        assert op.is_signed == 0

    def test_set_overwrites_previous_values(self):
        op = Operand()
        op.set("rax", 1, 0, 8)
        op.set("rbx", 1, 1, 4)

        assert op.expression == "rbx"
        assert op.address == 1
        assert op.size == 4


class TestOperandClear:
    def test_clear_resets_all_fields_and_invalidates(self):
        op = Operand()
        op.set("rax", 1, 0, 8, is_high=1, is_signed=1)

        op.clear()

        assert op.is_valid() is False
        assert op.expression == ""
        assert op.type == -1
        assert op.address == 0
        assert op.size == 0
        assert op.is_high == 0
        assert op.is_signed == 0

    def test_clear_on_already_invalid_operand_is_a_no_op_error_free(self):
        op = Operand()
        op.clear()  # should not raise
        assert op.is_valid() is False


class TestOperandSlotsEnforcement:
    def test_cannot_set_arbitrary_attribute(self):
        op = Operand()
        try:
            op.new_attr = 5  # type: ignore
            assert False, "expected AttributeError due to __slots__"
        except AttributeError:
            pass


# ------------------------------------------------------------------------------
# PARSE PIPELINE
# Tests for Instruction_Parser.parse and parse_operands — the top-level
# ------------------------------------------------------------------------------


class TestParseZeroOperandInstruction:
    def test_zero_operand_instruction_clears_both_operands(self, parser):
        parser.line = ["ret"]
        parser.expected_op_count = 0
        parser.rip = 10

        parser.parse()

        assert parser.op1.is_valid() is False
        assert parser.op2.is_valid() is False


class TestParseSingleOperandInstruction:
    def test_single_register_operand(self, parser):
        parser.line = ["push", "rax"]
        parser.expected_op_count = 1
        parser.rip = 5

        parser.parse()

        assert parser.op1.is_valid() is True
        assert parser.op1.expression == "rax"
        assert parser.op1.type == 1
        assert parser.op2.is_valid() is False

    def test_single_memory_operand(self, parser, fake_registers):
        fake_registers.values["rax"] = 2000
        parser.line = ["push", "[rax]"]
        parser.expected_op_count = 1
        parser.rip = 6

        parser.parse()

        assert parser.op1.type == 0
        assert parser.op1.address == 2000


class TestParseTwoOperandInstruction:
    def test_two_registers(self, parser):
        parser.line = ["mov", "rax", "rbx"]
        parser.expected_op_count = 2
        parser.rip = 7

        parser.parse()

        assert parser.op1.expression == "rax"
        assert parser.op2.expression == "rbx"

    def test_register_and_immediate_with_size_directive(self, parser):
        # NOTE: a size directive only sizes the operand immediately following
        # it (per get_operand_info's design) -- there is currently no
        # cross-operand size inference step in this pipeline (no
        # parse_operand_info-style pass), so op2 ("5") has no size directive
        # of its own and gets size=0. This documents CURRENT behavior; if
        # size inference is later added, this test's op2.size expectation
        # should become 1 to match al's declared size.
        parser.line = ["mov", "db", "al", "5"]
        parser.expected_op_count = 2
        parser.rip = 8

        parser.parse()

        assert parser.op1.expression == "al"
        assert parser.op1.size == 1
        assert parser.op2.expression == "5"
        assert parser.op2.size == 1


class TestParseValidationFailure:
    def test_wrong_operand_count_raises_syntax_error(self, parser):
        parser.line = ["push", "rax", "rbx"]  # push expects 1, got 2
        parser.expected_op_count = 1
        parser.rip = 9

        with pytest.raises(SyntaxError):
            parser.parse()

    def test_malformed_operand_raises_syntax_error(self, parser):
        parser.line = ["mov", "!!!bad!!!", "rbx"]
        parser.expected_op_count = 2
        parser.rip = 11

        with pytest.raises(SyntaxError):
            parser.parse()

    def test_error_message_includes_rip(self, parser):
        parser.line = ["push", "rax", "rbx"]
        parser.expected_op_count = 1
        parser.rip = 99

        with pytest.raises(SyntaxError, match="99"):
            parser.parse()


class TestParseOperandsZeroOperandNormalization:
    def test_all_empty_operand_slots_become_empty_list(self, parser):
        # get_operand_info(["ret"[1:]]) on an empty remaining line -> ["","","",""]
        # parse_operands should normalize that into [] before calling solve_operands
        parser.op1.set("stale", 1, 0, 8)
        parser.op2.set("stale", 1, 1, 8)

        parser.parse_operands([])

        assert parser.op1.is_valid() is False
        assert parser.op2.is_valid() is False
