import os
import sys
import threading

from interpreter.exit_codes import ExitCode

from ..bridges.data_memory import Data_Memory
from ..bridges.register_manager import Registers_Interface
from ..bridges.syscall import Syscall
from ..functional_units.alu import ALU
from ..functional_units.data_path import Data_Path
from ..functional_units.fpu import FPU
from ..helpers.my_types import (
    FU,
    BssSectionInfo,
    ConstantMap,
    DataSectionInfo,
    LabelMap,
)
from .instruction_parser import Instruction_Parser, Operand
from .patter_matching_helpers import INSTRUCTIONS
from .segment_mapper import Segment_Mapper


class CPUException(Exception):
    """Base class for errors raised during emulated execution."""
    def __init__(self, message: str):
        super().__init__(message)


_count = os.cpu_count()
TOTAL_THREADS: int = _count if _count != None else 0


class Control_Unit:
    """
    Control Unit class responsible for fetching instructions, decoding them, validating operands, and dispatching execution to the appropriate functional units (CPU, Data Path, ALU, FPU).
    It also manages the state of the CPU, including registers, flags, and the instruction pointer (RIP).
    The Control Unit interacts with the Data Memory, Segment Mapper, and the functional units to execute instructions and update the CPU state accordingly.

    Attributes:
        # TO DO
    """

    __slots__ = [
        "alu",
        "bss_section",
        "constants",
        "current_fu",
        "current_instruction",
        "data_path",
        "data_section",
        "finished",
        "fpu",
        "instruction_parser",
        "labels",
        "memory",
        "op1",
        "op2",
        "registers",
        "rip",
        "rodata_section",
        "syscall",
        "text_section",
    ]

    def __init__(self, loader: Segment_Mapper, debugging: bool = False) -> None:
        # Initialize Control Unit with memory, segment mapper, functional units and registers (general purpose, fpu and flags)
        self.registers: Registers_Interface = loader.registers
        self.memory: Data_Memory = loader.memory
        self.data_path: Data_Path = Data_Path(
            self.registers, self.memory, loader.labels
        )
        self.syscall: Syscall = Syscall(self.registers, self.memory)
        self.alu: ALU = ALU(self.registers, self.memory)
        self.fpu: FPU = FPU(self.registers, self.memory)

        # Useful registers and flags attributes
        self.rip: int = (
            loader.rip
        )  # Instruction Pointer initialized from Segment Mapper
        # Turns debugging on
        if debugging:
            self.registers.Exch_trap_flag()

        # Parsed sections from segment_mapper
        self.text_section: list[list[str]] = loader.memory_list
        self.rodata_section: DataSectionInfo = loader.rodata_segment
        self.data_section: DataSectionInfo = loader.data_segment
        self.bss_section: BssSectionInfo = loader.bss_segment
        self.labels: LabelMap = loader.labels
        self.constants: ConstantMap = loader.constants

        # Helper instances for the execution
        self.finished: bool = False
        self.current_fu: str = "cpu"  # (cpu/data_path/alu/fpu)
        self.current_instruction: str = ""
        self.op1: Operand = Operand()
        self.op2: Operand = Operand()
        self.instruction_parser: Instruction_Parser = Instruction_Parser(
            self.op1,
            self.op2,
            self.labels,
            self.constants,
            self.rodata_section,
            self.data_section,
            self.bss_section,
            self.registers,
        )

    def __del__(self):
        # Classes with a __del__ method implemented that dynamically allocate space on the heap
        self.alu = None  # type: ignore
        self.fpu = None  # type: ignore
        self.registers.clean()
        self.memory.clean()

    # ------------------
    # Callable methods
    # ------------------

    def run(self) -> ExitCode:
        """
        Runs the interpreter
        """
        self.rip += 1
        # Improve this loop to enable debugging features
        while not self.finished:
            # Debugging feature: Trap flag verification. If the trap flag is raised, execute the trap flag command and halt execution before executing the instruction in the current line.
            if self.registers.read_trap_flag() == 1:
                # Should allow for gdb command actions
                self._execute_state_command()
            try:
                self._step()
            except CPUException as e:   # Debugging Exception
                print(f"CPU Exception: {e} at line {self.rip + 1}.")
                self.finished = True
            except SystemExit as e:
                print(f"Exit due to {e} at line {self.rip + 1}.")
                return e.code  # type: ignore
        return ExitCode.SUCCESS

    def get_state(self, section: str, num_rep: int = 16) -> dict[str, int | str]:
        """
        Returns a snapshot of observable CPU/memory state as a dict of
        name -> current value, for the given named section.\n
        This is the return-value counterpart to print_section/
        execute_state_command's inspection commands: same underlying reads,
        same threaded fetch for memory sections, but handed back as data
        instead of printed to stdout — useful for tests or any caller that
        wants to assert on or further process the state rather than just
        display it.

        :param section: Which piece of state to fetch: 'all', 'data', 'rodata', 'bss', or 'registers'
        :type section: str
        :param num_rep: Numerical Representation to give values in - 10 (decimal, default), 2 (binary), 8 (octal), or 16 (hexadecimal). Non-decimal bases return Python-style prefixed strings (e.g. "0x2a"); negative values are shown as their two's-complement bit pattern at the value's actual width, not a signed "-0x.." string.
        :type num_rep: int
        :return: Mapping of variable/register name to its current value - a plain int for decimal, or a base-prefixed string for binary/octal/hexadecimal
        :rtype: dict[str, int | str]
        :raises ValueError: If section is not one of the recognized names, or num_rep is not one of 2, 8, 10, 16
        """
        if num_rep not in (2, 8, 10, 16):
            raise ValueError(
                f"UNSUPPORTED NUMERICAL REPRESENTATION '{num_rep}'. Expected one of: 2, 8, 10, 16."
            )

        if section == "all":
            data = self._get_memory_section_state(self.data_section, num_rep)
            rodata = self._get_memory_section_state(self.rodata_section, num_rep)
            bss = self._get_memory_section_state(self.bss_section, num_rep)
            registers = self._get_registers_state(num_rep)
            return Control_Unit._merge_list([rodata, data, bss, registers])  # type: ignore

        elif section == "data":
            return self._get_memory_section_state(self.data_section, num_rep)
        elif section == "rodata":
            return self._get_memory_section_state(self.rodata_section, num_rep)
        elif section == "bss":
            return self._get_memory_section_state(self.bss_section, num_rep)
        elif section == "registers":
            return self._get_registers_state(num_rep)
        else:
            raise ValueError(f"UNKNOWN SECTION '{section}' REQUESTED FOR get_state.")

    # ---------------------------------
    # Cycle execution methods
    # ---------------------------------

    def _step(self) -> None:
        """Method to execute a singe instruction"""
        try:
            # 1. Gets the instruction, operands and functional unit in use and verifies it's compatibility it the operator count of the instruction
            if self.rip < len(self.text_section):
                if self._fetch():
                    self._execute(self.current_instruction)
            else:
                print(
                    "NO VALID EXIT WAS VALID TO THE PROGRAM.\n Forcing program's exit..."
                )
                sys.exit(ExitCode.NO_EXIT_FOUND)
            self.rip += 1
        except ValueError as e:
            print(e)
            sys.exit(ExitCode.INVALID_OR_UNSUPPORTED_INSTRUCTION)

    # -------------------------------
    # Main Logic Implementation
    # -------------------------------

    def _fetch(self) -> bool:
        """
        Fetches the current instruction and its operands from the text section based on the instruction pointer (RIP).\n
        Sets the current instruction and current functional unit in use and validates and sets the operands and its size.
        Raises a ValueError if the instruction is invalid or if the operands are invalid.

        :return: True if an instruction was found, False if a label was found
        :rtype: bool
        :raises ValueError: If the instruction is invalid or if the operands are invalid.
        """
        line: list[str] = self.text_section[self.rip]

        # Means parsing failed to filter out empty lines and potentially comments too
        if not line:
            sys.exit(ExitCode.SOFTWARE_ERROR)

        # Verifies if the line is a label declaration and skips it if so
        if len(line) == 1 and line[0].strip(":") in self.labels:
            return False

        # Verifies if the line is an instruction and sets the instruction, f.u. in use and operand info needed for execution (size, type, value, address)
        elif self._is_valid_instruction(line[0]):
            self.current_instruction = line[0]
            self.instruction_parser.line = line
            self.instruction_parser.rip = self.rip
            try:
                self.instruction_parser.parse()
            except SyntaxError as e:
                print(e)
                sys.exit(ExitCode.INVALID_INSTRUCTION_SYNTAX)
            except ValueError as e:
                print(e)
                sys.exit(ExitCode.INVALID_INSTRUCTION_SYNTAX)

            # Verifies if the number of operands registered are compatible with the instructions documentation in the valid_instructions json file
            if self._valid_operand_count():
                return True
            else:
                # If incompatible reset all info to a Null value and raise an exception
                self.op1.clear()
                self.op2.clear()
                print(
                    f"INVALID OPERAND COUNT FOR INSTRUCTION AT LINE {self.rip}. Exiting program..."
                )
                sys.exit(ExitCode.INVALID_INSTRUCTION_SYNTAX)

        # If the instruction wasn't found, raise an exception
        else:
            raise ValueError(f"INVALID INSTRUCTION AT LINE {self.rip}!")

    def _execute(self, instruction: str) -> None:
        """
        Transfers executions to the class with the functional unit responsible for the instruction
        in the current instruction in this class's respective instance
        and retrieves the result of the operation if any and the flags state that resulted from the operation.

        """
        if self.current_fu == "cpu":
            # Calls syscall decoder methods
            # cpu should always just refer to the syscall operation
            error_code = self.syscall.syscall()
            if error_code == -1:
                sys.exit(ExitCode.INVALID_SYSCALL)
            elif error_code == 1:
                self.finished = True
        else:
            current_fu: FU = self._get_current_fu()
            if self.current_fu == "data_path" and instruction == "call":
                current_fu.load_rip(self.rip)  # type: ignore
            current_fu.load_values(instruction, self.op1, self.op2)
            try:
                ret = current_fu.execute()  # type: ignore ONLY FOR JUMPS, CALL'S AND RET
                self.rip = ret if ret != None else self.rip
            except RuntimeError:
                sys.exit(ExitCode.INVALID_INSTRUCTION_SYNTAX)
            except ZeroDivisionError:
                sys.exit(ExitCode.BY_0_DIVISION_ERROR)
            except NameError:
                sys.exit(ExitCode.INVALID_OR_UNSUPPORTED_INSTRUCTION)

    # ----------------------------------------
    # Execution Helpers
    # ----------------------------------------

    def _is_valid_instruction(self, instruction: str) -> bool:
        """
        Verifies if a given instruction is supported by the program and if so sets the current functional unit in use and the number of operands expected by the instruction parser.\n
        Enables syscall's and function calls methods taken care by this class.

        :param instruction: Instruction in verification
        :type instruction: str
        :return: True if the instruction is present in the valid_instructions.json file
        :rtype: bool
        """
        if instruction == "syscall":
            self.current_fu = "cpu"
            return True

        for functional_units in INSTRUCTIONS:
            if instruction in INSTRUCTIONS[functional_units]:
                self.current_fu = functional_units
                self.instruction_parser.expected_op_count = INSTRUCTIONS[
                    functional_units
                ][instruction]
                return True

        return False

    def _get_current_fu(self) -> FU:
        """
        Returns the object to the current functional unit in use

        :return: Functional unit object at use
        :rtype: FU (Type Alias for all functional unit types)
        """
        # 'cpu' is safely ignored as at this point it would already be taken care of
        if self.current_fu == "data_path":
            return self.data_path
        elif self.current_fu == "alu":
            return self.alu
        elif self.current_fu == "fpu":
            return self.fpu
        else:
            raise ValueError("NO FUNCTIONAL UNIT FOUND.\n Exiting program...")

    def _valid_operand_count(self) -> bool:
        """
        Verifies if the current operand count is valid for the current instruction

        :return: True if the current operand count is valid for the current instruction
        :rtype: bool
        """
        return INSTRUCTIONS[self.current_fu][self.current_instruction] == (
            self.op1.is_valid() + self.op2.is_valid()
        )

    # -------------------
    # DEBUGGING METHODS
    # -------------------

    def _execute_state_command(self) -> None:
        """
        Cyclically asks for user input to execute commands to print the state of the program in execution.\n
        Commands are:\n
        - 'registers': prints the state of the registers
        - 'memory': prints the state of the memory
        - 'data': prints the state of the data section
        - 'rodata': prints the state of the rodata section
        - 'bss': prints the state of the bss section
        - 'constants': prints the state of the constants declared
        - 'rip': prints the current value of the rip register
        - 'fu': prints the current functional unit in use
        - 'help': prints the list of commands available
        - 'step' : executes the instruction at the current rip and updates the state of the program accordingly (to be used to execute step by step)
        - 'exit': exits the program and stops execution
        If an invalid command is given it will print an error message and ask for a new command.
        """
        while True:  # Transform into a case switch
            command: str = input(
                "Enter a command to print the state of the program or 'help' to see the list of commands available: "
            )
            if command == "registers":
                print(self.registers)

            elif command == "memory":
                print("\n--//--\ndata section:\n")
                self._print_section(self.data_section)
                print("\n--//--\nrodata section:\n")
                self._print_section(self.rodata_section)
                print("\n--//--\nbss section:\n")
                self._print_section(self.bss_section)
                print("\n--//--\n")

            elif command == "data":
                print("\n--//--\ndata section:\n")
                self._print_section(self.data_section)
                print("\n--//--\n")

            elif command == "rodata":
                print("\n--//--\nrodata section:\n")
                self._print_section(self.rodata_section)
                print("\n--//--\n")

            elif command == "bss":
                print("\n--//--\nbss section:\n")
                self._print_section(self.bss_section)
                print("\n--//--\n")

            elif command == "rip":
                print("\n--//--\n")
                print(f"Current value of rip: {self.rip}")
                print("\n--//--\n")

            elif command == "fu":
                print("\n--//--\n")
                print(f"Current functional unit in use: {self.current_fu}")
                print("\n--//--\n")

            elif command == "help":
                print("\n--//--\n")
                print(
                    "List of commands available:\n- 'registers': prints the state of the registers\n- 'memory': prints the state of the memory\n- 'data': prints the state of the data section\n- 'rodata': prints the state of the rodata section\n- 'bss': prints the state of the bss section\n- 'rip': prints the current value of the rip register\n- 'fu': prints the current functional unit in use\n- 'help': prints this list of commands available\n- 'step': steps into the next instruction in the execution\n- 'continue': continues with the normal execution exiting debug mode\n- 'exit': exits the program and stops execution"
                )
                print("\n--//--\n")

            elif command == "step":
                return

            elif command == "run":
                self.registers.Exch_trap_flag()
                return

            elif command == "exit":
                print("Exiting program and stopping execution...")
                sys.exit(0)
            else:
                print(
                    "Invalid command! Enter 'help' to see the list of commands available."
                )

    def _print_section(self, section: DataSectionInfo | BssSectionInfo) -> None:
        """
        Prints every allocated variable in the given program section (data,
        rodata, or bss) along with its current value, read from simulated
        memory and interpreted as a signed little-endian integer.\n
        Reads are distributed across up to TOTAL_THREADS worker threads,
        each responsible for an equal-sized chunk of the section's variable
        names, so large sections are fetched concurrently rather than one
        variable at a time. Printing itself is deferred until every thread
        has finished, so output for different variables never interleaves
        and is always printed in the section's original declaration order.

        Section schema, per variable:
            {
                "var_name": {
                    "size": <number of bytes allocated>,
                    "addresses": [<byte address>, ...]
                }
            }

        :param section: The program section to print (data_section, rodata_section, or bss_section)
        :type section: DataSectionInfo | BssSectionInfo
        :return: None
        :rtype: None
        """
        var_names: list[str] = list(section.keys())

        if not var_names:
            print("(empty section)")
            return

        for name, value in self._fetch_section_values(section, var_names, 16):
            print(f"{name}: {value}")

    # ----------------------------------------
    # get_state / print_section helpers
    # ----------------------------------------

    @staticmethod
    def _merge_list(list: list[dict[str, int]]) -> dict[str, int]:
        """
        Joins all sections passed to the list of section. Called by 'get_state' on 'all' value of section\n
        Should return the total state of the process

        :param list: List of dictionaries depicting the state of each section of the process's information
        :type list: list[dict[str, int]]
        :return: Complete state of the process
        :rtype: dict{str, int}
        """
        merged = {}
        for section in list:
            if section != None:  # type: ignore
                merged.update(section)  # type: ignore
        return merged  # type: ignore

    @staticmethod
    def _format_value(value: int, size_bytes: int, num_rep: int) -> int | str:
        """
        Formats a signed integer value into the requested numeric
        representation.\n
        Decimal (10) returns the value unchanged, as a plain Python int.
        Every other base (2, 8, 16) returns a string with the
        corresponding Python-style prefix ("0b", "0o", "0x"). Negative
        values are converted to their two's-complement bit pattern at
        the value's actual bit width (size_bytes * 8) before formatting,
        matching how the value is genuinely stored in memory/a register,
        rather than showing a signed "-0x.." string.

        :param value: The signed value to format (as returned by read_reg / a memory read)
        :type value: int
        :param size_bytes: The value's width in bytes (e.g. 8 for a 64-bit register), used to compute its two's-complement pattern when negative
        :type size_bytes: int
        :param num_rep: Target base - 10 (decimal), 2 (binary), 8 (octal), or 16 (hexadecimal)
        :type num_rep: int
        :return: The value unchanged (decimal) or a base-prefixed string (binary/octal/hex)
        :rtype: int | str
        :raises ValueError: If num_rep is not one of 2, 8, 10, 16
        """
        if num_rep == 10:
            return value

        # Two's-complement pattern at the value's real bit width, so a
        # negative value's non-decimal representation matches what's
        # actually stored, e.g. -100 (int8) -> 0x9c, not -0x64.
        unsigned_value = value & ((1 << (size_bytes * 8)) - 1) if value < 0 else value

        if num_rep == 16:
            return f"0x{unsigned_value:x}"
        elif num_rep == 8:
            return f"0o{unsigned_value:o}"
        elif num_rep == 2:
            return f"0b{unsigned_value:b}"
        else:
            raise ValueError(
                f"UNSUPPORTED NUMERICAL REPRESENTATION '{num_rep}'. Expected one of: 2, 8, 10, 16."
            )

    def _get_memory_section_state(
        self, section: DataSectionInfo | BssSectionInfo, num_rep: int
    ) -> dict[str, int | str]:
        """
        Threaded-fetch counterpart to print_section, returning the section's
        variable values as a dict instead of printing them.

        :param section: The program section to read (data_section, rodata_section, or bss_section)
        :type section: DataSectionInfo | BssSectionInfo
        :param num_rep: Numerical Representation type to give values in (10 for decimal, 8 for octal, 16 for hexadecimal)
        :type num_rep: int
        :return: Mapping of variable name to its current signed value
        :rtype: dict[str, int]
        """
        var_names: list[str] = list(section.keys())

        if not var_names:
            return {}

        return {
            name: value
            for name, value in self._fetch_section_values(section, var_names, num_rep)
        }

    def _get_registers_state(self, num_rep: int) -> dict[str, int | str]:
        """
        Returns every general-purpose register's current value plus the
        individual status flags, as a single flat dict.\n
        Register values are read via Registers_Interface.read_reg, which
        already applies each register's current signed/unsigned
        interpretation (2's complement correction).

        :param num_rep: Numerical Representation type to give values in (10 for decimal, 8 for octal, 16 for hexadecimal)
        :type num_rep: int
        :return: Mapping of register/flag name to its current value
        :rtype: dict[str, int]
        """
        state: dict[str, int | str] = {}
        for reg_name in Registers_Interface.REGISTERS_MAP:
            state[reg_name] = Control_Unit._format_value(
                self.registers.read_reg(reg_name), 8, num_rep
            )

        state["ZF"] = Control_Unit._format_value(
            int(self.registers.read_zero()), 1, num_rep
        )
        state["CF"] = Control_Unit._format_value(
            int(self.registers.read_carry()), 1, num_rep
        )
        state["SF"] = Control_Unit._format_value(
            int(self.registers.read_sign()), 1, num_rep
        )
        state["OF"] = Control_Unit._format_value(
            int(self.registers.read_overflow()), 1, num_rep
        )
        state["PF"] = Control_Unit._format_value(
            int(self.registers.read_parity()), 1, num_rep
        )
        state["TF"] = Control_Unit._format_value(
            int(self.registers.read_trap_flag()), 1, num_rep
        )

        return state

    def _fetch_section_values(
        self,
        section: DataSectionInfo | BssSectionInfo,
        var_names: list[str],
        num_rep: int,
    ) -> list[tuple[str, int | str]]:
        """
        Reads every variable in var_names from simulated memory concurrently
        across up to TOTAL_THREADS worker threads, each responsible for an
        equal-sized chunk of the list. Results are returned in the section's
        original order regardless of which thread finishes first.\n
        Shared by print_section (prints the result) and
        _get_memory_section_state (returns it as a dict).

        :param section: The program section to read from
        :type section: DataSectionInfo | BssSectionInfo
        :param var_names: Ordered list of variable names to fetch (section.keys())
        :type var_names: list[str]
        :param num_rep: Numerical Representation type to give values in (2, 8, 10, or 16)
        :type num_rep: int
        :return: Ordered list of (name, formatted_value) pairs, in var_names order
        :rtype: list[tuple[str, int | str]]
        """
        # One slot per variable, indexed by position in var_names. Each
        # thread only ever writes to its own disjoint slice, so no lock is
        # needed, and the final pass preserves the section's original
        # order regardless of which thread finishes first.
        results: list[tuple[str, int | str] | None] = [None] * len(var_names)

        # At least one thread always runs, even if TOTAL_THREADS resolved to 0
        thread_count: int = max(1, TOTAL_THREADS)
        # Never use more threads than there are variables to read.
        thread_count = min(thread_count, len(var_names))

        chunk_size = (
            len(var_names) + thread_count - 1
        ) // thread_count  # ceil division

        def _fetch_elems(start: int, end: int) -> None:
            for i in range(start, end):
                name = var_names[i]
                info = section[name]
                size: int = info["size"]  # type: ignore
                base_addr: int = info["addresses"][0]  # type: ignore

                data: bytes = self.memory.read_bytes(base_addr, size)  # type: ignore
                value: int = int.from_bytes(data, byteorder="little", signed=True)

                results[i] = (name, Control_Unit._format_value(value, size, num_rep))

        threads: list[threading.Thread] = []
        for t in range(thread_count):
            start = t * chunk_size
            end = min(start + chunk_size, len(var_names))
            if start >= end:
                break  # fewer variables than thread_count after ceil division

            thread = threading.Thread(target=_fetch_elems, args=(start, end))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        for entry in results:
            assert entry is not None  # every slot is written by exactly one thread

        return results  # type: ignore[return-value]
