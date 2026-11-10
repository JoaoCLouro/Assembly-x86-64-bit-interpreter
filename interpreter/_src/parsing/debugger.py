"""
Debugging utilities for the parser.
"""

from collections.abc import Mapping
import re
import sys
from enum import Enum

from interpreter._src.parsing.control_unit import Control_Unit
from interpreter._src.parsing.patter_matching_helpers import REGISTER_PATTERN


class InvalidCommandError(Exception):
    """Raised when an invalid command is entered in the debugger."""


class Command(Enum):
    """GDB-like Debugger commands."""

    RUN = "run"
    STEP = "step instruction"
    CONTINUE = "continue"
    BREAK = "break"
    DELETE = "delete"
    INFO_BREAKPOINTS = "info breakpoints"
    INFO_REGISTERS = "info registers"
    EXAMINE = "x"
    RADIX = "radix"
    HELP = "help"
    QUIT = "quit"


# "info" is a prefix command with its own subcommands, so it is matched as a
# sentinel next to the Command members (this makes "in" / "inf" work).
INFO = "info"

# Exact aliases, checked before prefix matching so "s" or "c" are never ambiguous.
ALIASES: dict[str, Command | str] = {
    "r": Command.RUN,
    "s": Command.STEP,
    "si": Command.STEP,
    "stepi": Command.STEP,
    "c": Command.CONTINUE,
    "b": Command.BREAK,
    "d": Command.DELETE,
    "i": INFO,
    "h": Command.HELP,
    "q": Command.QUIT,
    "exit": Command.QUIT,
}

# Subcommands of "info", also matched by unique prefix.
INFO_SUBCOMMANDS: dict[str, Command] = {
    "registers": Command.INFO_REGISTERS,
    "breakpoints": Command.INFO_BREAKPOINTS,
}
INFO_ALIASES: dict[str, Command] = {
    "r": Command.INFO_REGISTERS,
    "reg": Command.INFO_REGISTERS,
    "b": Command.INFO_BREAKPOINTS,
}

# x/NFU: N = count, F = format, U = unit size (GDB letters).
UNIT_SIZES = {"b": 1, "h": 2, "w": 4, "g": 8}
FORMATS = {"x", "d", "u"}
EXAMINE_SPEC = re.compile(r"(\d*)([bhwgxdu]*)")

# Readable state that is not a general-purpose register: rip lives on the
# Control_Unit, the single flags come from get_state("registers"), and eflags
# is the whole flags register from Registers_Interface.read_flags().
EXTRA_REGISTERS = {"rip", "eflags", "zf", "cf", "sf", "of", "pf", "tf"}

# Numerical representations supported by Control_Unit.get_state, by name or number.
RADIX_NAMES = {
    "bin": 2, "binary": 2,
    "oct": 8, "octal": 8,
    "dec": 10, "decimal": 10,
    "hex": 16, "hexadecimal": 16,
}
VALID_RADIXES = (2, 8, 10, 16)


