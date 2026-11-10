"""
Tests for the GDB-style debugger (command parsing, breakpoints, execution
control, register/memory fetching, radix handling).

Run with:  pytest tests/test_debugger.py -v

The debugger is tested against small in-memory fakes of the control unit,
register file and memory, so no compiled C library (libreg.so) is needed.
Only the debugger module itself and `Control_Unit._format_value` (a pure
static helper) come from the real project.

Set DEBUGGER_MODULE below to wherever the debugger lives in your package.

One group of tests deserves a note: TestRealRegisterPattern runs against
your real REGISTER_PATTERN (every other test swaps in a known pattern so they
don't depend on it). If one of those fails, the parser rejects a register name
the rest of the debugger supports.
"""

import builtins
import importlib

import pytest

DEBUGGER_MODULE = "interpreter._src.parsing.debugger"

dbg = importlib.import_module(DEBUGGER_MODULE)
Command = dbg.Command
Debugger = dbg.Debugger
ExecutionCommand = dbg.ExecutionCommand
InvalidCommandError = dbg.InvalidCommandError
CommandResult = dbg.CommandResult
SourceLine = dbg.SourceLine
Stop = dbg.Stop
StopReason = dbg.StopReason
CPUException = dbg.CPUException

# A register pattern we control, so tests don't depend on the project's own.
FAKE_REGISTER_PATTERN = (
    r"(?:r(?:[a-d]x|[sd]i|[sb]p|[89]|1[0-5])[dwb]?"
    r"|e[a-d]x|e[sd]i|e[sb]p|[a-d]x|[a-d][lh]|[sd]il|[sb]pl|[sd]i|[sb]p)"
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRegisters:
    """Mimics the parts of Registers_Interface the debugger touches."""

    GPRS = [
        "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
    ]  # fmt: skip
    SUBREGS = {
        "eax": ("rax", 4),
        "ax": ("rax", 2),
        "al": ("rax", 1),
        "ebx": ("rbx", 4),
        "r8d": ("r8", 4),
    }

    def __init__(self, values=None, eflags=0x246, flags=None):
        self.values = {name: 0 for name in self.GPRS}
        self.values.update({"rax": 42, "rbx": -1, "rsp": 0x1000})
        self.values.update(values or {})
        self.eflags = eflags
        self.flags = {"zf": 1, "cf": 0, "sf": 0, "of": 0, "pf": 1, "tf": 0}
        self.flags.update(flags or {})
        self.read_reg_calls: list[str] = []

    def read_reg(self, name):
        name = name.lower()
        self.read_reg_calls.append(name)
        if name in self.values:
            return self.values[name]
        if name in self.SUBREGS:
            parent, size = self.SUBREGS[name]
            return self.values[parent] & ((1 << (size * 8)) - 1)
        raise ValueError(f"REGISTER {name} DOES NOT EXIST.")

    def get_register_parent(self, name):
        name = name.lower()
        if name in self.SUBREGS:
            return self.SUBREGS[name]
        return name, 8  # same fallback as the real implementation

    def read_flags(self):
        return self.eflags.to_bytes(4, "little")

    def read_zero(self):
        return bool(self.flags["zf"])

    def read_carry(self):
        return bool(self.flags["cf"])

    def read_sign(self):
        return bool(self.flags["sf"])

    def read_overflow(self):
        return bool(self.flags["of"])

    def read_parity(self):
        return bool(self.flags["pf"])

    def read_trap_flag(self):
        return bool(self.flags["tf"])


class FakeMemory:
    """Byte-addressable memory; reading an unmapped byte raises IndexError."""

    def __init__(self, regions=None):
        self.bytes: dict[int, int] = {}
        for base, data in (regions or {}).items():
            for offset, byte in enumerate(data):
                self.bytes[base + offset] = byte

    def read_bytes(self, address, size):
        out = bytearray()
        for a in range(address, address + size):
            if a not in self.bytes:
                raise IndexError(f"address 0x{a:x} is not mapped")
            out.append(self.bytes[a])
        return bytes(out)


class FakeControlUnit:
    """Stand-in for Control_Unit: rip, finished, _step, get_state, memory."""

    def __init__(
        self, registers=None, memory=None, rip=0, program_length=10, on_rip=None
    ):
        self.registers = registers or FakeRegisters()
        self.memory = memory or FakeMemory()
        self.rip = rip
        self.program_length = program_length
        self.finished = False
        self.steps = 0
        # Like the real Control_Unit, each line is a list of tokens
        self.text_section = [["instr", str(i)] for i in range(program_length)]
        # rip -> callable run when that line is stepped (to raise, print, ...)
        self.on_rip = on_rip or {}

    def _step(self):
        action = self.on_rip.get(self.rip)
        if action is not None:
            action()  # may raise or print, like a real faulting instruction
        self.steps += 1
        self.rip += 1
        if self.rip >= self.program_length:
            self.finished = True

    def get_state(self, section, num_rep=16):
        # Mirrors Control_Unit.get_state("registers", ...), including the
        # ValueError on unsupported representations.
        if num_rep not in (2, 8, 10, 16):
            raise ValueError(f"UNSUPPORTED NUMERICAL REPRESENTATION '{num_rep}'.")
        if section != "registers":
            raise ValueError(f"UNKNOWN SECTION '{section}'.")
        fmt = dbg.Control_Unit._format_value
        state = {}
        for name in FakeRegisters.GPRS:
            state[name] = fmt(self.registers.read_reg(name), 8, num_rep)
        state["ZF"] = fmt(int(self.registers.read_zero()), 1, num_rep)
        state["CF"] = fmt(int(self.registers.read_carry()), 1, num_rep)
        state["SF"] = fmt(int(self.registers.read_sign()), 1, num_rep)
        state["OF"] = fmt(int(self.registers.read_overflow()), 1, num_rep)
        state["PF"] = fmt(int(self.registers.read_parity()), 1, num_rep)
        state["TF"] = fmt(int(self.registers.read_trap_flag()), 1, num_rep)
        return state


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def known_register_pattern(request, monkeypatch):
    """Use a known REGISTER_PATTERN unless a test class opts into the real one."""
    if getattr(request.cls, "use_real_pattern", False):
        return
    monkeypatch.setattr(dbg, "REGISTER_PATTERN", FAKE_REGISTER_PATTERN)


@pytest.fixture
def cu():
    return FakeControlUnit()


@pytest.fixture
def debugger(cu):
    return Debugger(cu)


def parse(line):
    return Debugger(FakeControlUnit()).parse(line)


# ---------------------------------------------------------------------------
# Command enum
# ---------------------------------------------------------------------------


class TestCommandEnum:
    def test_expected_members_exist(self):
        expected = {
            "RUN", "STEP", "CONTINUE", "BREAK", "DELETE", "INFO_BREAKPOINTS",
            "INFO_REGISTERS", "EXAMINE", "RADIX", "HELP", "QUIT",
        }  # fmt: skip
        assert expected <= {c.name for c in Command}

    def test_values_are_unique(self):
        values = [c.value for c in Command]
        assert len(values) == len(set(values))

    def test_values_are_clean(self):
        # Regression: DELETE used to be " delete" (leading space)
        for c in Command:
            assert c.value == c.value.strip()
            assert c.value == c.value.lower()


class TestInvalidCommandError:
    def test_carries_message(self):
        assert str(InvalidCommandError("boom")) == "boom"

    def test_does_not_print_when_constructed(self, capsys):
        # Regression: the original printed from __init__, so errors showed twice
        InvalidCommandError("boom")
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Command matching: aliases, prefixes, case
# ---------------------------------------------------------------------------


class TestMatchCommand:
    @pytest.mark.parametrize(
        "line, expected",
        [
            ("run", Command.RUN), ("r", Command.RUN), ("ru", Command.RUN),
            ("step", Command.STEP), ("step instruction", Command.STEP),
            ("s", Command.STEP), ("si", Command.STEP),
            ("stepi", Command.STEP), ("ste", Command.STEP),
            ("continue", Command.CONTINUE), ("c", Command.CONTINUE),
            ("co", Command.CONTINUE), ("cont", Command.CONTINUE),
            ("break 5", Command.BREAK), ("b 5", Command.BREAK),
            ("br 5", Command.BREAK),
            ("delete 5", Command.DELETE), ("d 5", Command.DELETE),
            ("del 5", Command.DELETE),
            ("help", Command.HELP), ("h", Command.HELP), ("he", Command.HELP),
            ("quit", Command.QUIT), ("q", Command.QUIT),
            ("qu", Command.QUIT), ("exit", Command.QUIT),
            ("radix", Command.RADIX), ("ra", Command.RADIX),
            ("rad hex", Command.RADIX),
        ],
    )  # fmt: skip
    def test_top_level_commands_and_aliases(self, line, expected):
        assert parse(line).command is expected

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("info registers", Command.INFO_REGISTERS),
            ("info reg", Command.INFO_REGISTERS),
            ("info re", Command.INFO_REGISTERS),
            ("inf re", Command.INFO_REGISTERS),
            ("in r", Command.INFO_REGISTERS),
            ("i r", Command.INFO_REGISTERS),
            ("info breakpoints", Command.INFO_BREAKPOINTS),
            ("info break", Command.INFO_BREAKPOINTS),
            ("info b", Command.INFO_BREAKPOINTS),
            ("inf br", Command.INFO_BREAKPOINTS),
            ("i b", Command.INFO_BREAKPOINTS),
        ],
    )  # fmt: skip
    def test_info_commands_with_partial_words(self, line, expected):
        assert parse(line).command is expected

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("RUN", Command.RUN),
            ("Break 3", Command.BREAK),
            ("INFO REGISTERS", Command.INFO_REGISTERS),
            ("Inf Re", Command.INFO_REGISTERS),
            ("X/4GX $RSP", Command.EXAMINE),
            ("RADIX HEX", Command.RADIX),
        ],
    )  # fmt: skip
    def test_case_insensitive(self, line, expected):
        assert parse(line).command is expected

    def test_extra_whitespace_is_ignored(self):
        cmd = parse("   break     12  ")
        assert cmd.command is Command.BREAK and cmd.line == 12

    def test_arguments_are_carried_through(self):
        assert parse("break 12").line == 12
        assert parse("delete 3").line == 3
        assert parse("info registers rax").register == "rax"
        assert parse("inf re $RBX").register == "rbx"
        assert parse("info registers").register is None
        assert parse("radix hex").radix == 16
        assert parse("radix").radix is None

    @pytest.mark.parametrize(
        "line, message",
        [
            ("", "Empty command"),
            ("   ", "Empty command"),
            ("foo", "Invalid command"),
            ("xyz", "Invalid command"),
            ("e", "Invalid command"),
            ("info", "Usage"),
            ("i", "Usage"),
            ("info foo", "Invalid command"),
            ("info registers rax rbx", "Usage: info registers"),
            ("info breakpoints now", "takes no arguments"),
            ("run fast", "takes no arguments"),
            ("break", "Usage: break"),
            ("break abc", "positive integer"),
        ],
    )  # fmt: skip
    def test_invalid_input_raises(self, line, message):
        with pytest.raises(InvalidCommandError, match=message):
            parse(line)


