"""
GDB-style debugger for the x86-64 interpreter, built to sit behind any front end.

Layers (use whichever your front end needs):
  - Parsing:    `Debugger.parse(line)` -> ExecutionCommand (no I/O).
  - Fetching:   `read_registers`, `examine_memory`, `source_lines`,
                `breakpoint_lines`, ... return data and never print.
  - Running:    `step()` and `run_chunk(n)` return a `Stop`; `run_chunk` runs at
                most n instructions so a UI can stay responsive between chunks.
  - Executing:  `execute(ec)` / `submit(line)` run a command and return a
                `CommandResult` (structured data plus ready-to-show text lines).
  - Console:    `repl()` is a plain-terminal front end built on the layers above.

Nothing here calls `print`, `input` or `sys.exit` except `read_command` and
`repl`, the plain-terminal front end. Text the emulated program prints while it
runs is captured and handed back, not written to the terminal.
"""

import contextlib
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from interpreter._src.parsing.control_unit import Control_Unit, CPUException
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
RADIX_LABELS = {2: "binary", 8: "octal", 10: "decimal", 16: "hexadecimal"}

# How many x/ units are shown per row, by unit size in bytes (same as GDB).
MEMORY_UNITS_PER_ROW = {1: 8, 2: 8, 4: 4, 8: 2}

# Instructions executed per `run_chunk` call unless told otherwise.
DEFAULT_CHUNK = 1000

HELP_TEXT = """\
Debugger commands (unique prefixes work, e.g. 'inf re' for 'info registers'):
  run (r)                              run until a breakpoint or the end
  continue (c)                         continue until the next breakpoint or the end
  step instruction (stepi, si, s)      execute one instruction
  break (b) LINE                       set a breakpoint at LINE
  delete (d) LINE                      remove the breakpoint at LINE
  info breakpoints (i b)               list breakpoints
  info registers [REG] (i r)           show all registers, or just REG
  x/NFU ADDRESS                        examine memory: N=count, F=x|d|u, U=b|h|w|g
                                       ADDRESS is a number (0x1000) or a register ($rsp)
  radix [2|8|10|16|bin|oct|dec|hex]    show or change the register output base
  help (h)                             show this text
  quit (q, exit)                       leave the debugger"""


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
                # A Command exists that has no argument rules: a bug, not user error.
                raise ValueError(f"No argument rules for command {command!r}")

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


class StopReason(Enum):
    """Why execution stopped after a step or a run."""

    STEPPED = "stepped"  # a single instruction was executed
    BREAKPOINT = "breakpoint"  # about to execute a line with a breakpoint
    FINISHED = "finished"  # the program ended normally
    EXITED = "exited"  # the program or interpreter called sys.exit
    FAULT = "fault"  # the emulated CPU raised a CPUException


@dataclass(frozen=True)
class Stop:
    """What happened when execution stopped. `line` is 1-based (the next line to run)."""

    reason: StopReason
    line: int | None = None
    exit_code: int | None = None  # EXITED only
    exit_name: str | None = None  # EXITED only, e.g. "INVALID_SYSCALL" when available
    message: str | None = None  # FAULT message, or EXITED with a non-numeric code


@dataclass(frozen=True)
class SourceLine:
    """One line of the program, for a source panel. `number` is 1-based."""

    number: int
    text: str
    is_current: bool = False
    has_breakpoint: bool = False