class ExecutionCommand:
    """
    A validated debugger command, ready to be executed.

    After construction, only the fields relevant to the command are set:
        - BREAK / DELETE:    `line`
        - INFO_REGISTERS:    `register` (None means "all registers")
        - EXAMINE:           `count`, `fmt`, `unit`, and the address as either
                             `address` (a number) or `address_register`
                             (a register name, resolved when executed)
    """

    def __init__(self, command: Command, args: list[str]):
        self.command = command
        self.line: int | None = None
        self.register: str | None = None
        self.address: int | None = None
        self.address_register: str | None = None
        self.count: int = 1
        self.fmt: str = "x"
        self.unit: int = 8
        self.radix: int | None = None  # RADIX only; None means "show current"
        self._match_command_args(command, args or [])

    def _match_command_args(self, command: Command, args: list[str]):
        """
        Validate the arguments for `command` and store them on this object.

        For EXAMINE, `args` is [spec, address] where `spec` is the text after
        the slash in "x/4gx" (empty string for a bare "x").

        :raises InvalidCommandError: on missing, extra, or malformed arguments.
        """
        match command:
            case (
                Command.RUN
                | Command.CONTINUE
                | Command.HELP
                | Command.QUIT
                | Command.INFO_BREAKPOINTS
            ):
                if args:
                    raise InvalidCommandError(
                        f"'{command.value}' takes no arguments."
                    )

            case Command.STEP:
                if args not in ([], ["instruction"]):
                    raise InvalidCommandError("Usage: step instruction")

            case Command.BREAK | Command.DELETE:
                if len(args) != 1:
                    raise InvalidCommandError(f"Usage: {command.value} LINE_NUMBER")
                self.line = self._parse_line(args[0])

            case Command.INFO_REGISTERS:
                if len(args) > 1:
                    raise InvalidCommandError("Usage: info registers [REGISTER]")
                if args:
                    self.register = self._parse_register(args[0])

            case Command.RADIX:
                if len(args) > 1:
                    raise InvalidCommandError("Usage: radix [2|8|10|16|bin|oct|dec|hex]")
                if args:
                    self.radix = self._parse_radix(args[0])

            case Command.EXAMINE:
                if len(args) != 2:
                    raise InvalidCommandError(
                        "Usage: x/NFU ADDRESS  (e.g. x/4gx $rsp, x/2dw 0x1000)"
                    )
                self._parse_examine_spec(args[0])
                self._parse_address(args[1])

            case _:
                print(
                    "[DEBUG]: Clause not exhaustive enough! Report to the developers."
                )

    # --- Argument helpers ---

    @staticmethod
    def _parse_line(token: str) -> int:
        # isascii() matters: "²".isdigit() is True but int("²") raises
        if not (token.isascii() and token.isdigit()) or int(token) < 1:
            raise InvalidCommandError(
                f"Line number must be a positive integer, got '{token}'."
            )
        return int(token)

    @staticmethod
    def _parse_register(token: str) -> str:
        name = token.lstrip("$").lower()
        if name not in EXTRA_REGISTERS and not re.fullmatch(REGISTER_PATTERN, name):
            raise InvalidCommandError(f"Unknown register: '{name}'.")
        return name

    @staticmethod
    def _parse_radix(token: str) -> int:
        is_number = token.isascii() and token.isdigit()
        base = RADIX_NAMES.get(token, int(token) if is_number else None)
        if base not in VALID_RADIXES:
            raise InvalidCommandError(
                f"Unsupported radix '{token}'. Use 2, 8, 10, 16 or bin, oct, dec, hex."
            )
        return base

    def _parse_examine_spec(self, spec: str):
        m = EXAMINE_SPEC.fullmatch(spec)
        if not m:
            raise InvalidCommandError(
                f"Invalid format '/{spec}'. Use /NFU: count, format (x d u), "
                "unit (b h w g)."
            )
        if m.group(1):
            self.count = int(m.group(1))
            if self.count < 1:
                raise InvalidCommandError("Count must be at least 1.")
        for ch in m.group(2):
            if ch in UNIT_SIZES:
                self.unit = UNIT_SIZES[ch]
            else:
                self.fmt = ch

    def _parse_address(self, token: str):
        if token.startswith("$"):
            self.address_register = self._parse_register(token)
            return
        try:
            value = int(token, 0)  # accepts 0x1000 and 4096
        except ValueError:
            raise InvalidCommandError(f"Invalid address: '{token}'.")
        if value < 0:
            raise InvalidCommandError("Address cannot be negative.")
        self.address = value

    def __repr__(self) -> str:
        fields = {k: v for k, v in vars(self).items() if k != "command" and v is not None}
        return f"ExecutionCommand({self.command.name}, {fields})"