class TestResolve:
    resolve = staticmethod(Debugger._resolve)

    def test_alias_beats_prefix(self):
        assert self.resolve("s", {"s": 1}, {"step": 2, "stop": 3}) == 1

    def test_exact_name_beats_prefix(self):
        assert self.resolve("ab", {}, {"ab": 1, "abc": 2}) == 1

    def test_unique_prefix(self):
        assert self.resolve("ste", {}, {"step": 2, "stop": 3}) == 2

    def test_ambiguous_prefix_raises(self):
        with pytest.raises(InvalidCommandError, match="ambiguous"):
            self.resolve("st", {}, {"step": 2, "stop": 3})

    def test_unknown_raises(self):
        with pytest.raises(InvalidCommandError, match="Invalid command"):
            self.resolve("zzz", {}, {"step": 2})

    def test_prefix_of_several_names_with_same_target_is_not_ambiguous(self):
        assert self.resolve("a", {}, {"alpha": 1, "also": 1}) == 1


# ---------------------------------------------------------------------------
# ExecutionCommand argument validation
# ---------------------------------------------------------------------------


class TestExecutionCommandDefaults:
    def test_defaults(self):
        cmd = ExecutionCommand(Command.RUN, [])
        assert cmd.command is Command.RUN
        assert cmd.line is None and cmd.register is None
        assert cmd.address is None and cmd.address_register is None
        assert (cmd.count, cmd.fmt, cmd.unit) == (1, "x", 8)
        assert cmd.radix is None

    def test_none_args_are_treated_as_empty(self):
        assert ExecutionCommand(Command.RUN, None).command is Command.RUN  # type: ignore

    def test_repr_lists_only_set_fields(self):
        text = repr(ExecutionCommand(Command.BREAK, ["12"]))
        assert text.startswith("ExecutionCommand(BREAK")
        assert "'line': 12" in text
        assert "register" not in text and "radix" not in text


class TestNoArgumentCommands:
    NO_ARGS = [
        Command.RUN, Command.CONTINUE, Command.HELP, Command.QUIT,
        Command.INFO_BREAKPOINTS,
    ]  # fmt: skip

    @pytest.mark.parametrize("command", NO_ARGS)
    def test_accepts_no_arguments(self, command):
        assert ExecutionCommand(command, []).command is command

    @pytest.mark.parametrize("command", NO_ARGS)
    def test_rejects_extra_arguments(self, command):
        with pytest.raises(InvalidCommandError, match="takes no arguments"):
            ExecutionCommand(command, ["extra"])


class TestStepArguments:
    @pytest.mark.parametrize("args", [[], ["instruction"]])
    def test_valid(self, args):
        assert ExecutionCommand(Command.STEP, args).command is Command.STEP

    @pytest.mark.parametrize(
        "args", [["instr"], ["3"], ["instruction", "extra"], ["into"]]
    )
    def test_invalid(self, args):
        with pytest.raises(InvalidCommandError, match="Usage: step"):
            ExecutionCommand(Command.STEP, args)


class TestBreakAndDeleteArguments:
    @pytest.mark.parametrize("command", [Command.BREAK, Command.DELETE])
    @pytest.mark.parametrize("token, expected", [("1", 1), ("12", 12), ("9999", 9999)])
    def test_valid_line_numbers(self, command, token, expected):
        assert ExecutionCommand(command, [token]).line == expected

    @pytest.mark.parametrize("command", [Command.BREAK, Command.DELETE])
    @pytest.mark.parametrize("args", [[], ["1", "2"]])
    def test_wrong_argument_count(self, command, args):
        with pytest.raises(InvalidCommandError, match="Usage"):
            ExecutionCommand(command, args)

    @pytest.mark.parametrize("command", [Command.BREAK, Command.DELETE])
    @pytest.mark.parametrize(
        "token", ["0", "-1", "abc", "1.5", "", "0x10", "1e3", "\u00b2"]
    )
    def test_invalid_line_numbers(self, command, token):
        # "\u00b2" (superscript two) passes str.isdigit() but not int()
        with pytest.raises(InvalidCommandError, match="positive integer"):
            ExecutionCommand(command, [token])


class TestInfoRegistersArguments:
    def test_no_register_means_all(self):
        assert ExecutionCommand(Command.INFO_REGISTERS, []).register is None

    @pytest.mark.parametrize(
        "token, expected",
        [
            ("rax", "rax"), ("RAX", "rax"), ("$rax", "rax"), ("$RSP", "rsp"),
            ("r8", "r8"), ("r15", "r15"), ("eax", "eax"), ("al", "al"),
            ("rip", "rip"), ("eflags", "eflags"), ("zf", "zf"), ("$CF", "cf"),
            ("sf", "sf"), ("of", "of"), ("pf", "pf"), ("tf", "tf"),
        ],
    )  # fmt: skip
    def test_valid_registers(self, token, expected):
        assert ExecutionCommand(Command.INFO_REGISTERS, [token]).register == expected

    @pytest.mark.parametrize("token", ["foo", "r16", "$", "rax1", "xmm0x", ""])
    def test_invalid_registers(self, token):
        with pytest.raises(InvalidCommandError, match="Unknown register"):
            ExecutionCommand(Command.INFO_REGISTERS, [token])

    def test_too_many_arguments(self):
        with pytest.raises(InvalidCommandError, match="Usage: info registers"):
            ExecutionCommand(Command.INFO_REGISTERS, ["rax", "rbx"])


class TestRadixArguments:
    def test_no_argument_means_query(self):
        assert ExecutionCommand(Command.RADIX, []).radix is None

    @pytest.mark.parametrize(
        "token, expected",
        [
            ("2", 2), ("8", 8), ("10", 10), ("16", 16),
            ("bin", 2), ("binary", 2), ("oct", 8), ("octal", 8),
            ("dec", 10), ("decimal", 10), ("hex", 16), ("hexadecimal", 16),
        ],
    )  # fmt: skip
    def test_valid(self, token, expected):
        assert ExecutionCommand(Command.RADIX, [token]).radix == expected

    @pytest.mark.parametrize(
        "token",
        ["3", "0", "1", "32", "-16", "16.0", "hexa", "", "abc", "HEX", "\u00b2"],
    )
    def test_invalid(self, token):
        with pytest.raises(InvalidCommandError, match="Unsupported radix"):
            ExecutionCommand(Command.RADIX, [token])

    def test_too_many_arguments(self):
        with pytest.raises(InvalidCommandError, match="Usage: radix"):
            ExecutionCommand(Command.RADIX, ["16", "8"])


