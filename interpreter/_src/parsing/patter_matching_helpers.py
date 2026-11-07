# -----------------------
# SUPPORTED INSTRUCTIONS
# -----------------------
import re

VALID_START: str = "_start"

INSTRUCTIONS: dict[str, dict[str, int]] = {
    "cpu": {"syscall": 0},
    "data_path": {
        "lea": 2,
        "mov": 2,
        "push": 1,
        "pop": 1,
        "call": 1,
        "ret": 0,
        "jmp": 1,
        "je": 1,
        "jz": 1,  # Jump if Equal / Zero (ZF == 1)
        "jne": 1,
        "jnz": 1,  # Jump if Not Equal / Not Zero (ZF == 0)
        "jb": 1,
        "jc": 1,
        "jnae": 1,  # Jump if Below / Carry / Not Above or Equal (CF == 1)
        "jnb": 1,
        "jnc": 1,
        "jae": 1,  # Jump if Not Below / Not Carry / Above or Equal (CF == 0)
        "ja": 1,
        "jnbe": 1,  # Jump if Above / Not Below or Equal (CF == 0 and ZF == 0)
        "jbe": 1,
        "jna": 1,  # Jump if Below or Equal / Not Above (CF == 1 or ZF == 1)
        "jl": 1,
        "jnge": 1,  # Jump if Less / Not Greater or Equal (SF != OF)
        "jge": 1,
        "jnl": 1,  # Jump if Greater or Equal / Not Less (SF == OF)
        "jg": 1,
        "jnle": 1,  # Jump if Greater / Not Less or Equal (ZF == 0 and SF == OF)
        "jle": 1,
        "jng": 1,  # Jump if Less or Equal / Not Greater (ZF == 1 or SF != OF)
        "js": 1,  # Jump if Sign / Negative (SF == 1)
        "jns": 1,  # Jump if Not Sign / Positive (SF == 0)
        "jo": 1,  # Jump if Overflow (OF == 1)
        "jno": 1,  # Jump if Not Overflow (OF == 0)
        "jp": 1,
        "jpe": 1,  # Jump if Parity / Parity Even (PF == 1)
        "jnp": 1,
        "jpo": 1,  # Jump if Not Parity / Parity Odd (PF == 0)
    },
    "alu": {
        "cmp": 2,
        "add": 2,
        "adc": 2,
        "sub": 2,
        "sbb": 2,
        "inc": 1,
        "dec": 1,
        "and": 2,
        "or": 2,
        "xor": 2,
        "not": 1,
        "neg": 1,
        "xchg": 2,
        "mul": 1,
        "imul": 1,
        "div": 1,
        "idiv": 1,
        "shl": 2,
        "sal": 2,
        "shr": 2,
        "sar": 2,
        "rol": 2,
        "ror": 2,
        "rcl": 2,
        "rcr": 2,
    },
    "fpu": {},
}

# -------------------------------------
# Control Unit Helpers
# -------------------------------------

# -----------------
# keywords mapping
# -----------------

MASKS_DIRECTIVES = {
    "byte": 0xFF,
    "word": 0xFFFF,
    "dword": 0xFFFFFFFF,
    "qword": 0xFFFFFFFFFFFFFFFF,
}

# ----------------------------------------
# Patterns for operand type determination
# ----------------------------------------