class Debugger:
    """
    A simple debugger for the parser.

    Main Fixtures:
        - GDB like commands for stepping through the parsing process.
        - Logging of parsing events and state changes.
        - `Textual` based CLI interface for interactive debugging.
    """

    def __init__(self, control_unit: Control_Unit):
        self.control_unit: Control_Unit = control_unit
        self.breakpoints: set[int] = set()
        self.num_rep: int = 10  # base used for register output, changed by `radix`

    def read_command(self) -> ExecutionCommand:
        """Read a command from the user, prompting again until it is valid."""
        while True:
            line = input("(debugger) ").strip()
            if not line:
                continue
            try:
                return self._match_command(line)
            except InvalidCommandError as e:
                print(e)

    # === Breakpoint Management ===

    def add_breakpoint(self, line_number: int):
        """Add a breakpoint at the specified line number."""
        self.breakpoints.add(line_number - 1)  # Adjust for 0-based indexing

    def remove_breakpoint(self, line_number: int):
        """Remove a breakpoint from the specified line number."""
        self.breakpoints.discard(line_number - 1)  # Adjust for 0-based indexing

    def list_breakpoints(self):
        """List all current breakpoints."""
        if not self.breakpoints:
            print("No breakpoints set.")
        else:
            print("Current breakpoints:")
            for bp in sorted(self.breakpoints):
                print(f"  Line {bp + 1}")

    # === Execution Control ===

    def step(self):
        """Step through the next instruction."""
        self.control_unit._step()  # type: ignore

    def continue_execution(self) -> Control_Unit:
        """Continue execution until the next breakpoint or end of program."""
        # Step once to avoid immediately hitting the current breakpoint if the program is already at a breakpoint
        self.step() if not self.control_unit.finished else None 

        while not self.control_unit.finished:
            if self.control_unit.rip in self.breakpoints:
                break
            else:
                self.step()
        return self.control_unit

    def quit(self):
        """Quit the debugger and exit the program."""
        print("Exiting debugger.")
        sys.exit(0)

    # === Memory and Register Inspection ===
    def _read_registers(
        self, register: str | None = None, num_rep: int | None = None
    ) -> dict[str, int | str]:
        """
        Fetch the current value of one register, or of all of them.

        Reuses Control_Unit.get_state("registers"), so values come back with
        the same signed handling and formatting as the other API: a plain int
        for base 10, a prefixed string ("0x2a") for bases 2, 8 and 16. `rip`
        and `eflags` (the whole flags register) are added to the result since
        they are not part of the register map. Sub-registers (eax, ax, al, ...)
        can be requested by name.

        :param register: Register or flag name (case-insensitive, optional "$"). None returns everything.
        :param num_rep: 2, 8, 10 or 16. None uses the debugger's current radix (see `radix`).
        :return: Mapping of register/flag name to its value.
        :raises InvalidCommandError: If the register does not exist or num_rep is unsupported.
        """
        if num_rep is None:
            num_rep = self.num_rep
        try:
            state = self.control_unit.get_state("registers", num_rep)
        except ValueError as e:
            raise InvalidCommandError(str(e))
        registers = self.control_unit.registers
        state["rip"] = Control_Unit._format_value(self.control_unit.rip, 8, num_rep) # type: ignore
        # read_flags returns the 32-bit flags register as little-endian bytes
        eflags = int.from_bytes(registers.read_flags(), byteorder="little")
        state["eflags"] = Control_Unit._format_value(eflags, 4, num_rep) # type: ignore

        if register is None:
            return state

        name = register.lstrip("$").lower()
        for key, value in state.items():
            if key.lower() == name:
                return {key: value}

        # Not a 64-bit register or flag: try sub-registers (eax, ax, al, ...),
        # which read_reg resolves to the right parent and width.
        try:
            size = registers.get_register_parent(name)[1]
            return {name: Control_Unit._format_value(registers.read_reg(name), size, num_rep)} # type: ignore
        except ValueError:
            raise InvalidCommandError(f"Unknown register: '{register}'.")

    def _resolve_address(self, command: ExecutionCommand) -> int:
        """Return the absolute address an EXAMINE command points at, reading `$reg` if needed."""
        if command.address_register is not None:
            value = self._read_registers(command.address_register, num_rep=10)
            (raw,) = value.values()
            assert isinstance(raw, int)
            return raw & 0xFFFFFFFFFFFFFFFF  # registers are read signed
        assert command.address is not None
        return command.address

    def _examine_memory(
        self, address: int, count: int = 1, unit: int = 8, fmt: str = "x"
    ) -> dict[int, int | str]:
        """
        Fetch `count` consecutive units of `unit` bytes starting at `address`.

        :param address: Absolute start address.
        :param count: Number of units to read.
        :param unit: Unit size in bytes (1, 2, 4 or 8).
        :param fmt: 'x' hex string, 'd' signed int, 'u' unsigned int.
        :return: Mapping of each unit's address to its value, in address order.
        :raises InvalidCommandError: If a read fails (e.g. unmapped address).
        """
        values: dict[int, int | str] = {}
        for i in range(count):
            addr = address + i * unit
            try:
                data: bytes = self.control_unit.memory.read_bytes(addr, unit)  # type: ignore
            except Exception as e:  # TODO: narrow to whatever read_bytes raises
                raise InvalidCommandError(f"Cannot access memory at 0x{addr:x}: {e}")

            if fmt == "u":
                values[addr] = int.from_bytes(data, byteorder="little", signed=False)
                continue
            signed = int.from_bytes(data, byteorder="little", signed=True)
            values[addr] = (
                signed if fmt == "d" else Control_Unit._format_value(signed, unit, 16) # type: ignore
            )
        return values

    # === Output Settings ===

    def set_radix(self, base: int | None = None) -> int:
        """
        Change the numerical representation used when reading registers, or
        just query it when no base is given.

        :param base: 2, 8, 10 or 16. None leaves the setting unchanged.
        :return: The base now in effect.
        :raises InvalidCommandError: If the base is not supported.
        """
        if base is not None:
            if base not in VALID_RADIXES:
                raise InvalidCommandError(f"Unsupported radix '{base}'.")
            self.num_rep = base
        return self.num_rep

    # === Command Matching ===

    def _match_command(self, line: str) -> ExecutionCommand:
        """
        Turn a raw input line into a validated ExecutionCommand.

        Handles case insensitivity, aliases, unique-prefix matching
        (e.g. "inf re" -> "info registers"), and x/NFU memory examination.

        :param line: The user input command string.
        :return: The matched and argument-validated ExecutionCommand.
        :raises InvalidCommandError: If the input is ambiguous, unknown, or
            has invalid arguments.
        """
        tokens = line.lower().split()
        if not tokens:
            raise InvalidCommandError("Empty command. Type 'help' for a list of commands.")
        head, rest = tokens[0], tokens[1:]

        # x/NFU ADDRESS: the format spec rides on the command word itself.
        if head == "x" or head.startswith("x/"):
            return ExecutionCommand(Command.EXAMINE, [head[2:]] + rest)

        names: dict[str, Command | str] = {
            c.value.split()[0]: c for c in Command if not c.value.startswith("info")
        }
        names[INFO] = INFO
        command = self._resolve(head, ALIASES, names)

        if command == INFO:
            if not rest:
                raise InvalidCommandError(
                    "Usage: info registers [REGISTER] | info breakpoints"
                )
            command = self._resolve(rest[0], INFO_ALIASES, INFO_SUBCOMMANDS)
            rest = rest[1:]

        assert isinstance(command, Command)
        return ExecutionCommand(command, rest)

    @staticmethod
    def _resolve(word: str, aliases: Mapping[str, Command | str], names: Mapping[str, Command | str]) -> Command | str:
        """Exact alias first, then exact name, then unique prefix."""
        if word in aliases:
            return aliases[word]
        if word in names:
            return names[word]
        matches = {value for name, value in names.items() if name.startswith(word)}
        if len(matches) == 1:
            return matches.pop()
        if matches:
            raise InvalidCommandError(f"Command '{word}' is ambiguous.")
        raise InvalidCommandError(
            f"Invalid command: '{word}'. Type 'help' for a list of commands."
        )