class TestExamineArguments:
    @pytest.mark.parametrize(
        "spec, count, fmt, unit",
        [
            ("", 1, "x", 8),
            ("4", 4, "x", 8),
            ("x", 1, "x", 8), ("d", 1, "d", 8), ("u", 1, "u", 8),
            ("b", 1, "x", 1), ("h", 1, "x", 2), ("w", 1, "x", 4), ("g", 1, "x", 8),
            ("4gx", 4, "x", 8),
            ("2dw", 2, "d", 4),
            ("3ub", 3, "u", 1),
            ("8bx", 8, "x", 1),
            ("xb", 1, "x", 1),
            ("wd", 1, "d", 4),
            ("10", 10, "x", 8),
            ("16gd", 16, "d", 8),
            ("007", 7, "x", 8),
        ],
    )  # fmt: skip
    def test_format_spec(self, spec, count, fmt, unit):
        cmd = ExecutionCommand(Command.EXAMINE, [spec, "0x10"])
        assert (cmd.count, cmd.fmt, cmd.unit) == (count, fmt, unit)

    @pytest.mark.parametrize("spec", ["0", "00", "z", "4z", "g4", "-1", "1.5", "4 g"])
    def test_invalid_format_spec(self, spec):
        with pytest.raises(InvalidCommandError):
            ExecutionCommand(Command.EXAMINE, [spec, "0x10"])

    def test_zero_count_message(self):
        with pytest.raises(InvalidCommandError, match="Count must be at least 1"):
            ExecutionCommand(Command.EXAMINE, ["0", "0x10"])

    @pytest.mark.parametrize(
        "token, expected",
        [("0x10", 16), ("0X10", 16), ("4096", 4096), ("0b101", 5), ("0", 0)],
    )
    def test_numeric_addresses(self, token, expected):
        cmd = ExecutionCommand(Command.EXAMINE, ["", token])
        assert cmd.address == expected and cmd.address_register is None

    @pytest.mark.parametrize("token, name", [("$rsp", "rsp"), ("$RSP", "rsp"), ("$r8", "r8")])
    def test_register_addresses(self, token, name):
        cmd = ExecutionCommand(Command.EXAMINE, ["", token])
        assert cmd.address_register == name and cmd.address is None

    @pytest.mark.parametrize("token", ["abc", "0x", "", "1.5", "rsp"])
    def test_invalid_addresses(self, token):
        with pytest.raises(InvalidCommandError, match="Invalid address"):
            ExecutionCommand(Command.EXAMINE, ["", token])

    def test_negative_address(self):
        with pytest.raises(InvalidCommandError, match="negative"):
            ExecutionCommand(Command.EXAMINE, ["", "-5"])

    def test_unknown_register_address(self):
        with pytest.raises(InvalidCommandError, match="Unknown register"):
            ExecutionCommand(Command.EXAMINE, ["", "$bogus"])

    @pytest.mark.parametrize("args", [[], [""], ["4gx"], ["4gx", "0x1", "0x2"]])
    def test_wrong_argument_count(self, args):
        with pytest.raises(InvalidCommandError, match="Usage: x/NFU"):
            ExecutionCommand(Command.EXAMINE, args)


class TestExamineFromRawInput:
    def test_full_command(self):
        cmd = parse("x/4gx $rsp")
        assert cmd.command is Command.EXAMINE
        assert (cmd.count, cmd.fmt, cmd.unit) == (4, "x", 8)
        assert cmd.address_register == "rsp"

    def test_bare_x_uses_defaults(self):
        cmd = parse("x 0x1000")
        assert (cmd.count, cmd.fmt, cmd.unit, cmd.address) == (1, "x", 8, 0x1000)

    def test_empty_spec_after_slash(self):
        cmd = parse("x/ 0x1000")
        assert (cmd.count, cmd.fmt, cmd.unit, cmd.address) == (1, "x", 8, 0x1000)

    def test_missing_address(self):
        with pytest.raises(InvalidCommandError, match="Usage: x/NFU"):
            parse("x/4gx")

    def test_extra_arguments(self):
        with pytest.raises(InvalidCommandError, match="Usage: x/NFU"):
            parse("x/4gx 0x1 0x2")

    def test_bad_spec(self):
        with pytest.raises(InvalidCommandError, match="Invalid format"):
            parse("x/zz 0x10")

    def test_hex_address_is_case_insensitive(self):
        assert parse("x 0X1F").address == 0x1F


# ---------------------------------------------------------------------------
# Breakpoints
# ---------------------------------------------------------------------------


class TestBreakpoints:
    def test_add_stores_zero_based_line(self, debugger):
        debugger.add_breakpoint(5)
        assert debugger.breakpoints == {4}

    def test_add_is_idempotent(self, debugger):
        debugger.add_breakpoint(5)
        debugger.add_breakpoint(5)
        assert debugger.breakpoints == {4}

    def test_remove(self, debugger):
        debugger.add_breakpoint(5)
        debugger.add_breakpoint(7)
        debugger.remove_breakpoint(5)
        assert debugger.breakpoints == {6}

    def test_remove_missing_is_not_an_error(self, debugger):
        debugger.remove_breakpoint(99)
        assert debugger.breakpoints == set()

    def test_add_and_remove_report_whether_anything_changed(self, debugger):
        assert debugger.add_breakpoint(5) is True
        assert debugger.add_breakpoint(5) is False
        assert debugger.remove_breakpoint(5) is True
        assert debugger.remove_breakpoint(5) is False

    def test_breakpoint_lines_empty(self, debugger):
        assert debugger.breakpoint_lines() == []

    def test_breakpoint_lines_are_one_based_and_sorted_numerically(self, debugger):
        for line in (10, 2, 33):
            debugger.add_breakpoint(line)
        # numeric order: 2, 10, 33 (not the string order 10, 2, 33)
        assert debugger.breakpoint_lines() == [2, 10, 33]

    def test_breakpoints_are_per_debugger(self):
        a, b = Debugger(FakeControlUnit()), Debugger(FakeControlUnit())
        a.add_breakpoint(1)
        assert b.breakpoints == set()


# ---------------------------------------------------------------------------
# Execution control
# ---------------------------------------------------------------------------


class TestExecutionControl:
    def test_step_runs_exactly_one_instruction(self, debugger, cu):
        debugger.step()
        assert cu.steps == 1 and cu.rip == 1

    def test_continue_without_breakpoints_runs_to_the_end(self, debugger, cu):
        stop = debugger.continue_execution()
        assert stop.reason is StopReason.FINISHED
        assert cu.finished and cu.steps == cu.program_length

    def test_continue_stops_at_breakpoint(self, debugger, cu):
        debugger.add_breakpoint(5)  # stored as rip == 4
        debugger.continue_execution()
        assert cu.rip == 4 and not cu.finished and cu.steps == 4

    def test_continue_stops_at_the_first_of_several_breakpoints(self, debugger, cu):
        debugger.add_breakpoint(7)
        debugger.add_breakpoint(3)
        debugger.continue_execution()
        assert cu.rip == 2

    def test_breakpoint_past_the_end_is_never_hit(self, debugger, cu):
        debugger.add_breakpoint(500)
        debugger.continue_execution()
        assert cu.finished

    def test_removed_breakpoint_no_longer_stops(self, debugger, cu):
        debugger.add_breakpoint(5)
        debugger.remove_breakpoint(5)
        debugger.continue_execution()
        assert cu.finished

    def test_continue_on_finished_program_does_nothing(self, debugger, cu):
        cu.finished = True
        debugger.continue_execution()
        assert cu.steps == 0

    def test_continue_from_a_breakpoint_makes_progress(self, cu):
        cu.rip = 2
        d = Debugger(cu)
        d.add_breakpoint(3)  # rip == 2, where we are standing
        d.continue_execution()
        assert cu.steps >= 1

    def test_second_continue_reaches_the_next_breakpoint(self, debugger, cu):
        debugger.add_breakpoint(3)
        debugger.add_breakpoint(6)
        debugger.continue_execution()
        assert cu.rip == 2
        debugger.continue_execution()
        assert cu.rip == 5




# ---------------------------------------------------------------------------
# Register fetching
# ---------------------------------------------------------------------------