@dataclass
class CommandResult:
    """
    The outcome of executing one command.

    `lines` is the human-readable text for the command, ready to append to a
    log. The other fields carry the same information as data so a UI can feed
    panels instead of parsing text; only the fields relevant to the command
    are set. Text the emulated program printed while running is in `output`
    and is not repeated in `lines`.
    """

    command: Command | None
    lines: list[str] = field(default_factory=list[str])
    ok: bool = True  # False when the command was rejected (bad input, bad address, ...)
    output: str = ""
    stop: Stop | None = None  # STEP / RUN / CONTINUE
    registers: dict[str, int | str] | None = None  # INFO_REGISTERS
    memory: dict[int, int | str] | None = None  # EXAMINE: address -> value
    memory_unit: int = 8
    memory_fmt: str = "x"
    breakpoints: list[int] | None = None  # BREAK / DELETE / INFO_BREAKPOINTS (1-based)
    radix: int | None = None  # RADIX
    quit: bool = False  # QUIT: the front end should close

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class Debugger:
    """
    A GDB-like debugger for the interpreter's `Control_Unit`.

    API:
        - `parse`, `read_command`: turn text into a validated ExecutionCommand.
        - `execute`, `submit`: run a command / a line of text, get a CommandResult.
        - `step`, `run_chunk`, `continue_execution`: run the program, get a Stop.
        - `stop_result`: turn a Stop into a CommandResult (for front ends that
          drive `run_chunk` themselves).
        - `read_registers`, `examine_memory`, `resolve_address`, `set_radix`.
        - `add_breakpoint`, `remove_breakpoint`, `breakpoint_lines`.
        - `source_lines`, `current_line`, `program_lines`.
        - `take_output`: text the emulated program printed since the last call.
        - `repl`: plain-terminal front end.
    """

    def __init__(self, control_unit: Control_Unit):
        self.control_unit: Control_Unit = control_unit
        self.breakpoints: set[int] = set()  # 0-based line indexes (compared with rip)
        self.num_rep: int = 10  # base used for register output, changed by `radix`
        self._exit_stop: Stop | None = None
        self._output = io.StringIO()

    @property
    def done(self) -> bool:
        """True once the program ended, exited or faulted."""
        return self.control_unit.finished or self._exit_stop is not None

    # === Program text ===

    @staticmethod
    def format_instruction(tokens: "list[str] | tuple[str, ...] | str") -> str:
        """Render a tokenised line as text: ['mov', 'rax', '1'] -> 'mov rax, 1'."""
        if isinstance(tokens, str):
            return tokens
        tokens = list(tokens)
        if len(tokens) <= 1:
            return "".join(tokens)
        return f"{tokens[0]} {', '.join(tokens[1:])}"

    def source_lines(self) -> list[SourceLine]:
        """Every line of the program with its current-line and breakpoint flags."""
        rip = self.control_unit.rip
        return [
            SourceLine(i + 1, self.format_instruction(tokens), i == rip, i in self.breakpoints)
            for i, tokens in enumerate(self.control_unit.text_section)
        ]

    def current_line(self) -> SourceLine | None:
        """The line about to be executed, or None if the program is over or rip is out of range."""
        if self.done:
            return None
        rip = self.control_unit.rip
        text_section = self.control_unit.text_section
        if not 0 <= rip < len(text_section):
            return None
        return SourceLine(
            rip + 1,
            self.format_instruction(text_section[rip]),
            is_current=True,
            has_breakpoint=rip in self.breakpoints,
        )

    def program_lines(self) -> list[str]:
        """The program as display strings: ' --> ' marks the current line and 'b' a breakpoint."""
        rows: list[str] = []
        for line in self.source_lines():
            if line.is_current and line.has_breakpoint:
                gutter = " -->b"
            elif line.is_current:
                gutter = " --> "
            elif line.has_breakpoint:
                gutter = "  b  "
            else:
                gutter = "     "
            rows.append(f"{gutter}{line.number}: {line.text}")
        return rows

    # === Breakpoints ===

    def add_breakpoint(self, line_number: int) -> bool:
        """Set a breakpoint at a 1-based line. Returns False if it was already set."""
        index = line_number - 1
        if index in self.breakpoints:
            return False
        self.breakpoints.add(index)
        return True

    def remove_breakpoint(self, line_number: int) -> bool:
        """Remove the breakpoint at a 1-based line. Returns False if there was none."""
        index = line_number - 1
        if index not in self.breakpoints:
            return False
        self.breakpoints.discard(index)
        return True

    def breakpoint_lines(self) -> list[int]:
        """The 1-based lines that have a breakpoint, in order."""
        return [bp + 1 for bp in sorted(self.breakpoints)]

    # === Running the program ===

    def step(self) -> Stop:
        """Execute one instruction. Safe to call after the program ended (returns that end)."""
        if self.done:
            return self._end_stop()
        with contextlib.redirect_stdout(self._output):
            stop = self._step_once()
        if stop is None and self.control_unit.finished:
            stop = Stop(StopReason.FINISHED)
        return stop or Stop(StopReason.STEPPED, line=self.control_unit.rip + 1)

    def run_chunk(self, max_steps: int = DEFAULT_CHUNK) -> Stop | None:
        """
        Run at most `max_steps` instructions, stopping early at a breakpoint or
        when the program ends.

        The first instruction always executes before breakpoints are checked, so
        calling this while standing on a breakpoint moves past it. A front end
        calls this repeatedly (yielding to its event loop in between) until it
        returns a Stop, so a long or endless program never freezes the UI.

        :return: The Stop, or None if `max_steps` ran out and the program is still going.
        """
        if self.done:
            return self._end_stop()
        with contextlib.redirect_stdout(self._output):
            for _ in range(max_steps):
                stop = self._step_once()
                if stop is None and self.control_unit.finished:
                    stop = Stop(StopReason.FINISHED)
                if stop is not None:
                    return stop
                if self.control_unit.rip in self.breakpoints:
                    return Stop(StopReason.BREAKPOINT, line=self.control_unit.rip + 1)
        return None

    def continue_execution(self) -> Stop:
        """
        Run until a breakpoint or the end of the program. Blocks the caller, so
        a program that never ends never returns: front ends that must stay
        responsive should loop over `run_chunk` instead.
        """
        while True:
            stop = self.run_chunk()
            if stop is not None:
                return stop

    def take_output(self) -> str:
        """Return, and clear, the text the emulated program printed since the last call."""
        text = self._output.getvalue()
        self._output.seek(0)
        self._output.truncate()
        return text

    def _step_once(self) -> Stop | None:
        """Execute one instruction; return a Stop only if it ended the program abnormally."""
        try:
            self.control_unit._step()  # type: ignore
        except CPUException as e:
            # Same handling as Control_Unit.run(): report it and end the program
            self.control_unit.finished = True
            self._exit_stop = Stop(
                StopReason.FAULT, line=self.control_unit.rip + 1, message=str(e)
            )
        except SystemExit as e:
            # The interpreter calls sys.exit on bad instructions, a missing exit, etc.
            self._exit_stop = self._stop_from_exit(e)
        return self._exit_stop

    def _stop_from_exit(self, exc: SystemExit) -> Stop:
        code = exc.code
        name = getattr(code, "name", None)  # ExitCode members carry a name
        value = getattr(code, "value", code)
        if value is None:
            value = 0
        return Stop(
            StopReason.EXITED,
            line=self.control_unit.rip + 1,
            exit_code=value if isinstance(value, int) else None,
            exit_name=name,
            message=None if isinstance(value, int) else str(value),
        )

    def _end_stop(self) -> Stop:
        return self._exit_stop or Stop(StopReason.FINISHED)

    # === Registers, memory and output settings ===

    def read_registers(
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
        state["rip"] = Control_Unit._format_value(self.control_unit.rip, 8, num_rep)  # type: ignore
        # read_flags returns the 32-bit flags register as little-endian bytes
        eflags = int.from_bytes(registers.read_flags(), byteorder="little")
        state["eflags"] = Control_Unit._format_value(eflags, 4, num_rep)  # type: ignore

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
            return {name: Control_Unit._format_value(registers.read_reg(name), size, num_rep)}  # type: ignore
        except ValueError:
            raise InvalidCommandError(f"Unknown register: '{register}'.")

    def resolve_address(self, command: ExecutionCommand) -> int:
        """Return the absolute address an EXAMINE command points at, reading `$reg` if needed."""
        if command.address_register is not None:
            value = self.read_registers(command.address_register, num_rep=10)
            (raw,) = value.values()
            assert isinstance(raw, int)
            return raw & 0xFFFFFFFFFFFFFFFF  # registers are read signed
        assert command.address is not None
        return command.address

    def examine_memory(
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
                signed if fmt == "d" else Control_Unit._format_value(signed, unit, 16)  # type: ignore
            )
        return values

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

    @staticmethod
    def help_text() -> str:
        return HELP_TEXT

    # === Command execution ===

    def submit(self, line: str) -> CommandResult:
        """Parse and execute one line of user input. Never raises for bad input."""
        if not line.strip():
            return CommandResult(None)
        try:
            ec = self.parse(line)
        except InvalidCommandError as e:
            return CommandResult(None, [str(e)], ok=False)
        return self.execute(ec)

    def execute(self, ec: ExecutionCommand) -> CommandResult:
        """
        Run one validated command and return its result.

        Problems with the command itself (unknown register, unreadable memory,
        ...) come back as a result with `ok=False`, not as exceptions. RUN and
        CONTINUE block until the program stops; a UI that must stay responsive
        should loop over `run_chunk` and call `stop_result` instead.
        """
        try:
            match ec.command:
                case Command.RUN | Command.CONTINUE:
                    if self.done:
                        return CommandResult(ec.command, ["The program is not being run."])
                    return self.stop_result(ec.command, self.continue_execution())
                case Command.STEP:
                    if self.done:
                        return CommandResult(ec.command, ["Program has finished."])
                    return self.stop_result(ec.command, self.step())
                case Command.BREAK:
                    assert ec.line is not None
                    added = self.add_breakpoint(ec.line)
                    text = (
                        f"Breakpoint set at line {ec.line}."
                        if added
                        else f"Breakpoint already set at line {ec.line}."
                    )
                    return CommandResult(ec.command, [text], breakpoints=self.breakpoint_lines())
                case Command.DELETE:
                    assert ec.line is not None
                    removed = self.remove_breakpoint(ec.line)
                    text = (
                        f"Breakpoint at line {ec.line} removed."
                        if removed
                        else f"No breakpoint at line {ec.line}."
                    )
                    return CommandResult(ec.command, [text], breakpoints=self.breakpoint_lines())
                case Command.INFO_BREAKPOINTS:
                    lines = self.breakpoint_lines()
                    text_lines = (
                        ["Current breakpoints:"] + [f"  Line {n}" for n in lines]
                        if lines
                        else ["No breakpoints set."]
                    )
                    return CommandResult(ec.command, text_lines, breakpoints=lines)
                case Command.INFO_REGISTERS:
                    registers = self.read_registers(ec.register)
                    return CommandResult(
                        ec.command,
                        [f"{name:<8}{value}" for name, value in registers.items()],
                        registers=registers,
                    )
                case Command.EXAMINE:
                    address = self.resolve_address(ec)
                    memory = self.examine_memory(address, ec.count, ec.unit, ec.fmt)
                    return CommandResult(
                        ec.command,
                        self._format_memory(memory, ec.unit),
                        memory=memory,
                        memory_unit=ec.unit,
                        memory_fmt=ec.fmt,
                    )
                case Command.RADIX:
                    base = self.set_radix(ec.radix)
                    label = f"{RADIX_LABELS[base]} (base {base})"
                    text = (
                        f"Current output radix: {label}."
                        if ec.radix is None
                        else f"Output radix set to {label}."
                    )
                    return CommandResult(ec.command, [text], radix=base)
                case Command.HELP:
                    return CommandResult(ec.command, self.help_text().splitlines())
                case Command.QUIT:
                    return CommandResult(ec.command, ["Exiting debugger."], quit=True)
                case _:
                    # A Command exists that has no handler: a bug, not user error.
                    raise ValueError(f"No handler for command {ec.command!r}")
        except InvalidCommandError as e:
            return CommandResult(ec.command, [str(e)], ok=False)

    def stop_result(self, command: Command | None, stop: Stop) -> CommandResult:
        """
        Build the result for a Stop, and collect the program's captured output.

        `execute` uses this for STEP/RUN/CONTINUE. Front ends that drive
        `run_chunk` themselves call it once the loop ends.
        """
        return CommandResult(
            command, self._describe_stop(stop), stop=stop, output=self.take_output()
        )

    def _describe_stop(self, stop: Stop) -> list[str]:
        match stop.reason:
            case StopReason.STEPPED:
                return self._location_lines()
            case StopReason.BREAKPOINT:
                return [f"Breakpoint hit at line {stop.line}."] + self._location_lines()
            case StopReason.FINISHED:
                return ["Program finished."]
            case StopReason.EXITED:
                if stop.exit_code is None:
                    what = f"Program exited: {stop.message}"
                else:
                    code = (
                        f"{stop.exit_code} ({stop.exit_name})"
                        if stop.exit_name
                        else str(stop.exit_code)
                    )
                    what = f"Program exited with code {code}"
                return [f"{what} at line {stop.line}."]
            case StopReason.FAULT:
                return [f"CPU exception: {stop.message} at line {stop.line}."]

    def _location_lines(self) -> list[str]:
        """The line about to execute, e.g. ['12: mov rax, 1']."""
        if self.done:
            return []
        line = self.current_line()
        if line is None:
            return [f"At line {self.control_unit.rip + 1}."]
        return [f"{line.number}: {line.text}"]

    @staticmethod
    def _format_memory(values: Mapping[int, int | str], unit: int) -> list[str]:
        """Format x/ results GDB-style: an address, then a few units per row."""
        per_row = MEMORY_UNITS_PER_ROW[unit]
        items = list(values.items())
        rows: list[str] = []
        for start in range(0, len(items), per_row):
            row = items[start : start + per_row]
            # Zero-pad hex strings to the unit width so columns line up
            cells = [
                "0x" + v[2:].zfill(unit * 2) if isinstance(v, str) else str(v)
                for _, v in row
            ]
            rows.append(f"0x{row[0][0]:x}:\t" + "\t".join(cells))
        return rows

    # === Plain-terminal front end ===

    def read_command(self) -> ExecutionCommand:
        """Read a command from the terminal, prompting again until it is valid."""
        while True:
            line = input("(debugger) ").strip()
            if not line:
                continue
            try:
                return self.parse(line)
            except InvalidCommandError as e:
                print(e)

    def repl(self) -> None:
        """
        Plain-terminal loop: read, execute, print, until `quit`.

        Returns when the user quits (Ctrl-D counts); it does not exit the
        process, so the caller decides what happens next. Ctrl-C at the prompt
        only prints a reminder.
        """
        for text in self._location_lines():
            print(text)
        while True:
            try:
                ec = self.read_command()
            except EOFError:
                print("\nExiting debugger.")
                return
            except KeyboardInterrupt:
                print("\nQuit (type 'quit' to exit).")
                continue
            result = self.execute(ec)
            if result.output:
                print(result.output, end="" if result.output.endswith("\n") else "\n")
            for text in result.lines:
                print(text)
            if result.quit:
                return

    # === Command matching ===

    def parse(self, line: str) -> ExecutionCommand:
        """
        Turn a raw input line into a validated ExecutionCommand.

        Handles case insensitivity, aliases, unique-prefix matching
        (e.g. "inf re" -> "info registers"), and x/NFU memory examination.
        Does no I/O.

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
    def _resolve(
        word: str,
        aliases: Mapping[str, Command | str],
        names: Mapping[str, Command | str],
    ) -> Command | str:
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