COMPONENTS_ADDRESSING_PATTERN = r"(0x[\da-fA-F]+|[a-zA-Z_][a-zA-Z0-9_]*|\d+)"
GENERAL_PURPOSE_REGISTERS_PATTERN = r"([er]?[abcd]x|[er]?[sb]p|[er]?[sd]i|[er]?ip|r[89][bdlw]?|r1[0-5][bdlw]?|[abcd][hl])"
FPU_REGISTERS_PATTERN = r"(ymm[0-9]|xmm[0-9]|ymm1[0-5]|xmm1[0-5])"
NUMBER_REPRESENTATION_PATTERN = r"([-+]?(?:0[xX][\da-fA-F]+|\d[\da-fA-F]*[hH]|0[bB][01]+|[01]+[bB]|0[dD]\d+|\d+[dD]|[0-7]+[oOqQ]|\d+))"
WORD_OR_CHARACTERS_PATTERN = r"(\".*?\"|\'.*?\')"
IMMEDIATE_VALUE_PATTERN = (
    rf"({NUMBER_REPRESENTATION_PATTERN}|{WORD_OR_CHARACTERS_PATTERN})"
)
REGISTER_PATTERN = rf"({GENERAL_PURPOSE_REGISTERS_PATTERN}|{FPU_REGISTERS_PATTERN})"

# Directives for size identification and memory allocation verification.
SIZE_DIRECTIVES = {
    "db": (1, True),
    "dw": (2, True),
    "dd": (4, True),
    "dq": (8, True),
    "resb": (1, False),
    "resw": (2, False),
    "resd": (4, False),
    "resq": (8, False),
}

_RESERVED_KEYWORDS_PATTERN = "|".join(
    re.escape(k) for k in (*SIZE_DIRECTIVES.keys(), *MASKS_DIRECTIVES.keys())
)
CONSTANTS_AND_LABELS_PATTERN = (
    rf"\b(?!(?:{_RESERVED_KEYWORDS_PATTERN})\b)[a-zA-Z_]\w*\b"
)

DIRECT_AND_BASE_ADDRESSING_PATTERN = rf"^\[(?:\s*){COMPONENTS_ADDRESSING_PATTERN}(?:\s)*([\+\-](?:\s)*{COMPONENTS_ADDRESSING_PATTERN})*(?:\s)*\]$"
INDEXED_ADDRESSING_PATTERN = rf"^\[(?:\s*){COMPONENTS_ADDRESSING_PATTERN}(?:\s)*([\+\-\*](?:\s)*{COMPONENTS_ADDRESSING_PATTERN})*(?:\s)*\]$"
MEMORY_ADDRESSING_PATTERN = (
    rf"(?:{INDEXED_ADDRESSING_PATTERN}|{DIRECT_AND_BASE_ADDRESSING_PATTERN})"
)

OPERAND_PATTERN = rf"(?:{MEMORY_ADDRESSING_PATTERN}|{REGISTER_PATTERN}|{IMMEDIATE_VALUE_PATTERN}|{CONSTANTS_AND_LABELS_PATTERN})"

# -------------------------------------------//-------------------------------------------

# ------------------------------------
# Segment Mapper Helpers
# ------------------------------------

# Architecture Constants for sections start and memory allocation
TEXT_BASE = 0x400000
RODATA_BASE = 0x500000
DATA_BASE = 0x600000
BSS_BASE = 0x700000
STACK_START = 0x7FFFFFFFE000

# -----------------------------
# Pattern-Matching Expressions
# -----------------------------

TOKENS_PATTERN = r"""(?x)
    ".*?"|'.*?'|                  # Strings
    \[.*?\]|                      # Memory access
    \(.*?\)|                      # Parenthesized expressions
    [-+]?0[xX][\da-fA-F]+|        # Hex Prefix with sign
    [-+]?\d+[\da-fA-F]*[hH]|      # Hex Suffix with sign
    [-+]?0[bB][01]+|              # Binary prefix with sign
    [-+]?[01]+[bB]|               # Binary suffix with sign
    [-+]?0[dD]\d+|                # Decimal prefix with sign
    [-+]?\d+[dD]|                 # Decimal suffix with sign (-100d)
    [-+]?[0-7]+[oOqQ]|            # Octal with sign
    [a-zA-Z_]\w*:|                # Label/variable declarations
    [a-zA-Z_]\w*|                 # Instructions / Registers / Labels (referenced, not declared)
    [-+]?\d+                      # Signed Decimals
"""

ELEMENTS_TO_SKIP = r"^[,\s]+$"  # Commas and whitespace to skip during parsing