class TestReadRegisters:
    def test_all_registers_decimal(self, debugger):
        state = debugger.read_registers()
        expected_keys = (
            set(FakeRegisters.GPRS)
            | {"ZF", "CF", "SF", "OF", "PF", "TF"}
            | {"rip", "eflags"}
        )
        assert set(state) == expected_keys
        assert state["rax"] == 42 and state["rbx"] == -1
        assert state["ZF"] == 1 and state["CF"] == 0

    def test_returns_values_and_prints_nothing(self, debugger, capsys):
        result = debugger.read_registers()
        assert isinstance(result, dict)
        assert capsys.readouterr().out == ""

    def test_rip_reflects_the_control_unit(self, debugger, cu):
        cu.rip = 7
        assert debugger.read_registers("rip") == {"rip": 7}
        cu.rip = 9
        assert debugger.read_registers("rip") == {"rip": 9}

    def test_eflags_decoded_from_read_flags_bytes(self, cu):
        cu.registers = FakeRegisters(eflags=0x246)
        d = Debugger(cu)
        assert d.read_registers("eflags") == {"eflags": 0x246}
        assert d.read_registers("eflags", 16) == {"eflags": "0x246"}
        assert d.read_registers("eflags", 2) == {"eflags": "0b1001000110"}
        assert d.read_registers("eflags", 8) == {"eflags": "0o1106"}

    def test_eflags_uses_all_four_bytes(self, cu):
        cu.registers = FakeRegisters(eflags=0x80000246)
        assert Debugger(cu).read_registers("eflags", 16) == {"eflags": "0x80000246"}

    def test_eflags_never_goes_through_read_reg(self, debugger, cu):
        # "eflags" starts with "e", so read_reg would mistake it for a 32-bit
        # alias of a register called "rflags"
        debugger.read_registers("eflags")
        assert "eflags" not in cu.registers.read_reg_calls

    @pytest.mark.parametrize("name", ["rax", "RAX", "$rax", "$RAX"])
    def test_single_register_name_forms(self, debugger, name):
        assert debugger.read_registers(name) == {"rax": 42}

    @pytest.mark.parametrize(
        "name, key, value",
        [("zf", "ZF", 1), ("$CF", "CF", 0), ("pf", "PF", 1), ("tf", "TF", 0)],
    )
    def test_single_flags(self, debugger, name, key, value):
        assert debugger.read_registers(name) == {key: value}

    @pytest.mark.parametrize(
        "num_rep, rax, rbx",
        [
            (10, 42, -1),
            (16, "0x2a", "0xffffffffffffffff"),
            (8, "0o52", "0o1777777777777777777777"),
            (2, "0b101010", "0b" + "1" * 64),
        ],
    )
    def test_representations(self, debugger, num_rep, rax, rbx):
        state = debugger.read_registers(num_rep=num_rep)
        assert state["rax"] == rax and state["rbx"] == rbx

    def test_rip_follows_the_representation(self, debugger, cu):
        cu.rip = 255
        assert debugger.read_registers("rip", 16) == {"rip": "0xff"}
        assert debugger.read_registers("rip", 2) == {"rip": "0b11111111"}

    @pytest.mark.parametrize(
        "name, rax, expected",
        [
            ("eax", 42, 42),
            ("ax", 42, 42),
            ("al", 42, 42),
            ("eax", -1, 0xFFFFFFFF),
            ("ax", -1, 0xFFFF),
            ("al", -1, 0xFF),
            ("eax", 0x1_2345_6789, 0x2345_6789),
        ],
    )
    def test_sub_registers_use_the_fallback(self, cu, name, rax, expected):
        cu.registers = FakeRegisters(values={"rax": rax})
        assert Debugger(cu).read_registers(name) == {name: expected}

    def test_sub_registers_in_hex(self, cu):
        cu.registers = FakeRegisters(values={"rax": -1})
        d = Debugger(cu)
        assert d.read_registers("eax", 16) == {"eax": "0xffffffff"}
        assert d.read_registers("al", 16) == {"al": "0xff"}

    @pytest.mark.parametrize("name", ["foo", "r99", "$", "xmm0"])
    def test_unknown_register(self, debugger, name):
        with pytest.raises(InvalidCommandError, match="Unknown register"):
            debugger.read_registers(name)

    @pytest.mark.parametrize("num_rep", [0, 1, 3, 7, 12, 32])
    def test_unsupported_representation(self, debugger, num_rep):
        with pytest.raises(InvalidCommandError, match="UNSUPPORTED"):
            debugger.read_registers(num_rep=num_rep)

    def test_default_representation_is_the_debugger_radix(self, debugger):
        debugger.num_rep = 16
        assert debugger.read_registers("rax") == {"rax": "0x2a"}

    def test_explicit_representation_does_not_change_the_radix(self, debugger):
        debugger.num_rep = 16
        assert debugger.read_registers("rax", num_rep=10) == {"rax": 42}
        assert debugger.num_rep == 16


# ---------------------------------------------------------------------------
# Address resolution
# ---------------------------------------------------------------------------


class TestResolveAddress:
    def test_numeric_address(self, debugger):
        cmd = ExecutionCommand(Command.EXAMINE, ["", "0x1000"])
        assert debugger.resolve_address(cmd) == 0x1000

    def test_register_address(self, debugger):
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        assert debugger.resolve_address(cmd) == 0x1000

    def test_negative_register_is_masked_to_unsigned(self, cu):
        cu.registers = FakeRegisters(values={"rsp": -8})
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        assert Debugger(cu).resolve_address(cmd) == 0xFFFFFFFFFFFFFFF8

    @pytest.mark.parametrize("radix", [2, 8, 10, 16])
    def test_always_an_int_whatever_the_radix(self, debugger, radix):
        debugger.num_rep = radix
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        result = debugger.resolve_address(cmd)
        assert isinstance(result, int) and result == 0x1000

    def test_flag_register_as_address(self, debugger):
        # rip/flags are legal register names, so they must resolve to numbers
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$zf"])
        assert debugger.resolve_address(cmd) == 1


# ---------------------------------------------------------------------------
# Memory fetching
# ---------------------------------------------------------------------------

MEMORY_BYTES = bytes(
    [0x78, 0x56, 0x34, 0x12, 0xFF, 0xFF, 0xFF, 0xFF,
     0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
)  # fmt: skip


@pytest.fixture
def mem_debugger():
    return Debugger(FakeControlUnit(memory=FakeMemory({0x1000: MEMORY_BYTES})))


class TestExamineMemory:
    def test_returns_values_and_prints_nothing(self, mem_debugger, capsys):
        result = mem_debugger.examine_memory(0x1000, 1, 4, "x")
        assert isinstance(result, dict)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize(
        "unit, expected",
        [(1, "0x78"), (2, "0x5678"), (4, "0x12345678"), (8, "0xffffffff12345678")],
    )
    def test_hex_by_unit_size_is_little_endian(self, mem_debugger, unit, expected):
        assert mem_debugger.examine_memory(0x1000, 1, unit, "x") == {0x1000: expected}

    def test_multiple_units_have_consecutive_addresses(self, mem_debugger):
        result = mem_debugger.examine_memory(0x1000, 3, 4, "x")
        assert result == {
            0x1000: "0x12345678",
            0x1004: "0xffffffff",
            0x1008: "0x1",
        }

    def test_results_are_in_address_order(self, mem_debugger):
        result = mem_debugger.examine_memory(0x1000, 8, 1, "x")
        assert list(result) == [0x1000 + i for i in range(8)]

    def test_signed_decimal(self, mem_debugger):
        result = mem_debugger.examine_memory(0x1000, 2, 4, "d")
        assert result == {0x1000: 0x12345678, 0x1004: -1}

    def test_unsigned_decimal(self, mem_debugger):
        result = mem_debugger.examine_memory(0x1000, 2, 4, "u")
        assert result == {0x1000: 0x12345678, 0x1004: 4294967295}

    def test_byte_sign_handling(self, mem_debugger):
        assert mem_debugger.examine_memory(0x1004, 1, 1, "d") == {0x1004: -1}
        assert mem_debugger.examine_memory(0x1004, 1, 1, "u") == {0x1004: 255}
        assert mem_debugger.examine_memory(0x1004, 1, 1, "x") == {0x1004: "0xff"}

    def test_eight_byte_values(self, mem_debugger):
        value = 0xFFFFFFFF12345678
        assert mem_debugger.examine_memory(0x1000, 1, 8, "u") == {0x1000: value}
        assert mem_debugger.examine_memory(0x1000, 1, 8, "d") == {
            0x1000: value - (1 << 64)
        }
        assert mem_debugger.examine_memory(0x1008, 1, 8, "x") == {0x1008: "0x1"}

    def test_defaults_are_one_eight_byte_hex_value(self, mem_debugger):
        assert mem_debugger.examine_memory(0x1000) == {0x1000: "0xffffffff12345678"}

    def test_zero_count_returns_nothing(self, mem_debugger):
        assert mem_debugger.examine_memory(0x1000, 0, 4, "x") == {}

    def test_unmapped_address(self, mem_debugger):
        with pytest.raises(InvalidCommandError, match="0x2000"):
            mem_debugger.examine_memory(0x2000, 1, 4, "x")

    def test_error_names_the_first_unreadable_unit(self, mem_debugger):
        # 16 bytes are mapped; the fifth 4-byte unit starts at 0x1010
        with pytest.raises(InvalidCommandError, match="0x1010"):
            mem_debugger.examine_memory(0x1000, 5, 4, "x")

    def test_unit_straddling_the_end_of_memory_fails(self, mem_debugger):
        with pytest.raises(InvalidCommandError):
            mem_debugger.examine_memory(0x100C, 1, 8, "x")


# ---------------------------------------------------------------------------
# Radix
# ---------------------------------------------------------------------------


class TestRadix:
    def test_default_is_decimal(self, debugger):
        assert debugger.num_rep == 10
        assert debugger.set_radix() == 10

    @pytest.mark.parametrize("base", [2, 8, 10, 16])
    def test_set_returns_and_stores_the_new_base(self, debugger, base):
        assert debugger.set_radix(base) == base
        assert debugger.num_rep == base

    def test_query_does_not_change_it(self, debugger):
        debugger.set_radix(16)
        assert debugger.set_radix(None) == 16
        assert debugger.set_radix() == 16

    @pytest.mark.parametrize("base", [0, 1, 3, 12, 32, -16])
    def test_invalid_base_is_rejected_and_ignored(self, debugger, base):
        debugger.set_radix(16)
        with pytest.raises(InvalidCommandError, match="Unsupported radix"):
            debugger.set_radix(base)
        assert debugger.num_rep == 16

    def test_set_radix_does_not_print(self, debugger, capsys):
        debugger.set_radix(16)
        assert capsys.readouterr().out == ""

    def test_radix_changes_register_output(self, debugger):
        assert debugger.read_registers("rax") == {"rax": 42}
        debugger.set_radix(16)
        assert debugger.read_registers("rax") == {"rax": "0x2a"}
        debugger.set_radix(10)
        assert debugger.read_registers("rax") == {"rax": 42}

    def test_radix_does_not_change_memory_format(self, mem_debugger):
        mem_debugger.set_radix(16)
        assert mem_debugger.examine_memory(0x1004, 1, 4, "d") == {0x1004: -1}

    def test_each_debugger_has_its_own_radix(self):
        a, b = Debugger(FakeControlUnit()), Debugger(FakeControlUnit())
        a.set_radix(16)
        assert b.num_rep == 10


# ---------------------------------------------------------------------------
# read_command loop
# ---------------------------------------------------------------------------


class TestReadCommand:
    @staticmethod
    def feed(monkeypatch, lines):
        it = iter(lines)
        monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))

    def test_returns_a_parsed_command(self, debugger, monkeypatch):
        self.feed(monkeypatch, ["break 7"])
        cmd = debugger.read_command()
        assert cmd.command is Command.BREAK and cmd.line == 7

    def test_blank_lines_reprompt_silently(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, ["", "   ", "run"])
        assert debugger.read_command().command is Command.RUN
        assert capsys.readouterr().out == ""

    def test_invalid_input_reprompts_and_prints_the_error_once(
        self, debugger, monkeypatch, capsys
    ):
        self.feed(monkeypatch, ["bogus", "break abc", "continue"])
        assert debugger.read_command().command is Command.CONTINUE
        out = capsys.readouterr().out
        # Regression: the error used to be printed twice
        assert out.count("Invalid command") == 1
        assert out.count("positive integer") == 1

    def test_many_bad_inputs_do_not_recurse_forever(self, debugger, monkeypatch):
        self.feed(monkeypatch, ["nope"] * 2000 + ["run"])
        assert debugger.read_command().command is Command.RUN


