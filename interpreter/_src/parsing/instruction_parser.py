import re

from ..bridges.register_manager import Registers_Interface
from ..helpers.my_types import BssSectionInfo, ConstantMap, DataSectionInfo, LabelMap
from . import patter_matching_helpers as PM


class Operand:
    """
    Represents a decoded operand for an x86-64 assembly instruction.

    Stores metadata regarding operand classification (register, memory, immediate),
    evaluated numeric memory addresses or register ordinals, byte sizes, high-byte flags,
    and usability state.

    :param valid: Indicates whether the operand holds active/valid decoded data
    :type valid: bool
    :param expression: Unprocessed or reconstructed string expression of the operand
    :type expression: str
    :param type: Numeric classification identifier (0: MEMORY, 1: REGISTER, 2: IMMEDIATE)
    :type type: int
    :param address: Evaluated numeric memory address or canonical register ordinal index
    :type address: int
    :param size: Declared or inferred size of the operand in bytes (1, 2, 4, 8, 16, 32)
    :type size: int
    :param is_high: Flag indicating high 8-bit register access (1 for ah, bh, ch, dh; else 0)
    :type is_high: int
    :param is_signed: Flag indicating signed register or arithmetic operand operations
    :type is_signed: int
    """

    __slots__ = [
        "address",
        "expression",
        "is_high",
        "is_signed",
        "size",
        "type",
        "valid",
    ]

    def __init__(self) -> None:
        """
        Initializes the parameters of the operand.
        """
        self.valid: bool = False  # Information validity flag for usability
        self.expression: str = ""
        self.type: int = 0  # OpType enum (e.g., REGISTER=1, MEMORY=0, IMMEDIATE=2)
        self.address: int = 0  # Virtual address or register index (long long)
        self.size: int = 0  # Size in bytes (1, 2, 4, 8, 16, 32)
        self.is_high: int = 0  # Flag for high register access (e.g., AH, BH)
        self.is_signed: int = 0  # Flag for signed register/operand operations

    def set(
        self,
        expression: str,
        op_type: int,
        address: int,
        size: int,
        is_high: int = 0,
        is_signed: int = 0,
    ) -> None:
        """
        Sets the parameters of the operand and enables use of this Operand info.
        """
        self.valid = True
        self.expression = expression
        self.type = op_type
        self.address = address
        self.size = size
        self.is_high = is_high
        self.is_signed = is_signed

    def clear(self) -> None:
        """
        Sets the validity parameter to False to signal not current/usable information.
        """
        self.valid = False
        self.expression = ""
        self.type = -1
        self.address = 0
        self.size = 0
        self.is_high = 0
        self.is_signed = 0

    def is_valid(self) -> bool:
        """
        Returns the usability status of this Operand object.
        """
        return self.valid

    def __str__(self):
        # For debug purposes
        return (
            "Operand: "
            + self.expression
            + "\nType: "
            + str(self.type)
            + "\nAddress: "
            + str(self.address)
            + "\nSize: "
            + str(self.size)
            + "\nHigh byte: "
            + str(self.is_high)
            + "\nSigned: "
            + str(self.is_signed)
            + "\nActive: "
            + str(self.valid)
        )


