import re
import sys

from interpreter.exit_codes import ExitCode

from ..bridges.data_memory import Data_Memory
from ..bridges.register_manager import Registers_Interface
from ..helpers.my_types import (
    Address,
    BssSectionInfo,
    ConstantMap,
    DataSectionInfo,
    LabelMap,
)
from ..helpers.storage import Storage
from .patter_matching_helpers import (
    _RESERVED_KEYWORDS_PATTERN,
    BSS_BASE,
    DATA_BASE,
    ELEMENTS_TO_SKIP,
    RODATA_BASE,
    SIZE_DIRECTIVES,
    STACK_START,
    TOKENS_PATTERN,
    VALID_START,
)


class Segment_Mapper:
    """
    Class responsible for mapping program segments into memory.\n
    Parses the assembly file to identify sections, labels, constants, and initializes memory segments accordingly.
    Does validation of segment declarations and manages stack initialization.\n
    Uses Data_Memory class to handle memory operations.\n
    Provides methods to load program sections (.text, .data, .rodata, .bss) and constants.
    Initializes the stack with argc and argv values.\n
    If any syntax errors or critical issues are found during parsing, the program exits gracefully with appropriate error messages.\n
    All segment addresses are stored in respective dictionaries for easy access during execution. Actual values are stored in Data_Memory object on appropriate addresses.\n
    Author: João Carilho Louro

    :param file_name: Path to the assembly file
    :type file_name: str
    :param argvcount: Number of command line arguments
    :type argvcount: int
    :param argv: List of command line arguments
    :type argv: list[str] | None
    :param stack_limit: Minimum allowed value for the stack pointer
    :type stack_limit: int
    :return: None
    """

    # Memory footprint optimization
    __slots__ = (
        "bss_segment",
        "constants",
        "data_segment",
        "exit_status",
        "file_name",
        "labels",
        "memory",
        "memory_list",
        "registers",
        "rip",
        "rodata_segment",
        "stack_limit",
    )

    def __init__(
        self,
        file_name: str,
        argvcount: int = 0,
        argv: list[str] | None = None,
        stack_limit: int = 0x7FFF00000000,
    ) -> None:
        """
        Initializes the Segment_Mapper by loading the assembly file, parsing its sections, and setting up memory segments and stack.

        :param file_name: Path to the assembly file
        :type file_name: str
        :param argvcount: Number of command line arguments
        :type argvcount: int
        :param argv: List of command line arguments
        :type argv: list[str] | None
        :param stack_limit: Minimum allowed value for the stack pointer
        :type stack_limit: int
        :return: None
        """
        # ------------------------
        # Constraints definitions
        # ------------------------

        # Stack limit setting
        self.stack_limit: int = stack_limit

        # ---------------
        # Info holders
        # ---------------

        # File name holder (After conversion to a parsable json file)
        self.file_name: str = Storage.convert_to_json(file_name)
        # Value will be changed while parsing .text section
        self.rip: int = -1  # default invalid value
        # Memory used in the execution of the program
        self.memory_list: list[list[str]] = []

        # ---------------------------------------
        # Should only store addresses as actually memory values are stored in Data_Memory class
        self.rodata_segment: DataSectionInfo = {}
        self.data_segment: DataSectionInfo = {}
        self.bss_segment: BssSectionInfo = {}
        # ---------------------------------------

        self.labels: LabelMap = {}
        self.constants: ConstantMap = {}  # Stores constant values

        # Register handler class instance
        self.registers: Registers_Interface = Registers_Interface()
        # Memory handler class instance
        self.memory: Data_Memory = Data_Memory(self.registers, RODATA_BASE)

        self.exit_status: ExitCode = ExitCode.SUCCESS
        self._load_program(self.file_name)
        try:
            self._load_text()
            self._initialize_stack(argvcount, argv, self.memory, self.stack_limit)
            self._parse_section()
        except SystemExit:
            self.exit_status = ExitCode.IRRECOVERABLE_ERROR

    # -----------------------
    # PROGRAM LOADING
    # -----------------------
    def _load_program(self, file_name: str) -> None:
        """
        Loads the program into 'usable memory' and loads
        a json file with each line of relevant code properly separated
        into tokens of a list.

        :param file_name: name of the file to load
        :type file_name: str
        :return: Data_Memory object used to hold contents of labels
        :rtype: Data_Memory
        """
        program_lines: list[str] = Storage.load_file_lines(file_name)
        # List for usable memory initialization
        self.memory_list = []
        for line in program_lines:
            code_part: str = line.split(";")[0].strip()
            tokens: list[str] = re.findall(TOKENS_PATTERN, code_part)
            tokens = [
                token for token in tokens if not re.match(ELEMENTS_TO_SKIP, token)
            ]
            self.memory_list.append(tokens)
        Storage.save_file(file_name, self.memory_list)

    def _parse_section(self) -> None:
        """
        Parsing loop for the .data, .rodata and .bss sections of the program.\n
        It iterates through the memory_list, identifies section declarations, and calls appropriate methods to load data or bss segments into memory.\n
        It also validates the format of declarations and handles constant declarations.\n
        If any syntax errors are found during parsing, the program exits gracefully with appropriate error messages.
        """
        # Pointers for lines of usable memory and address at use from a Data_memory object
        index: int = 0
        current_rip: Address = RODATA_BASE
        while index < self.rip:
            tokens = self.memory_list[index]

            # Just for prevention
            if not tokens:
                index += 1
                continue

            if tokens[0] == "section":
                section_name: str = tokens[1]
                if (
                    section_name.lstrip(".") == "rodata"
                    or section_name.lstrip(".") == "data"
                ):
                    if section_name.lstrip(".") == "rodata":
                        current_rip = RODATA_BASE
                    else:
                        current_rip = DATA_BASE
                    current_rip, index = self._load_data(
                        current_rip, index, section_name.lstrip(".")
                    )
                    continue  # index already points past everything _load_data consumed
                elif section_name.lstrip(".") == "bss":
                    current_rip = BSS_BASE
                    current_rip, index = self._load_bss(current_rip, index)
                    continue  # index already points past everything _load_bss consumed
                elif section_name.lstrip(".") == "text":
                    return

            elif Segment_Mapper._is_constant_declaration(tokens):
                self._load_constant(tokens, index)
            index += 1

    # Schematics for each element of program sections:
    # |_variable name
    # |_'size': (number of bytes allocated)
    # |_'addresses': (address list from Data Memory objet)

    # Schematics for labels storage:
    # |_label name
    # |_'line': (index counter of load_text)

    # Schematics for constant storage:
    # |_constant name
    # |_'line': (index counter of load_text)
    # |_'value': (integer value)

    # ------------------------------------------
    # sections .data and .rodata related methods
    # ------------------------------------------

    def _load_data(
        self, current_rip: Address, index: int, section: str
    ) -> tuple[Address, int]:
        """
        Takes care of .data and .rodata components parsing as well as validation of the declarations format.

        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :param index: number of the line being parsed (the 'section .data'/'section .rodata' line itself)
        :param section: name of the section being parsed ('.data' or '.rodata')
        :return: tuple of (updated Address pointer, updated line index) after loading the
            section. The returned index points at the first line NOT consumed by this call
            (typically the next 'section' line, or one past the end of the file) - the
            caller should resume iterating FROM this index, not increment its own separately
            tracked index, or already-consumed lines (including any 'equ' constants declared
            inside this section) will be re-processed and falsely flagged as duplicates.
        :rtype: tuple[Address, int]
        """

        index += 1
        while (
            index < len(self.memory_list)
            and self.memory_list[index]
            and self.memory_list[index][0] != "section"
        ):
            tokens: list[str] = self.memory_list[index]
            formatted_tokens = Segment_Mapper._format_string(tokens)

            # constant validation
            if Segment_Mapper._is_constant_declaration(tokens):
                self._load_constant(tokens, index)

            elif not self._data_format_validation(tokens, index, section):
                sys.exit(ExitCode.DATA_FORMAT_ERROR)
            elif "times" in tokens:
                current_rip = self._load_timed_data(tokens, section, current_rip)
            elif len(tokens) > 3 or Segment_Mapper._any_string(tokens[2:]):
                current_rip = self._load_multiple_data(
                    formatted_tokens, section, current_rip
                )
            else:
                current_rip = self._load_single_data(tokens, section, current_rip)
            index += 1

        return current_rip, index

    def _data_format_validation(
        self, line: list[str], index: int, section: str
    ) -> bool:
        """
        Validates the format of a .data or .rodata declaration line.

        :param line: full line of code that has a .data or .rodata declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        :param section: name of the section being parsed ('.data' or '.rodata')
        :type section: str
        :return: True if the line is a valid .data or .rodata declaration, False otherwise
        :rtype: bool
        """

        if not line:
            return False
        label: str = line[0].rstrip(":")

        # Check label duplication
        if self._label_in_use(label):
            print(
                f"Variable {label} already declared. Exiting program on a SyntaxError..."
            )
            return False

        # Validates labels name
        elif not Segment_Mapper._valid_variable_name(label):
            print(
                f"INVALID VARIABLE NAME {label} AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        # "times" declaration validation
        if "times" in line:
            if not self.timed_data_validation(line, section, "times"):
                print(
                    f"UNSUPPORTED OR INCORRECT 'TIMES' {section.upper()} DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
                )
                return False
            return True

        # Standard declaration validation
        elif len(line) < 3:
            print(
                f"INVALID {section.upper()} DECLARATION AT LINE {index}.\nNot all required elements declared. Exiting program on a SyntaxError..."
            )
            return False

        elif not Segment_Mapper._valid_size_specifier(line[1], section.lstrip(".")):
            print(
                f"INVALID {section.upper()} SECTION SIZE SPECIFIER AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

            # 5. Fast value checks
        if not all(self._is_valid_value(val) for val in line[2:]):
            print(f"INVALID {section.upper()} VALUE DECLARATION AT LINE {index}.")
            return False
        return True

    def timed_data_validation(
        self, line: list[str], section: str, TIMES_KEY: str
    ) -> bool:
        """
        Validates declarations using the 'times' keyword.\n
        Declarations must follow the pattern <label>: times <count> <size_specifier> <init_value>\n

        :param line: full line of code that has a .data or .rodata declaration
        :type line: list[str]
        :param section: name of the section being parsed ('.data' or '.rodata')
        :type section: str
        :param TIMES_KEY: 'times' keyword for faster memory accesses
        :type TIMES_KEY: str
        :return: True if the declaration follows the desired pattern, False otherwise
        :rtype: bool
        """
        match line:
            case [_, "times", count, size_spec, val] if (
                self._is_numeric(count) or self.is_constant(count)
            ) and (self._is_valid_value(val) or self.is_constant(val)):
                return self._valid_size_specifier(size_spec, section)
            case _:
                return False

    def _load_timed_data(
        self, line: list[str], section: str, current_rip: Address
    ) -> Address:
        """
        Loads a timed data declaration into memory.

        :param line: full line of code that has a .data or .rodata timed declaration
        :type line: list[str]
        :param section: name of the section being parsed ('.data' or '.rodata')
        :type section: str
        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :type current_rip: Address
        :return: updated pointer to the Address in use to store values in the Data_memory object
        :rtype: Address
        """
        # times to declare a variable data
        times: int = int(line[2])
        # size declaration of the variable
        number_of_bytes: int = SIZE_DIRECTIVES[line[3]][0]
        # total number of bytes to allocate
        size: int = number_of_bytes * times

        addresses: list[Address] = self._define_segment(
            section, line[0].strip(":"), size, current_rip
        )

        Segment_Mapper._write_section_to_memory(
            self.memory, times, number_of_bytes, addresses, current_rip, value=line[4]
        )
        current_rip += size
        return current_rip

    def _load_multiple_data(
        self, line: list[str], section: str, current_rip: Address
    ) -> Address:
        """
        Loads a multiple data declaration into memory. Supports mixing
        string literals with comma-separated numeric values on one line
        (e.g. `msg: db "hi", 0x0a`).

        A string token expands into one write per CHARACTER (each 1 byte,
        regardless of the declared size specifier - a string is always
        byte-per-character), advancing current_rip once per character. A
        numeric token occupies exactly one number_of_bytes-sized slot, as
        before. Treating a whole string as a single number_of_bytes slot
        (the previous behavior) silently truncated it to 1 byte and threw
        off every subsequent value's address.

        :param line: full line of code (already quote-stripped) that has a .data or .rodata multiple declaration
        :type line: list[str]
        :param section: name of the section being parsed ('.data' or '.rodata')
        :type section: str
        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :type current_rip: Address
        :return: updated pointer to the Address in use to store values in the Data_memory object
        :rtype: Address
        """
        number_of_bytes: int = SIZE_DIRECTIVES[line[1]][0]

        # Total size must count each string CHARACTER as its own byte-slot,
        # not each string TOKEN as a single number_of_bytes-sized slot.
        size: int = 0
        for value in line[2:]:
            if Segment_Mapper._is_numeric(value):
                size += number_of_bytes
            else:
                size += len(value)

        # Initializes the new entry on the correct section
        self._define_segment(section, line[0].strip(":"), size, current_rip)

        for value in line[2:]:
            if Segment_Mapper._is_numeric(value):
                Segment_Mapper._write_section_to_memory(
                    self.memory,
                    1,
                    number_of_bytes,
                    [current_rip],
                    current_rip,
                    value=value,
                )
                current_rip += number_of_bytes
            else:
                for ch in value:
                    Segment_Mapper._write_section_to_memory(
                        self.memory, 1, 1, [current_rip], current_rip, value=ch
                    )
                    current_rip += 1
        return current_rip

    def _load_single_data(
        self, line: list[str], section: str, current_rip: Address
    ) -> Address:
        """
        Loads a single data declaration into memory.

        :param line: full line of code that has a .data or .rodata single declaration
        :type line: list[str]
        :param section: name of the section being parsed ('.data' or '.rodata')
        :type section: str
        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :type current_rip: Address
        :return: updated pointer to the Address in use to store values in the Data_memory object
        :rtype: Address
        """
        number_of_bytes: int = SIZE_DIRECTIVES[line[1]][0]
        size: int = number_of_bytes
        addresses: list[Address] = self._define_segment(
            section, line[0].strip(":"), size, current_rip
        )

        Segment_Mapper._write_section_to_memory(
            self.memory, 1, number_of_bytes, addresses, current_rip, value=line[2]
        )
        current_rip += size
        return current_rip

    @staticmethod
    def _any_string(tokens: list[str]):
        """
        Verifies if any element on a token list is a double quoted string (indicator of a stringed string declaration of a variable)
        """
        for elem in tokens:
            _elem = elem[1:-1]
            if (
                _elem.startswith('"')
                and _elem.endswith('"')
                or _elem.startswith("'")
                and _elem.endswith("'")
            ):
                return True
        return False

    @staticmethod
    def _format_string(tokens: list[str]) -> list[str]:
        """
        Formats the elements of a token list into usable string elements. If any of them is a string that is double quoted strips the escaped outer quotes.

        :param tokens: List of elements to format by the declaration conditions
        :type tokens: List[str]
        :returns: List of simplified elements formatted as by the conditions declared
        :rtype: list[str]
        """
        formatted_tokens = []

        for elem in tokens:
            quote_char = ""
            if (
                elem.startswith('"')
                and elem.endswith('"')
                or elem.startswith("'")
                and elem.endswith("'")
            ):
                formatted_tokens.append(Segment_Mapper._parse_string_elem(elem))
            else:
                formatted_tokens.append(elem)
        return formatted_tokens

    @staticmethod
    def _parse_string_elem(elem: str) -> str:
        """
        Removes any outer escaped quotes on a string
        """
        return elem.lstrip("\", '").rstrip("\", '")

    # ------------------------------
    # section .bss related methods
    # ------------------------------

    def _load_bss(self, current_rip: Address, index: int) -> tuple[Address, int]:
        """
        Takes care of .bss components parsing as well as validation of the declarations format.

        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :param index: number of the line being parsed (the 'section .bss' line itself)
        :return: tuple of (updated Address pointer, updated line index) after loading the
            section. The returned index points at the first line NOT consumed by this call -
            see _load_data's docstring for why the caller must resume from this index rather
            than incrementing its own separately tracked index.
        :rtype: tuple[Address, int]
        """
        index += 1
        while (
            index < len(self.memory_list)
            and self.memory_list[index]
            and self.memory_list[index][0] != "section"
        ):
            tokens: list[str] = self.memory_list[index]

            # constant validation
            if Segment_Mapper._is_constant_declaration(tokens):
                self._load_constant(tokens, index)
                index += 1
                continue

            if not self.bss_format_validation(tokens, index):
                sys.exit(ExitCode.BSS_FORMAT_ERROR)

            label: str = tokens[0].rstrip(":")

            if "times" in tokens:
                times: int = int(tokens[2])
                number_of_bytes: int = SIZE_DIRECTIVES[tokens[3]][0]
            else:
                # plain reserve form: [label, size_spec, count]
                times: int = int(tokens[2])
                number_of_bytes: int = SIZE_DIRECTIVES[tokens[1]][0]

            size: int = number_of_bytes * times
            if not Segment_Mapper._exists_in_section(label, self.bss_segment):
                self.bss_segment[label] = {"size": size, "addresses": []}

            addresses: list[Address] = []
            for i in range(size):
                addresses.append(current_rip + i)

            self.bss_segment[label]["addresses"] = addresses
            Segment_Mapper._write_section_to_memory(
                self.memory, times, number_of_bytes, addresses, current_rip
            )  # BSS is always uninitialized (0)
            current_rip += size
            index += 1
        return current_rip, index

    def bss_format_validation(self, line: list[str], index: int) -> bool:
        """
        Validates the format of a .bss declaration line.
        Accepts either the plain reserve form (<label> <size_spec> <count>,
        e.g. `buffer: resd 5`) or the 'times' form mirroring .data/.rodata
        (<label> times <count> <size_spec> <value>, e.g. `buffer: times 5 dd 0`).
        In the 'times' form, the trailing value token is accepted for
        syntactic symmetry with .data but is never actually used - .bss is
        always zero-initialized regardless of what's written there.

        :param line: full line of code that has a .bss declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        :return: True if the line is a valid .bss declaration, False otherwise
        :rtype: bool
        """
        label: str = line[0].rstrip(":")

        # Check label duplication
        if self._label_in_use(label):
            print(
                f"Variable {label} already declared. Exiting program on a SyntaxError..."
            )
            return False

        # Validates labels name
        elif not Segment_Mapper._valid_variable_name(label):
            print(
                f"INVALID VARIABLE NAME {label} AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        if "times" in line:
            if not self.timed_data_validation(line, "data", "times"):
                print(
                    f"UNSUPPORTED OR INCORRECT 'TIMES' BSS DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
                )
                return False
            return True

        # Checks correct number of components declared
        if len(line) != 3:
            print(
                f"INVALID BSS DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        # Validates size specifier
        elif not Segment_Mapper._valid_size_specifier(line[1], "bss"):
            print(
                f"INVALID BSS SECTION SIZE SPECIFIER AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        # Validates values declared
        elif not self._is_valid_value(line[2]):
            print(
                f"INVALID BSS VALUE DECLARED AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False
        return True

    # ------------------------------
    # section .text related methods
    # ------------------------------

    def _load_text(self) -> None:
        """
        Takes care of .text components (methods labels and constants) parsing as well as validation of the start declaration

        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :type current_rip: Address
        :param index: index to the line of code
        :type index: int
        """
        try:
            index: int = self.skip_to_star()
        except SyntaxError as e:
            print(e)
            sys.exit(ExitCode.NO_START_LABEL)

        self.rip = (
            index + 1
        )  # Set instruction pointer to the line after the start declaration
        self.fetch_labels(index + 2)
        # Exit validation is verified while running

    def skip_to_star(self) -> int:
        """
        Helper to move load_text to the correct start.\n
        Should return the index of the line in the json file where the start is declaration

        :return: Index of the row where start is declared
        :rtype: int
        :raises SyntaxError: if no valid start declaration was found, if the
        """

        index: int = 0
        while index < len(self.memory_list):
            tokens: list[str] = self.memory_list[index]

            # Just for prevention
            if not tokens:
                index += 1
                continue

            if index + 1 < len(self.memory_list):
                idx: int = self.find_start(
                    tokens,
                    self.memory_list[index + 1]
                    if index + 1 < len(self.memory_list)
                    else None,
                )
                match idx:
                    case 0:
                        self.labels[VALID_START] = index
                        return index
                    case 1:
                        self.labels[VALID_START] = index + 1
                        return index + 1
                    case -10:
                        raise SyntaxError(
                            f"Invalid start declaration syntax found. Try removing extra instruction from right after {VALID_START}!"
                        )
                    # Never reached
                    case _:
                        index += 1
            else:
                if (
                    len(tokens) != 2
                    or tokens[0] != "global"
                    or tokens[1] != VALID_START
                ):
                    index += 1
                else:
                    return index
        raise SyntaxError("No valid start declaration was found")

    def find_start(self, line: list[str], next_line: list[str] | None) -> int:
        """
        Validates the existence of a valid start declaration

        :param line: List of words of a line of code where a start declaration is expected
        :type line: list[str]
        :param next_line: List of words of the line of code following the expected start declaration or None if out of bounds
        :type next_line: list[str]
        :return: 0 if a valid start declaration is found, 1 if a valid start declaration was found on the next line,
                 -1 if no global declaration is found, -2 if no valid start declaration is found and -10 if the start declaration was found but was not correct
        :rtype: int
        """

        if line[0] != "global":
            return -1  # Partial error (meaning no global found and possibly wrong line was passed)

        elif len(line) > 1 and line[1] == VALID_START:
            # Extra info on the start declaration that wont be properly parsed
            if len(line) != 2:
                return -10
            return 0

        elif next_line and next_line[0] != VALID_START + ":":
            return 1

        else:
            return -2

    def fetch_labels(self, index: int) -> None:
        """
        Takes care of the label initialization with all labels present in the code passed to the execution.\n
        Also verifies if any of the lines is a constant declaration and redirects the execution to the appropriate method

        :param index: starting line (Must have a global start declaration)
        :type index: int
        """

        while index < len(self.memory_list):
            line: list[str] = self.memory_list[index]
            if Segment_Mapper._is_constant_declaration(line):
                self._load_constant(line, index)

            elif len(line) == 1 and line[0].endswith(":"):
                variable = line[0].strip(":")
                if Segment_Mapper._exists_in_section(variable, self.labels):
                    print(
                        f"Label {variable} is duplicate on line {index}. Exiting program on a SyntaxError..."
                    )
                    sys.exit(ExitCode.DUPLICATE_LABEL)
                elif not Segment_Mapper._valid_variable_name(variable):
                    sys.exit(ExitCode.RESERVED_KEYWORD_VIOLATION)
                else:
                    self.labels[variable] = index
            index += 1

    # ------------------------
    # Constant related methods
    # ------------------------

    def _load_constant(self, line: list[str], index: int) -> None:
        """
        Takes care of constant storing

        :param line: full line of code that has a constant declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        """
        if line[0] == "#define":
            self.load_c_constant(line, index)
            return
        elif not self.is_valid_constant_declaration(line, index):
            sys.exit(ExitCode.CONSTANT_DECLARATION_ERROR)

        # Value getting
        value: int | str
        if Segment_Mapper._has_size_calculation(line):
            variable: str = line[2]
            value = self.get_size_constant_value(variable, index, line[0])
        else:
            value = self.get_constant_value(line[2])

        self.constants[line[0]] = {"line": index, "value": value}

    # ------------------------
    # Constant validation
    # ------------------------

    def load_c_constant(self, line: list[str], index: int) -> None:
        """
        Takes care of constant storing for C-style constants

        :param line: full line of code that has a constant declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        """
        if not self.common_constant_declaration_validation(line, line[1], index):
            sys.exit(ExitCode.CONSTANT_DECLARATION_ERROR)
        elif not self._is_valid_value(line[2]):
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            sys.exit(ExitCode.CONSTANT_DECLARATION_ERROR)
        self.constants[line[1]] = {
            "line": index,
            "value": self.get_constant_value(line[2]),
        }

    # -----------------------------
    # Constant (format) validation
    # -----------------------------

    def is_constant(self, label: str) -> bool:
        """
        Verifies if a given label is a constant already declared

        :param label: label to verify if is a label
        :type label: str
        :return: True if label is a constant, False otherwise
        :rtype: bool
        """
        if label in self.constants:
            return True
        return False

    def common_constant_declaration_validation(
        self, line: list[str], label: str, index: int
    ) -> bool:
        """
        Validates common conditions between c constants and standard constants

        :param line: full line of code that has a constant declaration
        :type line: list[str]
        :param label: name of the constant being declared
        :type label: str
        :param index: number of that line of the code
        :type index: int
        :return: True if all conditions pass, False otherwise
        :rtype: bool
        """
        if len(line) != 3:
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        # Label validation
        elif self._label_in_use(label, include_constants=True):
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Label {label} already in use. Exiting program on a SyntaxError..."
            )
            return False

        elif not Segment_Mapper._valid_variable_name(label):
            print(
                f"INVALID CONSTANT NAME {label} AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False
        return True

    def is_valid_constant_declaration(self, line: list[str], index: int) -> bool:
        """
        Verifies if a standard constant declaration is valid.

        :param line: full line of code that has a constant declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        :return: True if the constant declaration is valid, False otherwise
        :rtype: bool
        """
        # allowed formats:
        # <label> equ/EQU <value>
        # <label> equ/EQU $-<data/rodata label>     # it's important to not leave spaces between $ and -

        if not self.common_constant_declaration_validation(line, line[0], index):
            return False

        elif line[1].lower().rstrip(":") != "equ":
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        elif Segment_Mapper._has_size_calculation(
            line
        ) and not self.valid_size_calculation(line, index):
            return False

        # value verification
        elif not self._is_valid_value(
            line[2]
        ) and not Segment_Mapper._has_size_calculation(line):
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False
        return True

    def valid_size_calculation(self, line: list[str], index: int) -> bool:
        """
        Verifies that the size calculation is valid.

        :param line: full line of code that has a constant declaration
        :type line: list[str]
        :param index: number of that line of the code
        :type index: int
        :return: True if the size calculation is valid, False otherwise
        :rtype: bool
        """
        if not re.match(r"^\$-\w+$", line[2]):
            print(
                f"INVALID CONSTANT DECLARATION AT LINE {index}. Exiting program on a SyntaxError..."
            )
            return False

        label = line[2][2:]  # Extract label after '$-'
        if not (
            Segment_Mapper._exists_in_section(label, self.data_segment)
            or Segment_Mapper._exists_in_section(label, self.rodata_segment)
        ):
            print(
                f"Invalid label used in {line[0]} declaration at line {index}. {label} is not a usable label. Exiting program on a SyntaxError...\n"
            )
            return False
        return True

    # ----------------------------
    # Constant definition getters
    # ----------------------------

    def get_size_constant_value(
        self, variable: str, index: int, label: str
    ) -> int | str:
        """
        Gets the number of addresses used to define the variable used to declare a constant.\n
        Should be used to get the value of size constant declarations

        :param variable: label of a variable to search for
        :type variable: str
        :param index: index of the declaration of the constant
        :type index: int
        :param label: label used to declare the constant
        :type label: str
        :return: number of byte addresses used in the variable declaration
        :rtype: int
        """
        if Segment_Mapper._exists_in_section(variable, self.data_segment):
            return int(self.data_segment[variable]["size"])  # type: ignore  (is always int)
        return int(self.rodata_segment[variable]["size"])  # type: ignore  (is always int)

    def get_constant_value(self, value: str) -> int | str:
        """
        Gets the value of a constant that is not declared using a size calculation of a string.

        :param value: value of the constant to be parsed
        :type value: str
        :return: value of the constant (int or str)
        :rtype: int | str
        """
        try:
            # if is int will pass
            val: int = int(value)
            return val
        except ValueError:  # triggered if not int
            # removes quotation marks and returns
            return value[1:-1]

    # --------------------
    # STACK INITIALIZATION
    # --------------------

    # Stack layout (top to bottom):
    # |_[argument strings]
    # |_[0]
    # |_[argv pointers]
    # |_[0]
    # |_[argc] <--- stack pointer at initialize_stack return

    def _initialize_stack(
        self,
        argvcount: int,
        argv: list[str] | None,
        memory: Data_Memory,
        stack_limit: int,
        stack_start: int = STACK_START,
    ) -> None:
        """
        Initializes the stack with argc and argv values as well as argument strings.

        :param argvcount: argument counter
        :type argvcount: int
        :param argv: vector of argument strings
        :type argv: list[str] | None
        :param memory: Data_Memory object used to hold the program's memory
        :type memory: Data_Memory
        :param stack_limit: maximum value the stack pointer can reach
        :type stack_limit: int
        :param stack_start: initial value of the stack pointer
        :type stack_start: int
        :return: final value of the sack pointer after the initializations
        :rtype: int
        """
        self.registers.write_reg("rsp", stack_start, False)
        # Step 1: push argument strings
        if argv is not None:
            argv_addr: list[int] = self.push_arguments(argv)
            # Step 2: push argument pointers
            for addr in argv_addr:
                self.memory.push(addr.to_bytes(8, "little"))
            # Step 3: push argc
            memory.push((0).to_bytes(8, "little"))
        memory.push(argvcount.to_bytes(8, "little"))
        # Step 4: align the stack and verify its size
        self.align_stack(memory, stack_limit)

    def push_arguments(self, argv: list[str]) -> list[int]:
        """
        Push argument strings into the stack.\n
        Returns list of addresses where each arg begins.

        :param argv: vector of argument strings
        :type argv: list[str]
        :return: list of addresses where each argument string begins
        :rtype: list[int]
        """
        addresses: list[int] = []
        for arg in reversed(argv):
            # Reverses arg_bytes to give the correct push order
            arg_bytes = (arg.encode("utf-8") + b"\x00")[::-1]
            self.memory.push(arg_bytes)
            addresses.append(self.registers.read_reg("rsp"))
        self.memory.push(b"\x00")
        return addresses

    def align_stack(self, memory: Data_Memory, stack_limit: int) -> None:
        """
        Align stack pointer to 16 bits.

        :param memory: Data_Memory object used to hold the program's memory
        :type memory: Data_Memory
        :param stack_limit: maximum value the stack pointer can reach
        :type stack_limit: int
        """
        rsp: int = self.registers.read_reg("rsp")
        misalignment: int = rsp % 16
        if misalignment != 0:
            rsp -= misalignment
            try:
                self.check_stack_limit(rsp, stack_limit)
                self.registers.write_reg("rsp", rsp, False)
            except OverflowError as e:
                print(e)
                sys.exit(ExitCode.STACK_OVERFLOW)

    def check_stack_limit(self, rsp: int, stack_limit: int) -> None:
        """
        Check if the current stack pointer is below the minimum allowed.\n
        Raises an exception if stack overflow occurs.

        :param memory: Data_Memory object used to hold the program's memory
        :type memory: Data_Memory
        :param stack_limit: maximum value the stack pointer can reach
        :type stack_limit: int
        :raises OverflowError: if stack overflow occurs
        """
        if rsp < stack_limit:
            raise OverflowError(
                f"Stack overflow: stack pointer {hex(rsp)} "
                f"below minimum allowed {hex(stack_limit)}"
            )

    # ----------------
    # Helper methods
    # ----------------

    def _define_segment(
        self, section: str, label: str, size: int, current_rip: Address
    ) -> list[Address]:
        """
        Handles entry creation on the correct segment handler matching the section inputted an
        """
        addresses = list(range(current_rip, current_rip + size))
        segment = self.data_segment if section == "data" else self.rodata_segment
        segment[label] = {"size": size, "addresses": addresses}
        return addresses

    def _label_in_use(self, label: str, include_constants: bool = False) -> bool:
        """
        Checks whether a label is already declared in any memory segment
        (.data, .rodata, .bss), optionally also checking constants.

        :param label: label to check for existing declarations
        :type label: str
        :param include_constants: whether to also check the constants map
        :type include_constants: bool
        :return: True if the label is already in use, False otherwise
        :rtype: bool
        """
        in_use = (
            Segment_Mapper._exists_in_section(label, self.data_segment)
            or Segment_Mapper._exists_in_section(label, self.rodata_segment)
            or Segment_Mapper._exists_in_section(label, self.bss_segment)
        )
        if include_constants:
            in_use = in_use or Segment_Mapper._exists_in_section(label, self.constants)
        return in_use

    # ----------------
    # STATIC HELPERS
    # ----------------

    @staticmethod
    def _is_constant_declaration(line: list[str]) -> bool:
        """
        Verifies if a given line declares a constant

        :param line: full line of code in execution
        :type line: list[str]
        :return: True if the line defines a constant, False if it doesn't
        :rtype: bool
        """

        stripped = [tok.rstrip(":") for tok in line]
        return "equ" in stripped or "EQU" in stripped or line[0] == "#define"

    @staticmethod
    def _has_size_calculation(line: list[str]) -> bool:
        """
        Verifies if a size calculation is present in a constant declaration line

        :param line: full line of code in execution
        :type line: list[str]
        :return: True if the line has a size calculation formula, False if it doesn't
        :rtype: bool
        """
        for kword in line:
            if "$" in kword:
                return True
        return False

    @staticmethod
    def _exists_in_section(
        variable: str,
        section: DataSectionInfo | BssSectionInfo | LabelMap | ConstantMap,
    ) -> bool:
        """
        Verifies if a variable label matches one existing in a given section

        :param variable: label of a variable to search for
        :type variable: str
        :param section: section where to look for
        :type section: DataSectionInfo | BssSectionInfo | LabelMap | ConstantMap
        :return: true if a match was found, false if it wasn't
        :rtype: bool
        """
        return variable in section  # type: ignore

    @staticmethod
    def _valid_size_specifier(specifier: str, section: str) -> bool:
        """
        Validates if a size specifier is valid for a given section.

        :param specifier: size specifier string for a given section
        :type specifier: str
        :param section: section name where the size specifier is used
        :type section: str
        :return: True if the size specifier is valid, False otherwise
        :rtype: bool
        """
        if specifier not in SIZE_DIRECTIVES:
            return False
        is_initialized = SIZE_DIRECTIVES[specifier][1]
        return is_initialized if section in ("data", "rodata") else not is_initialized

    @staticmethod
    def _write_section_to_memory(
        memory: Data_Memory,
        times: int,
        specifier: int,
        addresses: list[Address],
        current_rip: Address,
        value: int | str = 0,
    ) -> None:
        """
        Writes a section to memory with a given initial value.

        :param memory: Data_Memory object used to hold the program's memory
        :type memory: Data_Memory
        :param times: number of times to write the section
        :type times: int
        :param specifier: size specifier for the section (1,2,4,8)
        :type specifier: int
        :param addresses: list of addresses where to write the section
        :type addresses: list[Address]
        :param current_rip: pointer to the Address in use to store values in the Data_memory object
        :type current_rip: Address
        :param value: initial value to write into the section
        :type value: int | str
        """
        byte_value: bytes
        try:
            # base=0 makes int() auto-detect 0x/0o/0b prefixes (and still
            # parses plain decimal strings normally) - plain int(value)
            # raises ValueError on a hex literal like "0x0a", which was
            # silently falling through to the string-encoding fallback
            # below and writing the literal characters '0','x','0','a'
            # instead of the intended single byte 0x0a. int(x, 0) requires
            # a str, not an int, hence the isinstance check (value defaults
            # to the int 0 for BSS's always-uninitialized writes).
            parsed = value if isinstance(value, int) else int(value, 0)
            byte_value = parsed.to_bytes(specifier, "little")
            for i in range(times):
                memory.write_bytes(current_rip + i * specifier, byte_value, specifier)
        except ValueError:
            byte_value = (str(value).encode())[:specifier].ljust(specifier, b"\x00")
            for i in range(times):
                memory.write_bytes(current_rip + i * specifier, byte_value, specifier)

    @staticmethod
    def _valid_variable_name(name: str) -> bool:
        """
        Validates if a variable name is valid.

        :param name: variable name to validate
        :type name: str
        :param index: number of that line of the code
        :type index: int
        :return: True if the variable name is valid, False otherwise
        :rtype: bool
        """
        name = name.strip(":")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) or re.fullmatch(
            rf"(?:{_RESERVED_KEYWORDS_PATTERN})", name, re.IGNORECASE
        ):
            return False
        return True

    @staticmethod
    def _is_numeric(s: str) -> bool:
        """
        Helper that verifies if a given str is a numerical value

        :param s: String to check the condition
        :type s: str
        :return: True if s is a numerical value, False otherwise
        :rtype: bool
        """
        try:
            if s.lower().startswith("0x"):
                int(s, 16)
            else:
                int(s)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_valid_value(val: str) -> bool:
        """
        Helper that verifies if a given value to be used in initialization of a variable is valid

        :param s: String to check the condition
        :type s: str
        :return: True if s is a numerical value, False otherwise
        :rtype: bool
        """
        if Segment_Mapper._is_numeric(val):
            return True

        # Check for char/string constants
        if len(val) >= 3 and (
            (val.startswith("'") and val.endswith("'"))
            or (val.startswith('"') and val.endswith('"'))
        ):
            return True
        return False