# ---------------------------------------------------------------------------
# End to end: raw input -> parsed command -> fetched values
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_info_registers_one_register_in_hex(self, debugger):
        debugger.set_radix(parse("radix hex").radix)
        cmd = parse("inf re rax")
        assert debugger.read_registers(cmd.register) == {"rax": "0x2a"}

    def test_examine_stack_through_a_register(self):
        cu = FakeControlUnit(memory=FakeMemory({0x1000: MEMORY_BYTES}))
        d = Debugger(cu)
        cmd = parse("x/2dw $rsp")
        values = d.examine_memory(
            d.resolve_address(cmd), cmd.count, cmd.unit, cmd.fmt
        )
        assert values == {0x1000: 0x12345678, 0x1004: -1}

    def test_examine_a_fixed_address_in_hex_after_radix_change(self):
        cu = FakeControlUnit(memory=FakeMemory({0x1000: MEMORY_BYTES}))
        d = Debugger(cu)
        d.set_radix(16)  # must not break register-based addressing
        cmd = parse("x/gx $rsp")
        values = d.examine_memory(
            d.resolve_address(cmd), cmd.count, cmd.unit, cmd.fmt
        )
        assert values == {0x1000: "0xffffffff12345678"}

    def test_break_then_continue_then_inspect(self, debugger, cu):
        cmd = parse("break 4")
        debugger.add_breakpoint(cmd.line)
        debugger.continue_execution()
        assert debugger.read_registers("rip") == {"rip": 3}

    def test_break_delete_list_cycle(self, debugger):
        for line in ("break 3", "break 8", "delete 3"):
            debugger.execute(debugger.parse(line))
        assert debugger.breakpoint_lines() == [8]


# ---------------------------------------------------------------------------
# Assumptions about the project's real REGISTER_PATTERN
# ---------------------------------------------------------------------------


class TestRealRegisterPattern:
    """Runs against the project's actual REGISTER_PATTERN (no fake swapped in)."""

    use_real_pattern = True

    @pytest.mark.parametrize(
        "name", ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r15"]
    )
    def test_64_bit_registers_are_accepted(self, name):
        assert ExecutionCommand(Command.INFO_REGISTERS, [name]).register == name

    @pytest.mark.parametrize("name", ["eax", "ax", "al", "ah", "r8d", "r8w", "r8b"])
    def test_regular_sub_registers_are_accepted(self, name):
        # _read_registers supports these through read_reg; the parser has to
        # let them through for that to be reachable.
        assert ExecutionCommand(Command.INFO_REGISTERS, [name]).register == name

    @pytest.mark.parametrize("name", ["si", "di", "bp", "sp", "sil", "dil", "bpl", "spl"])
    def test_irregular_sub_registers_are_accepted(self, name):
        # Registers_Interface handles these through EXTENDED_16BIT and
        # EXTENDED_8BIT (names that don't follow the e/r + x/l/h pattern).
        # If one fails here, REGISTER_PATTERN rejects a register the register
        # file supports, which affects the interpreter's own parsing too.
        assert ExecutionCommand(Command.INFO_REGISTERS, [name]).register == name

    @pytest.mark.parametrize("name", ["rip", "eflags", "zf", "cf", "sf", "of", "pf", "tf"])
    def test_names_the_debugger_adds_are_accepted(self, name):
        assert ExecutionCommand(Command.INFO_REGISTERS, [name]).register == name

    def test_dollar_prefix_is_accepted(self):
        assert ExecutionCommand(Command.INFO_REGISTERS, ["$rax"]).register == "rax"

    @pytest.mark.parametrize("name", ["notareg", "r16", "xyz", ""])
    def test_garbage_is_rejected(self, name):
        with pytest.raises(InvalidCommandError):
            ExecutionCommand(Command.INFO_REGISTERS, [name])


# ---------------------------------------------------------------------------
# Program text: format_instruction, source_lines, current_line, program_lines
# ---------------------------------------------------------------------------


def acts(exc):
    """A scripted behaviour for FakeControlUnit.on_rip: raise `exc` when stepped."""

    def _raise():
        raise exc

    return _raise


class TestFormatInstruction:
    @pytest.mark.parametrize(
        "tokens, expected",
        [
            (["mov", "rax", "1"], "mov rax, 1"),
            (["mov", "[rbp - 8]", "rax"], "mov [rbp - 8], rax"),
            (["push", "rbp"], "push rbp"),
            (["syscall"], "syscall"),
            (["_start:"], "_start:"),
            ([], ""),
            (("add", "rax", "rbx"), "add rax, rbx"),
            ("already text", "already text"),
        ],
    )
    def test_formats(self, tokens, expected):
        assert Debugger.format_instruction(tokens) == expected


class TestSourceLines:
    def test_one_entry_per_line_numbered_from_one(self, debugger, cu):
        lines = debugger.source_lines()
        assert [ln.number for ln in lines] == list(range(1, cu.program_length + 1))
        assert lines[0].text == "instr 0"
        assert all(isinstance(ln, SourceLine) for ln in lines)

    def test_current_line_flag_follows_rip(self, debugger, cu):
        cu.rip = 3
        flags = [ln.is_current for ln in debugger.source_lines()]
        assert flags.count(True) == 1 and flags[3] is True

    def test_breakpoint_flags(self, debugger):
        debugger.add_breakpoint(2)
        debugger.add_breakpoint(7)
        marked = [ln.number for ln in debugger.source_lines() if ln.has_breakpoint]
        assert marked == [2, 7]

    def test_a_line_can_be_current_and_have_a_breakpoint(self, debugger):
        debugger.add_breakpoint(1)
        first = debugger.source_lines()[0]
        assert first.is_current and first.has_breakpoint

    def test_label_lines_render_as_labels(self, cu):
        cu.text_section[0] = ["_start:"]
        assert Debugger(cu).source_lines()[0].text == "_start:"


class TestCurrentLine:
    def test_is_the_line_at_rip(self, debugger, cu):
        cu.rip = 4
        line = debugger.current_line()
        assert (line.number, line.text, line.is_current) == (5, "instr 4", True)

    def test_reports_a_breakpoint_on_it(self, debugger):
        debugger.add_breakpoint(1)
        assert debugger.current_line().has_breakpoint is True

    def test_none_when_the_program_is_over(self, debugger, cu):
        cu.finished = True
        assert debugger.current_line() is None

    @pytest.mark.parametrize("rip", [-1, 10, 99])
    def test_none_when_rip_is_outside_the_program(self, debugger, cu, rip):
        cu.rip = rip
        assert debugger.current_line() is None


class TestProgramLines:
    def test_returns_one_string_per_line(self, debugger, cu):
        rows = debugger.program_lines()
        # Regression: `result += "text"` on a list used to add single characters
        assert len(rows) == cu.program_length
        assert all(len(row) > 5 for row in rows)

    def test_markers(self, cu):
        d = Debugger(cu)
        cu.rip = 1
        d.add_breakpoint(1)  # a breakpoint that is not the current line
        d.add_breakpoint(2)  # a breakpoint on the current line
        rows = d.program_lines()
        assert rows[0] == "  b  1: instr 0"
        assert rows[1] == " -->b2: instr 1"
        assert rows[2] == "     3: instr 2"

    def test_current_line_marker_without_a_breakpoint(self, debugger):
        assert debugger.program_lines()[0] == " --> 1: instr 0"