GP_REGISTER_ORDER = [
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

FPU_REGISTER_ORDER = [f"xmm{i}" for i in range(16)] + [f"ymm{i}" for i in range(16)]

# Pre-compiled module-level patterns for fast instruction layout matching
#
# NOTE: PM.OPERAND_PATTERN embeds its own internal '^'/'$' anchors inside the
# memory-addressing sub-patterns (e.g. DIRECT_AND_BASE_ADDRESSING_PATTERN is
# '^\[...\]$'). str.strip("^$") only removes characters from the very start/
# end of the *whole* pattern string, so those embedded anchors survive
# untouched — which previously broke any 2-operand match where one operand
# was a memory expression (the embedded '^...$' forced that operand alone to
# match the entire joined string). re.sub removes every occurrence, wherever
# it appears, which is what's actually needed here.
_ANCHOR_CHARS = re.compile(r"[\^$]")
_SIZE_PATTERN_STR = rf"(?:{'|'.join(re.escape(_ANCHOR_CHARS.sub('', k)) for k in (*PM.SIZE_DIRECTIVES.keys(), *PM.MASKS_DIRECTIVES.keys()))})"
_OP_PATTERN_STR = rf"(?:{_ANCHOR_CHARS.sub('', PM.OPERAND_PATTERN)})"

ONE_OPERAND_PATTERN = re.compile(
    rf"^(?:{_SIZE_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}|{_OP_PATTERN_STR})$",
    re.IGNORECASE,
)

TWO_OPERAND_PATTERN = re.compile(
    rf"^(?:"
    rf"{_SIZE_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}\s*,\s*{_SIZE_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}|"
    rf"{_OP_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}|"
    rf"{_SIZE_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}|"
    rf"{_OP_PATTERN_STR}\s*,\s*{_SIZE_PATTERN_STR}\s*,\s*{_OP_PATTERN_STR}"
    rf")$",
    re.IGNORECASE,
)


class Instruction_Parser:
    """
    Validates, tokenizes, and resolves operands for x86-64 assembly instructions.

    Parses tokenized assembly lines, verifies structural layout against expected operand counts,
    resolves symbolic identifiers (labels and constants), evaluates memory addressing expressions
    against current register states, and populates target `Operand` instances.

    :param op1: Destination/first operand instance updated by parsing operations
    :type op1: Operand
    :param op2: Source/second operand instance updated by parsing operations
    :type op2: Operand
    :param labels: Map linking label identifiers to target .text line indices
    :type labels: LabelMap
    :param constants: Map linking constant identifiers to literal value definitions
    :type constants: ConstantMap
    :param rodata: Data section structure for read-only constant data
    :type rodata: DataSectionInfo
    :param data: Data section structure for initialized writable data
    :type data: DataSectionInfo
    :param bss: Data section structure for uninitialized writable memory
    :type bss: BssSectionInfo
    :param registers: Interface bridge used to query live CPU register values during address computation
    :type registers: Registers_Interface
    :param expected_op_count: Number of operands required by the current instruction opcode
    :type expected_op_count: int
    :param line: Tokenized assembly instruction line (e.g., ['mov', 'rax', 'rbx'])
    :type line: list[str]
    """

    __slots__ = (
        "bss",
        "constants",
        "data",
        "expected_op_count",
        "labels",
        "line",
        "op1",
        "op2",
        "registers",
        "rip",
        "rodata",
    )

    def __init__(
        self,
        op1: Operand,
        op2: Operand,
        labels: LabelMap,
        constants: ConstantMap,
        rodata: DataSectionInfo,
        data: DataSectionInfo,
        bss: BssSectionInfo,
        registers: Registers_Interface,
    ):
        self.op1: Operand = op1
        self.op2: Operand = op2
        self.labels = labels
        self.constants = constants
        self.rodata = rodata
        self.data = data
        self.bss = bss
        self.registers: Registers_Interface = registers

        # Attributes to update in run time
        self.line = []
        self.expected_op_count = -1
        self.rip: int = -1  # Reset immediately before any call to parser

    def parse(self) -> None:
        """
        Executes the primary validation and parsing pipeline for the current instruction line.

        Verifies the tokenized instruction line against expected layout rules and operand counts.
        If validation succeeds, triggers operand extraction and address/value resolution.

        :return: None
        :rtype: None
        :raises SyntaxError: If the instruction tokens violate structural rules or expected operand counts at `self.rip`.
        """
        if not self.validate_instruction_line(self.line):  # type: ignore
            raise SyntaxError(
                f"Invalid instruction declaration syntax at line {self.rip}."
            )
        self.parse_operands(self.line[1:])  # type: ignore

    def parse_operands(self, line: list[str]) -> None:
        """
        Extracts raw size and operand expression pairs and triggers operand resolution.
        Delegates token processing to `get_operand_info` to construct a standardized 4-element
        tuple `[size2, op2, size1, op1]`, handles empty operand cases for 0-operand instructions,
        and passes the result to `solve_operands`.

        :param line: List of instruction tokens excluding the instruction in use.
        :type line: list[str]
        :return: None
        :rtype: None
        :raises SyntaxError: If operand syntax or size directive placement is invalid.
        :raises ValueError: If internal token indexing boundaries are exceeded.
        """
        operand_info: list[str] = self.get_operand_info(line)

        # Eliminate empty operand tuples for 0-operand instructions
        if operand_info[3] == "":
            operand_info = []

        self.solve_operands(operand_info)

    def get_operand_info(self, line: list[str]) -> list[str]:
        """
        Dynamically parses the operand declarations of an instruction.
        Tries to match size keywords and skips over the expected operand.
        Returns size and operand expression pairs in the format: [size2, op2, size1, op1]

        :param line: Line of code without the instruction mnemonic
        :type line: list[str]
        :return: List of size and operand expression pairs
        :rtype: list[str]
        :raises SyntaxError: If syntax is invalid for x86-64 code
        :raises ValueError: If an internal parsing limit error occurs
        """
        ret_list: list[str] = ["", "", "", ""]
        max_ret_value: int = 3
        last_idx: int = len(line) - 1
        size_directives = PM.SIZE_DIRECTIVES  # data declarations: db/dw/dd/dq
        mask_directives = (
            PM.MASKS_DIRECTIVES
        )  # instruction operand prefixes: byte/word/dword/qword
        operand_re = re.compile(rf"^({PM.OPERAND_PATTERN})$")

        i = 0
        while i < len(line):
            token = line[i]
            size_entry = size_directives.get(token)

            if size_entry is not None:
                size = size_entry[0]
            else:
                mask = mask_directives.get(token)
                size = (mask.bit_length() // 8) if mask is not None else None

            if size is not None:
                if i == last_idx or not operand_re.match(line[i + 1]):
                    raise SyntaxError(f"INVALID SYNTAX FORMAT AT LINE {self.rip}!")
                if max_ret_value < 1:
                    raise ValueError(
                        "Program parsing ran into a problem! Aborting execution ..."
                    )
                ret_list[max_ret_value] = line[i + 1]
                ret_list[max_ret_value - 1] = str(size)
                max_ret_value -= 2
                i += 2

            elif operand_re.match(token):
                if max_ret_value < 1:
                    raise ValueError(
                        "Program parsing ran into a problem! Aborting execution ..."
                    )
                ret_list[max_ret_value] = token
                if self.is_register(token):
                    ret_list[max_ret_value - 1] = str(
                        self.get_register_size(token, self.rip)
                    )
                else:
                    ret_list[max_ret_value - 1] = ""
                max_ret_value -= 2
                i += 1

            else:
                raise ValueError(
                    "Program parsing ran into a problem! Aborting execution ..."
                )
        return ret_list

    def solve_operands(self, operands_info: list[str]) -> None:
        """
        Decomposes and solves each operand declaration, computing final numeric memory addresses,
        resolving labels/constants, and determining register ordinals — then sets self.op1 and
        self.op2 (Operand instances) accordingly.

        :param operands_info: List of size/operand-expression pairs, or [] for 0-operand instructions
        :type operands_info: list[str]
        """
        if not operands_info:
            self.op1.clear()
            self.op2.clear()
            return

        # (operand_instance, size_idx, expr_idx) — op2 uses indices 0/1, op1 uses indices 2/3
        for operand_obj, size_idx, expr_idx in ((self.op2, 0, 1), (self.op1, 2, 3)):
            expr = operands_info[expr_idx]

            if expr == "":
                operand_obj.clear()
                continue

            size_str = operands_info[size_idx]
            size = int(size_str) if size_str != "" else 0

            if self.is_register(expr):
                self._solve_register_operand(operand_obj, expr, size)
            elif self.is_memory(expr):
                self._solve_memory_operand_into(operand_obj, expr, size)
            elif self.is_number(expr):
                val = self._parse_numeric_literal(expr)
                is_signed = 1 if val < 0 else 0
                raw_bits = val & 0xFFFFFFFFFFFFFFFF  # Mask for C FFI bindings
                operand_obj.set(expr, 2, raw_bits, size, is_signed=is_signed)
            elif self.is_label(expr):
                resolved = self._solve_label_or_constant(expr)
                operand_obj.set(expr, 2, resolved, size)
            else:
                raise ValueError(
                    "Program parsing ran into a problem! Aborting execution ..."
                )

        self._infer_unsized_memory_operand()

    def _infer_unsized_memory_operand(self) -> None:
        """
        Infers the byte size of an unsized memory operand (e.g. `[exit]`
        with no `byte`/`word`/`dword`/`qword` prefix) from the OTHER
        operand's size, when that other operand is a register.

        Mirrors standard NASM behavior: `mov rax, [exit]` is only
        unambiguous because `rax` is 8 bytes wide - a bare memory operand
        with no size directive and no register on the other side is a
        genuine syntax error (matches real assemblers requiring an
        explicit size directive in that case), so no inference happens
        if neither operand is a register.
        """
        op1, op2 = self.op1, self.op2

        if op1.is_valid() and op2.is_valid():
            # op1 is memory (type 0) or immediate (type 2) with no size, op2 is a register
            if op1.type in (0, 2) and op1.size == 0 and op2.type == 1:
                op1.size = op2.size
            # op2 is memory (type 0) or immediate (type 2) with no size, op1 is a register
            elif op2.type in (0, 2) and op2.size == 0 and op1.type == 1:
                op2.size = op1.size

    def _solve_register_operand(
        self, operand_obj: Operand, expr: str, size: int
    ) -> None:
        """
        Sets an Operand instance for a register operand.
        """
        is_high = 1 if re.fullmatch(r"[abcd]h", expr) else 0

        if self.is_fpu_register(expr):
            address = FPU_REGISTER_ORDER.index(expr)
        else:
            parent = self._get_parent_register(expr)
            address = GP_REGISTER_ORDER.index(parent)

        operand_obj.set(expr, 1, address, size, is_high=is_high)

    def _solve_memory_operand_into(
        self, operand_obj: Operand, expr: str, size: int
    ) -> None:
        """
        Sets an Operand instance for a memory operand.
        """
        computed_address = self._solve_memory_operand(expr)
        operand_obj.set(f"[{computed_address}]", 0, computed_address, size)

    def _get_parent_register(self, register: str) -> str:
        """
        Maps any general-purpose register alias to its canonical 64-bit family name.
        """
        match = re.fullmatch(r"(r(?:[89]|1[0-5]))[bdlw]?", register)
        if match:
            return match.group(1)

        alias_map = {"a": "rax", "b": "rbx", "c": "rcx", "d": "rdx"}
        if re.fullmatch(r"[abcd][hl]", register):
            return alias_map[register[0]]
        if re.fullmatch(r"[er]?[abcd]x", register):
            return alias_map[register[-2]]

        special_map = {
            "sp": "rsp",
            "esp": "rsp",
            "rsp": "rsp",
            "bp": "rbp",
            "ebp": "rbp",
            "rbp": "rbp",
            "si": "rsi",
            "esi": "rsi",
            "rsi": "rsi",
            "di": "rdi",
            "edi": "rdi",
            "rdi": "rdi",
        }
        if register in special_map:
            return special_map[register]

        raise ValueError(
            f"Program parsing ran into a problem! Unrecognized register alias: '{register}'"
        )

    # ------------------
    # Operand Decoders
    # ------------------

    def _solve_label_or_constant(self, name: str) -> int:
        """
        Resolves a bare identifier to a label's line index, a constant's
        literal value, or a data/rodata/bss variable's base memory address.

        Checked in this order: labels, constants, then data/rodata/bss
        variables. A variable resolves to the FIRST address in its
        'addresses' list (its base address) - not the value currently
        stored there - since this is used to compute a memory address for
        addressing expressions like `[exit]`, not to fetch the variable's
        value. The actual value at that address is read separately at
        execution time by whatever dereferences the resolved address.
        """
        if name in self.labels:
            return self.labels[name]
        if name in self.constants:
            return int(self.constants[name]["value"])
        for section in (self.data, self.rodata, self.bss):
            if name in section:
                return section[name]["addresses"][0]  # type: ignore
        raise SyntaxError(
            f"INVALID SYNTAX FORMAT AT LINE {self.rip}! Unresolved label or constant: '{name}'"
        )

    def _solve_memory_operand(self, operand: str) -> int:
        """
        Decomposes a memory addressing expression and computes the final numeric address.
        """
        inner = operand.strip()[1:-1]  # strip enclosing '[' ']'

        # Split into signed components: e.g. "ebx+ecx*4-8" -> ["ebx", "+ecx*4", "-8"]
        tokens = re.findall(r"[+\-][^+\-]+|^[^+\-]+", inner.replace(" ", ""))

        address = 0
        for token in tokens:
            sign = -1 if token.startswith("-") else 1
            term = token.lstrip("+-")

            if "*" in term:
                reg, scale = term.split("*")
                try:
                    value = self.registers.read_reg(reg) * int(scale)
                except Exception:
                    raise SyntaxError(
                        f"INVALID REGISTER NAME {reg} AT LINE {self.rip}!"
                    )
            elif self.is_register(term):
                try:
                    value = self.registers.read_reg(term)
                except Exception:
                    raise SyntaxError(
                        f"INVALID REGISTER NAME {term} AT LINE {self.rip}!"
                    )
            elif self.is_number(term):
                value = self._parse_numeric_literal(term)
            elif self.is_label(term):
                value = self._solve_label_or_constant(term)
            else:
                raise SyntaxError(
                    f"INVALID SYNTAX FORMAT AT LINE {self.rip}! Bad memory component: '{term}'"
                )
            address += sign * value
        return address

    def _parse_numeric_literal(self, literal: str) -> int:
        """
        Converts a numeric literal token into its integer value.
        """
        if re.fullmatch(r"[-+]?0[xX][\da-fA-F]+", literal):
            return int(literal, 16)
        if re.fullmatch(r"[-+]?\d[\da-fA-F]*h", literal, re.IGNORECASE):
            return int(literal.rstrip("hH"), 16)
        if re.fullmatch(r"[-+]?0[bB][01]+", literal):
            return int(literal, 2)
        if re.fullmatch(r"[-+]?[01]+b", literal, re.IGNORECASE):
            return int(literal.rstrip("bB"), 2)
        if re.fullmatch(r"[-+]?0[dD]\d+", literal):
            sign = -1 if literal.startswith("-") else 1
            return sign * int(literal.lstrip("+-")[2:], 10)
        if re.fullmatch(r"[-+]?\d+d", literal, re.IGNORECASE):
            return int(literal.rstrip("dD"), 10)
        if re.fullmatch(r"[-+]?[0-7]+[oq]", literal, re.IGNORECASE):
            return int(literal.rstrip("oqOQ"), 8)
        if re.fullmatch(r"[-+]?\d+", literal):
            return int(literal)
        raise ValueError(
            f"Program parsing ran into a problem! Unrecognized numeric literal: '{literal}'"
        )

    # ----------------------------
    # General Validation Methods
    # ----------------------------

    def validate_instruction_line(self, line: list[str]) -> bool:
        """
        Validates the operands of the current instruction line.
        """
        instruction_length: int = len(line)

        if instruction_length == 1:
            self.op1.clear()
            self.op2.clear()
            return True
        elif instruction_length > 5:
            self.op1.clear()
            self.op2.clear()
            return False
        else:
            try:
                return self.match_instruction_format(line[1:]) == self.expected_op_count
            except SyntaxError:
                return False

    # --------------------------
    # Pattern Matching Methods
    # --------------------------

    def match_instruction_format(self, instruction: list[str]) -> int:
        """
        Checks whether the operand declaration matches supported 1 or 2 operand formats.

        :param instruction: List of instruction tokens excluding the instruction in use.
        :type instruction: list[str]
        :return: Number of operands matched
        :rtype: int
        :raises SyntaxError: If no supported operand patterns are matched
        """
        joined_ops = ",".join(instruction)

        if TWO_OPERAND_PATTERN.match(joined_ops):
            return 2
        if ONE_OPERAND_PATTERN.match(joined_ops):
            return 1
        raise SyntaxError

    # -----------------------------
    # Operand Attribute Fetching
    # -----------------------------

    @staticmethod
    def get_register_size(register: str, rip: int) -> int:
        """
        Determines register size in bytes based on name.
        """
        if Instruction_Parser.is_fpu_register(register):
            return 32 if register.startswith("ymm") else 16

        if not Instruction_Parser.is_general_purpose_register(register):
            location = f" AT LINE {rip}" if rip is not None else ""  # type: ignore
            raise SyntaxError(f"INVALID SYNTAX FORMAT{location}!")

        if re.fullmatch(r"[abcd][hl]", register):
            return 1

        match = re.fullmatch(r"r(?:[89]|1[0-5])([bdlw]?)", register)
        if match:
            suffix = match.group(1)
            return {"": 8, "b": 1, "l": 1, "w": 2, "d": 4}[suffix]

        if register in ("rip", "eip", "ip"):
            return {"rip": 8, "eip": 4, "ip": 2}[register]

        if register.startswith("r"):
            return 8
        if register.startswith("e"):
            return 4
        return 2

    # -----------------
    # Type Validation
    # -----------------

    @staticmethod
    def is_memory(operand: str) -> bool:
        return bool(re.fullmatch(PM.MEMORY_ADDRESSING_PATTERN, operand))

    @staticmethod
    def is_number(operand: str) -> bool:
        return bool(re.fullmatch(PM.IMMEDIATE_VALUE_PATTERN, operand))

    @staticmethod
    def is_label(operand: str) -> bool:
        return bool(re.fullmatch(PM.CONSTANTS_AND_LABELS_PATTERN, operand))

    @staticmethod
    def is_register(operand: str) -> bool:
        return Instruction_Parser.is_general_purpose_register(
            operand
        ) or Instruction_Parser.is_fpu_register(operand)

    @staticmethod
    def is_general_purpose_register(operand: str) -> bool:
        return bool(re.fullmatch(PM.GENERAL_PURPOSE_REGISTERS_PATTERN, operand))

    @staticmethod
    def is_fpu_register(operand: str) -> bool:
        return bool(re.fullmatch(PM.FPU_REGISTERS_PATTERN, operand))

    # --------------------------------------------------
    # Unused / Utility Helpers (Might be useful later)
    # --------------------------------------------------

    # @staticmethod
    # def get_operand_type(operand: str, rip: int) -> int:
    #     """
    #     Determines operand type (0=Memory, 1=Register, 2=Immediate).
    #     Unused in parse pipeline: solve_operands checks types directly.
    #     """
    #     if Instruction_Parser.is_memory(operand):
    #         return 0
    #     if Instruction_Parser.is_register(operand):
    #         return 1
    #     if Instruction_Parser.is_immediate(operand):
    #         return 2
    #     raise SyntaxError(f"INVALID SYNTAX FORMAT AT LINE {rip}!")

    # @staticmethod
    # def is_immediate(operand: str) -> bool:
    #     """Checks if operand is a numeric literal or constant/label."""
    #     return Instruction_Parser.is_number(operand) or Instruction_Parser.is_label(operand)

    # @staticmethod
    # def is_direct_memory(operand: str) -> bool:
    #     """Checks for direct/base memory addressing format."""
    #     return bool(re.fullmatch(PM.DIRECT_AND_BASE_ADDRESSING_PATTERN, operand))

    # @staticmethod
    # def is_indexed_memory(operand: str) -> bool:
    #     """Checks for indexed memory addressing format."""
    #     return bool(re.fullmatch(PM.INDEXED_ADDRESSING_PATTERN, operand))
