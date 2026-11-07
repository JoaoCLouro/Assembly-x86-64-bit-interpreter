from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    IRRECOVERABLE_ERROR = -1000
    DATA_FORMAT_ERROR = -1
    BSS_FORMAT_ERROR = -2
    CONSTANT_DECLARATION_ERROR = -3
    NO_START_LABEL = 1
    DUPLICATE_LABEL = 2
    UNOPENABLE_FILE = 4
    STACK_OVERFLOW = 5
    INVALID_INSTRUCTION_SYNTAX = 10
    RESERVED_KEYWORD_VIOLATION = 11
    INVALID_SYSCALL = 12
    NO_EXIT_FOUND = 13
    INVALID_OR_UNSUPPORTED_INSTRUCTION = 14
    BY_0_DIVISION_ERROR = 15
    SOFTWARE_ERROR = 109101
    # To be continued later

    def __str__(self) -> str:
        match self:
            case ExitCode.SUCCESS:
                return "SUCCESS"
            case ExitCode.IRRECOVERABLE_ERROR:
                return "IRRECOVERABLE_ERROR"
            case ExitCode.DATA_FORMAT_ERROR:
                return "DATA_FORMAT_ERROR"
            case ExitCode.BSS_FORMAT_ERROR:
                return "BSS_FORMAT_ERROR"
            case ExitCode.CONSTANT_DECLARATION_ERROR:
                return "CONSTANT_DECLARATION_ERROR"
            case ExitCode.NO_START_LABEL:
                return "NO_START_LABEL"
            case ExitCode.DUPLICATE_LABEL:
                return "DUPLICATE_LABEL"
            case ExitCode.UNOPENABLE_FILE:
                return "UNOPENABLE_FILE"
            case ExitCode.STACK_OVERFLOW:
                return "STACK_OVERFLOW"
            case ExitCode.INVALID_INSTRUCTION_SYNTAX:
                return "INVALID_INSTRUCTION_SYNTAX"
            case ExitCode.RESERVED_KEYWORD_VIOLATION:
                return "RESERVED_KEYWORD_VIOLATION"
            case ExitCode.INVALID_SYSCALL:
                return "INVALID_SYSCALL"
            case ExitCode.NO_EXIT_FOUND:
                return "NO_EXIT_FOUND"
            case ExitCode.INVALID_OR_UNSUPPORTED_INSTRUCTION:
                return "INVALID_OR_UNSUPPORTED_INSTRUCTION"
            case ExitCode.BY_0_DIVISION_ERROR:
                return "BY_0_DIVISION_ERROR"
            case ExitCode.SOFTWARE_ERROR:
                return "SOFTWARE_ERROR"
            case _:
                return f"UNKNOWN_ERROR_{self.value}"