# ---------------------------------------------------------------------------
# Running the program: step, run_chunk, continue_execution, Stop
# ---------------------------------------------------------------------------


class TestStep:
    def test_returns_a_stepped_stop_with_the_next_line(self, debugger, cu):
        stop = debugger.step()
        assert stop == Stop(StopReason.STEPPED, line=2)
        assert cu.steps == 1

    def test_the_last_instruction_finishes_the_program(self, cu):
        cu.rip, d = 9, Debugger(cu)
        assert d.step().reason is StopReason.FINISHED
        assert d.done

    def test_after_the_program_ended_nothing_runs(self, debugger, cu):
        cu.finished = True
        assert debugger.step().reason is StopReason.FINISHED
        assert cu.steps == 0

    def test_stepping_onto_a_breakpoint_is_still_just_a_step(self, debugger):
        debugger.add_breakpoint(2)
        assert debugger.step().reason is StopReason.STEPPED


class TestRunChunk:
    def test_stops_after_max_steps_and_reports_still_running(self, debugger, cu):
        assert debugger.run_chunk(3) is None
        assert cu.steps == 3 and not cu.finished

    def test_resumes_where_it_left_off(self, debugger, cu):
        debugger.run_chunk(3)
        debugger.run_chunk(3)
        assert cu.steps == 6 and cu.rip == 6

    def test_zero_steps_runs_nothing(self, debugger, cu):
        assert debugger.run_chunk(0) is None
        assert cu.steps == 0

    def test_stops_at_a_breakpoint_inside_the_chunk(self, debugger, cu):
        debugger.add_breakpoint(5)
        stop = debugger.run_chunk(100)
        assert stop == Stop(StopReason.BREAKPOINT, line=5)
        assert cu.steps == 4

    def test_a_breakpoint_just_beyond_the_chunk_is_not_hit_yet(self, debugger, cu):
        debugger.add_breakpoint(5)
        assert debugger.run_chunk(3) is None
        assert debugger.run_chunk(3) == Stop(StopReason.BREAKPOINT, line=5)

    def test_runs_to_the_end(self, debugger, cu):
        stop = debugger.run_chunk(100)
        assert stop == Stop(StopReason.FINISHED) and cu.finished

    def test_moves_past_the_breakpoint_it_is_standing_on(self, debugger, cu):
        debugger.add_breakpoint(1)  # rip is 0 right now
        stop = debugger.run_chunk(100)
        assert stop.reason is StopReason.FINISHED
        assert cu.steps == cu.program_length

    def test_after_the_program_ended_it_reports_the_end(self, debugger, cu):
        cu.finished = True
        assert debugger.run_chunk(5).reason is StopReason.FINISHED
        assert cu.steps == 0

    def test_a_front_end_loop_over_chunks_matches_continue(self, cu):
        d = Debugger(cu)
        d.add_breakpoint(8)
        stop, chunks = None, 0
        while stop is None:
            stop = d.run_chunk(2)
            chunks += 1
        assert stop == Stop(StopReason.BREAKPOINT, line=8)
        assert chunks == 4  # 7 steps in chunks of 2


class TestContinueExecution:
    def test_long_programs_run_to_the_end_across_many_chunks(self):
        cu = FakeControlUnit(program_length=2500)  # more than DEFAULT_CHUNK
        stop = Debugger(cu).continue_execution()
        assert stop.reason is StopReason.FINISHED and cu.steps == 2500

    def test_stops_at_a_breakpoint_beyond_the_first_chunk(self):
        cu = FakeControlUnit(program_length=2500)
        d = Debugger(cu)
        d.add_breakpoint(2000)
        assert d.continue_execution() == Stop(StopReason.BREAKPOINT, line=2000)


class TestFaultsAndExits:
    def test_cpu_exception_becomes_a_fault_stop(self):
        cu = FakeControlUnit(on_rip={3: acts(CPUException("division by zero"))})
        d = Debugger(cu)
        stop = d.continue_execution()
        assert stop == Stop(StopReason.FAULT, line=4, message="division by zero")
        assert d.done and cu.finished  # same handling as Control_Unit.run()

    def test_nothing_runs_after_a_fault(self):
        cu = FakeControlUnit(on_rip={3: acts(CPUException("boom"))})
        d = Debugger(cu)
        first = d.continue_execution()
        steps = cu.steps
        assert d.step() == first and d.run_chunk(5) == first
        assert cu.steps == steps

    def test_system_exit_with_a_number(self):
        cu = FakeControlUnit(on_rip={2: acts(SystemExit(3))})
        d = Debugger(cu)
        stop = d.continue_execution()
        assert stop == Stop(StopReason.EXITED, line=3, exit_code=3)
        assert d.done and not cu.finished  # the control unit itself is left alone

    def test_system_exit_with_an_exit_code_enum(self):
        from enum import Enum

        class FakeExitCode(Enum):
            INVALID_SYSCALL = 7

        cu = FakeControlUnit(on_rip={2: acts(SystemExit(FakeExitCode.INVALID_SYSCALL))})
        stop = Debugger(cu).continue_execution()
        assert stop.exit_code == 7 and stop.exit_name == "INVALID_SYSCALL"

    def test_bare_system_exit_means_code_zero(self):
        cu = FakeControlUnit(on_rip={0: acts(SystemExit())})
        assert Debugger(cu).step().exit_code == 0

    def test_system_exit_with_a_message(self):
        cu = FakeControlUnit(on_rip={0: acts(SystemExit("boom"))})
        stop = Debugger(cu).step()
        assert stop.exit_code is None and stop.message == "boom"

    def test_step_reports_an_exit_too(self):
        cu = FakeControlUnit(on_rip={0: acts(SystemExit(2))})
        assert Debugger(cu).step().reason is StopReason.EXITED

    def test_other_exceptions_are_not_swallowed(self):
        cu = FakeControlUnit(on_rip={0: acts(RuntimeError("a real bug"))})
        with pytest.raises(RuntimeError, match="a real bug"):
            Debugger(cu).step()

    def test_keyboard_interrupt_propagates_and_stdout_is_restored(self):
        import sys

        before = sys.stdout
        cu = FakeControlUnit(on_rip={0: acts(KeyboardInterrupt())})
        with pytest.raises(KeyboardInterrupt):
            Debugger(cu).run_chunk(5)
        assert sys.stdout is before


class TestProgramOutputCapture:
    @staticmethod
    def says(text):
        return lambda: print(text)

    def test_output_is_captured_not_printed(self, capsys):
        d = Debugger(FakeControlUnit(on_rip={1: self.says("hello")}))
        d.run_chunk(5)
        assert capsys.readouterr().out == ""
        assert d.take_output() == "hello\n"

    def test_take_output_clears_the_buffer(self):
        d = Debugger(FakeControlUnit(on_rip={0: self.says("once")}))
        d.step()
        assert d.take_output() == "once\n"
        assert d.take_output() == ""

    def test_output_accumulates_across_steps_and_chunks(self):
        d = Debugger(FakeControlUnit(on_rip={0: self.says("a"), 2: self.says("b")}))
        d.step()
        d.run_chunk(5)
        assert d.take_output() == "a\nb\n"

    def test_error_text_printed_before_an_exit_is_kept(self):
        def fail():
            print("INVALID INSTRUCTION")
            raise SystemExit(4)

        d = Debugger(FakeControlUnit(on_rip={0: fail}))
        d.step()
        assert d.take_output() == "INVALID INSTRUCTION\n"

    def test_nothing_is_captured_when_nothing_prints(self, debugger):
        debugger.continue_execution()
        assert debugger.take_output() == ""


# ---------------------------------------------------------------------------
# execute() and submit(): commands return CommandResult, nothing is printed
# ---------------------------------------------------------------------------


def run(debugger, line):
    """Parse a raw line and execute it."""
    return debugger.execute(debugger.parse(line))


@pytest.fixture
def big_debugger():
    """A debugger whose memory holds the bytes 0x00..0x1f at 0x1000."""
    cu = FakeControlUnit(memory=FakeMemory({0x1000: bytes(range(32))}))
    return Debugger(cu)


class TestExecuteDispatch:
    ARGS = {
        Command.RUN: [], Command.STEP: [], Command.CONTINUE: [],
        Command.BREAK: ["1"], Command.DELETE: ["1"],
        Command.INFO_BREAKPOINTS: [], Command.INFO_REGISTERS: [],
        Command.EXAMINE: ["", "0x1000"], Command.RADIX: [],
        Command.HELP: [], Command.QUIT: [],
    }  # fmt: skip

    @pytest.mark.parametrize("command", list(Command))
    def test_every_command_has_a_handler(self, command, mem_debugger):
        # Guards against adding a Command without teaching execute() about it
        assert command in self.ARGS, f"add test arguments for {command}"
        result = mem_debugger.execute(ExecutionCommand(command, self.ARGS[command]))
        assert isinstance(result, CommandResult) and result.command is command
        assert result.ok

    def test_execute_never_prints(self, mem_debugger, capsys):
        for command, args in TestExecuteDispatch.ARGS.items():
            mem_debugger.execute(ExecutionCommand(command, args))
        assert capsys.readouterr().out == ""

    def test_execute_never_exits_the_process(self, debugger):
        run(debugger, "quit")  # would raise SystemExit if it called sys.exit

    def test_unknown_commands_are_a_bug_not_user_error(self, debugger, monkeypatch):
        ec = ExecutionCommand(Command.RUN, [])
        monkeypatch.setattr(ec, "command", "bogus")
        with pytest.raises(ValueError, match="No handler"):
            debugger.execute(ec)

    def test_rejected_commands_come_back_as_failed_results(self, debugger):
        result = run(debugger, "info registers r8w")  # parses, but the register file lacks it
        assert result.ok is False
        assert result.command is Command.INFO_REGISTERS
        assert "Unknown register" in result.text

    def test_debugger_keeps_working_after_an_error(self, debugger):
        assert run(debugger, "x 0x9000").ok is False
        assert run(debugger, "break 3").ok is True
        assert debugger.breakpoint_lines() == [3]


class TestSubmit:
    def test_blank_input_is_an_empty_successful_result(self, debugger):
        for line in ("", "   ", "\t"):
            result = debugger.submit(line)
            assert result.ok and result.command is None and result.lines == []

    def test_unparseable_input_is_a_failed_result(self, debugger):
        result = debugger.submit("frobnicate")
        assert result.ok is False and result.command is None
        assert "Invalid command" in result.text

    def test_bad_arguments_are_a_failed_result(self, debugger):
        result = debugger.submit("break abc")
        assert result.ok is False and "positive integer" in result.text

    def test_valid_input_is_executed(self, debugger):
        result = debugger.submit("break 4")
        assert result.ok and result.breakpoints == [4]
        assert debugger.breakpoint_lines() == [4]

    def test_never_raises_for_user_input(self, debugger):
        for line in ("x", "x/zz 1", "info", "radix 3", "break 0", "info registers $", "\x00"):
            debugger.submit(line)


class TestResultBasics:
    def test_text_joins_lines(self):
        assert CommandResult(None, ["a", "b"]).text == "a\nb"

    def test_defaults(self):
        r = CommandResult(Command.RUN)
        assert r.ok and r.lines == [] and r.output == "" and r.stop is None
        assert r.registers is None and r.memory is None and r.breakpoints is None
        assert r.radix is None and r.quit is False

    def test_lines_are_not_shared_between_results(self):
        a, b = CommandResult(None), CommandResult(None)
        a.lines.append("x")
        assert b.lines == []


class TestExecuteBreakpoints:
    def test_break(self, debugger):
        r = run(debugger, "break 5")
        assert r.lines == ["Breakpoint set at line 5."] and r.breakpoints == [5]
        assert debugger.breakpoints == {4}

    def test_break_twice_reports_the_duplicate(self, debugger):
        run(debugger, "break 5")
        r = run(debugger, "break 5")
        assert r.lines == ["Breakpoint already set at line 5."]
        assert r.breakpoints == [5]

    def test_delete(self, debugger):
        run(debugger, "break 5")
        run(debugger, "break 7")
        r = run(debugger, "delete 5")
        assert r.lines == ["Breakpoint at line 5 removed."] and r.breakpoints == [7]

    def test_delete_missing(self, debugger):
        r = run(debugger, "delete 9")
        assert r.lines == ["No breakpoint at line 9."] and r.breakpoints == []

    def test_info_breakpoints(self, debugger):
        assert run(debugger, "info breakpoints").lines == ["No breakpoints set."]
        run(debugger, "break 8")
        run(debugger, "break 2")
        r = run(debugger, "i b")
        assert r.lines == ["Current breakpoints:", "  Line 2", "  Line 8"]
        assert r.breakpoints == [2, 8]


class TestExecuteRunControl:
    def test_step(self, debugger, cu):
        r = run(debugger, "stepi")
        assert r.stop == Stop(StopReason.STEPPED, line=2)
        assert r.lines == ["2: instr 1"] and cu.steps == 1

    def test_step_on_a_finished_program(self, debugger, cu):
        cu.finished = True
        r = run(debugger, "step")
        assert r.lines == ["Program has finished."] and r.stop is None
        assert cu.steps == 0

    @pytest.mark.parametrize("word", ["continue", "c", "run", "r"])
    def test_continue_and_run_stop_at_a_breakpoint(self, debugger, cu, word):
        debugger.add_breakpoint(5)
        r = run(debugger, word)
        assert cu.rip == 4
        assert r.stop == Stop(StopReason.BREAKPOINT, line=5)
        assert r.lines == ["Breakpoint hit at line 5.", "5: instr 4"]

    def test_continue_to_the_end(self, debugger, cu):
        r = run(debugger, "continue")
        assert cu.finished and r.lines == ["Program finished."]
        assert r.stop.reason is StopReason.FINISHED

    def test_continue_after_the_program_ended(self, debugger, cu):
        cu.finished = True
        r = run(debugger, "continue")
        assert r.lines == ["The program is not being run."] and cu.steps == 0

    def test_continue_twice_walks_through_breakpoints(self, debugger, cu):
        debugger.add_breakpoint(3)
        debugger.add_breakpoint(6)
        run(debugger, "continue")
        run(debugger, "continue")
        assert cu.rip == 5
        assert run(debugger, "continue").lines == ["Program finished."]

    def test_location_when_the_program_text_is_shorter_than_rip(self, cu):
        del cu.text_section[3:]
        d = Debugger(cu)
        cu.rip = 5
        assert run(d, "stepi").lines == ["At line 7."]

    def test_a_label_line_is_shown_as_the_label(self, cu):
        cu.text_section[1] = ["loop:"]
        assert run(Debugger(cu), "stepi").lines == ["2: loop:"]


class TestExecuteStopDescriptions:
    def test_cpu_exception(self):
        cu = FakeControlUnit(on_rip={3: acts(CPUException("division by zero"))})
        r = run(Debugger(cu), "continue")
        assert r.lines == ["CPU exception: division by zero at line 4."]
        assert r.stop.reason is StopReason.FAULT and r.ok

    def test_exit_with_a_code(self):
        cu = FakeControlUnit(on_rip={2: acts(SystemExit(3))})
        r = run(Debugger(cu), "continue")
        assert r.lines == ["Program exited with code 3 at line 3."]

    def test_exit_with_a_named_code(self):
        from enum import Enum

        class FakeExitCode(Enum):
            INVALID_SYSCALL = 7

        cu = FakeControlUnit(on_rip={2: acts(SystemExit(FakeExitCode.INVALID_SYSCALL))})
        r = run(Debugger(cu), "continue")
        assert r.lines == ["Program exited with code 7 (INVALID_SYSCALL) at line 3."]

    def test_exit_with_a_message(self):
        cu = FakeControlUnit(on_rip={2: acts(SystemExit("boom"))})
        r = run(Debugger(cu), "run")
        assert r.lines == ["Program exited: boom at line 3."]

    def test_stepping_into_an_exit(self):
        cu = FakeControlUnit(on_rip={0: acts(SystemExit(1))})
        r = run(Debugger(cu), "stepi")
        assert r.stop.reason is StopReason.EXITED and "code 1" in r.text

    def test_commands_after_an_exit(self):
        cu = FakeControlUnit(on_rip={0: acts(SystemExit(1))})
        d = Debugger(cu)
        run(d, "continue")
        assert run(d, "continue").lines == ["The program is not being run."]
        assert run(d, "step").lines == ["Program has finished."]


class TestExecuteProgramOutput:
    def test_output_goes_in_its_own_field_not_in_lines(self):
        cu = FakeControlUnit(on_rip={1: lambda: print("hello from the program")})
        r = run(Debugger(cu), "continue")
        assert r.output == "hello from the program\n"
        assert r.lines == ["Program finished."]

    def test_output_is_consumed_by_the_result(self):
        cu = FakeControlUnit(on_rip={0: lambda: print("x")})
        d = Debugger(cu)
        assert run(d, "stepi").output == "x\n"
        assert run(d, "stepi").output == ""

    def test_commands_that_do_not_run_the_program_have_no_output(self, debugger):
        assert run(debugger, "info registers").output == ""


class TestStopResult:
    def test_matches_what_execute_returns(self, cu):
        a, b = Debugger(cu), Debugger(FakeControlUnit())
        a.add_breakpoint(5)
        b.add_breakpoint(5)
        via_execute = run(a, "continue")
        stop = None
        while stop is None:  # what a UI does, so it can stay responsive
            stop = b.run_chunk(2)
        via_ui = b.stop_result(Command.CONTINUE, stop)
        assert via_ui == via_execute

    def test_collects_the_programs_output(self):
        d = Debugger(FakeControlUnit(on_rip={0: lambda: print("hi")}))
        stop = d.run_chunk(3)
        assert d.stop_result(None, Stop(StopReason.FINISHED)).output == "hi\n"
        assert stop is None


class TestExecuteRegisters:
    def test_all_registers(self, debugger):
        r = run(debugger, "info registers")
        assert r.registers["rax"] == 42 and r.registers["rbx"] == -1
        assert {"rip", "eflags", "ZF"} <= set(r.registers)
        assert len(r.lines) == len(FakeRegisters.GPRS) + 6 + 2
        assert r.registers == debugger.read_registers()

    def test_line_format(self, debugger):
        r = run(debugger, "info registers rax")
        assert r.lines == ["rax     42"] and r.registers == {"rax": 42}

    def test_follows_the_radix(self, debugger):
        run(debugger, "radix hex")
        assert run(debugger, "info registers rax").lines == ["rax     0x2a"]

    def test_eflags(self, debugger):
        run(debugger, "radix 16")
        assert run(debugger, "info registers eflags").lines == ["eflags  0x246"]


class TestExecuteExamine:
    def test_hex_is_zero_padded_to_the_unit_width(self, mem_debugger):
        assert run(mem_debugger, "x/2wx 0x1000").lines == ["0x1000:\t0x12345678\t0xffffffff"]
        assert run(mem_debugger, "x/bx 0x1008").lines == ["0x1008:\t0x01"]
        assert run(mem_debugger, "x/gx 0x1008").lines == ["0x1008:\t0x0000000000000001"]

    def test_decimal_formats(self, mem_debugger):
        assert run(mem_debugger, "x/2dw 0x1000").lines == ["0x1000:\t305419896\t-1"]
        assert run(mem_debugger, "x/2uw 0x1000").lines == ["0x1000:\t305419896\t4294967295"]

    def test_structured_data_is_returned_too(self, mem_debugger):
        r = run(mem_debugger, "x/2dw 0x1000")
        assert r.memory == {0x1000: 305419896, 0x1004: -1}
        assert (r.memory_unit, r.memory_fmt) == (4, "d")

    def test_register_as_the_address(self, mem_debugger):
        assert run(mem_debugger, "x/wx $rsp").lines == ["0x1000:\t0x12345678"]

    def test_register_address_still_works_in_hex_radix(self, mem_debugger):
        run(mem_debugger, "radix hex")
        assert run(mem_debugger, "x/wx $rsp").lines == ["0x1000:\t0x12345678"]

    @pytest.mark.parametrize(
        "unit_letter, per_row", [("b", 8), ("h", 8), ("w", 4), ("g", 2)]
    )
    def test_rows_wrap_like_gdb(self, big_debugger, unit_letter, per_row):
        lines = run(big_debugger, f"x/{per_row + 1}{unit_letter}x 0x1000").lines
        assert len(lines) == 2
        assert len(lines[0].split("\t")) == per_row + 1  # address + cells
        assert len(lines[1].split("\t")) == 2  # address + the one leftover cell

    def test_second_row_starts_at_the_right_address(self, big_debugger):
        lines = run(big_debugger, "x/10bx 0x1000").lines
        assert lines[0].startswith("0x1000:") and lines[1] == "0x1008:\t0x08\t0x09"

    def test_unmapped_memory_is_a_failed_result(self, mem_debugger):
        r = run(mem_debugger, "x/gx 0x5000")
        assert r.ok is False and "Cannot access memory at 0x5000" in r.text
        assert r.memory is None

    def test_a_failed_examine_has_no_partial_rows(self, mem_debugger):
        r = run(mem_debugger, "x/5wx 0x1000")  # the 5th word is past the mapped 16 bytes
        assert r.lines == [r.lines[0]] and "0x1010" in r.lines[0] and r.memory is None


class TestExecuteRadixHelpQuit:
    def test_query(self, debugger):
        r = run(debugger, "radix")
        assert r.lines == ["Current output radix: decimal (base 10)."] and r.radix == 10

    @pytest.mark.parametrize(
        "word, base, label",
        [("hex", 16, "hexadecimal"), ("2", 2, "binary"), ("oct", 8, "octal"), ("dec", 10, "decimal")],
    )
    def test_change(self, debugger, word, base, label):
        r = run(debugger, f"radix {word}")
        assert debugger.num_rep == base and r.radix == base
        assert r.lines == [f"Output radix set to {label} (base {base})."]

    def test_help_lists_every_command(self, debugger):
        text = run(debugger, "help").text
        assert text.startswith("Debugger commands")
        for command in Command:
            assert command.value.split()[0] in text or command.value in text

    def test_quit_asks_the_front_end_to_close(self, debugger):
        r = run(debugger, "quit")
        assert r.quit is True and r.lines == ["Exiting debugger."]

    def test_other_commands_do_not_ask_to_quit(self, debugger):
        assert run(debugger, "radix").quit is False


# ---------------------------------------------------------------------------
# The plain-terminal front end: read_command() and repl()
# ---------------------------------------------------------------------------


class TestRepl:
    @staticmethod
    def feed(monkeypatch, items):
        """Feed input() a script; exception instances in it are raised."""
        it = iter(items)

        def fake_input(prompt=""):
            item = next(it)
            if isinstance(item, BaseException):
                raise item
            return item

        monkeypatch.setattr(builtins, "input", fake_input)

    def test_runs_commands_until_quit_and_returns(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, ["break 5", "continue", "info registers rip", "quit"])
        debugger.repl()  # returns normally: it does not exit the process
        assert capsys.readouterr().out.splitlines() == [
            "1: instr 0",
            "Breakpoint set at line 5.",
            "Breakpoint hit at line 5.",
            "5: instr 4",
            "rip     4",
            "Exiting debugger.",
        ]

    def test_program_output_is_printed_before_the_stop_message(self, monkeypatch, capsys):
        cu = FakeControlUnit(on_rip={1: lambda: print("hello")})
        self.feed(monkeypatch, ["continue", "quit"])
        Debugger(cu).repl()
        lines = capsys.readouterr().out.splitlines()
        assert lines.index("hello") < lines.index("Program finished.")

    def test_invalid_commands_do_not_end_the_session(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, ["bogus", "break x", "", "break 2", "quit"])
        debugger.repl()
        out = capsys.readouterr().out
        assert "Invalid command" in out and "positive integer" in out
        assert "Breakpoint set at line 2." in out and debugger.breakpoints == {1}

    def test_failed_commands_are_printed(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, ["x 0x9000", "quit"])
        debugger.repl()
        assert "Cannot access memory at 0x9000" in capsys.readouterr().out

    def test_ctrl_d_leaves_the_loop(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, [EOFError()])
        debugger.repl()
        assert "Exiting debugger." in capsys.readouterr().out

    def test_ctrl_c_at_the_prompt_is_ignored(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, [KeyboardInterrupt(), "break 3", "quit"])
        debugger.repl()
        out = capsys.readouterr().out
        assert "Quit (type 'quit' to exit)." in out and "Breakpoint set at line 3." in out

    def test_session_survives_the_program_finishing(self, debugger, monkeypatch, capsys):
        self.feed(monkeypatch, ["continue", "continue", "step", "quit"])
        debugger.repl()
        out = capsys.readouterr().out
        assert "Program finished." in out
        assert "The program is not being run." in out
        assert "Program has finished." in out

    def test_no_location_is_shown_when_already_finished(self, debugger, cu, monkeypatch, capsys):
        cu.finished = True
        self.feed(monkeypatch, ["quit"])
        debugger.repl()
        assert capsys.readouterr().out.splitlines() == ["Exiting debugger."]


# ---------------------------------------------------------------------------
# The front-end contract: only the console front end may touch the terminal
# ---------------------------------------------------------------------------


class TestNoTerminalAccessOutsideTheConsoleFrontEnd:
    """
    A GUI/TUI front end owns the terminal, so print/input/sys.exit anywhere
    else in the debugger would corrupt it or kill the app.
    """

    ALLOWED_FUNCTIONS = {"read_command", "repl"}

    @staticmethod
    def offenders(module):
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(module))
        found = []

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.stack = []

            def visit_FunctionDef(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node):
                f = node.func
                name = (
                    f.id if isinstance(f, ast.Name)
                    else f"{f.value.id}.{f.attr}"
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    else None
                )
                if name in {"print", "input", "sys.exit", "exit", "quit"}:
                    found.append((name, self.stack[-1] if self.stack else "<module>"))
                self.generic_visit(node)

        Visitor().visit(tree)
        return found

    def test_only_read_command_and_repl_use_the_terminal(self):
        bad = [
            (call, fn)
            for call, fn in self.offenders(dbg)
            if fn not in self.ALLOWED_FUNCTIONS
        ]
        assert bad == []

    def test_the_check_itself_can_see_violations(self):
        # Sanity check of the checker: the console front end does use print/input
        found = {fn for _, fn in self.offenders(dbg)}
        assert found == self.ALLOWED_FUNCTIONS


class TestArgumentRulesFallback:
    def test_a_command_without_argument_rules_is_a_bug_not_user_error(self):
        with pytest.raises(ValueError, match="No argument rules"):
            ExecutionCommand("bogus", [])  # type: ignore[arg-type]