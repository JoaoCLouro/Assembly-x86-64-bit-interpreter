"""
Tests for the GDB-style debugger (command parsing, breakpoints, execution
control, register/memory fetching, radix handling).

Run with:  pytest tests/test_debugger.py -v

The debugger is tested against small in-memory fakes of the control unit,
register file and memory, so no compiled C library (libreg.so) is needed.
Only the debugger module itself and `Control_Unit._format_value` (a pure
static helper) come from the real project.

Set DEBUGGER_MODULE below to wherever the debugger lives in your package.

Two groups of tests deserve a note:
  - TestRealRegisterPattern runs against your real REGISTER_PATTERN (every
    other test swaps in a known pattern so they don't depend on it). If one
    of those fails, the parser rejects a register name the rest of the
    debugger supports.
  - The two tests marked xfail document a known issue: continue_execution
    checks for a breakpoint before stepping, so continuing from a breakpoint
    makes no progress. They are strict, so they will start failing as soon as
    the bug is fixed; remove the marker at that point.
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

    def __init__(self, registers=None, memory=None, rip=0, program_length=10):
        self.registers = registers or FakeRegisters()
        self.memory = memory or FakeMemory()
        self.rip = rip
        self.program_length = program_length
        self.finished = False
        self.steps = 0

    def _step(self):
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
    return Debugger(FakeControlUnit())._match_command(line)


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

    def test_list_empty(self, debugger, capsys):
        debugger.list_breakpoints()
        assert capsys.readouterr().out.strip() == "No breakpoints set."

    def test_list_is_sorted_numerically_and_compact(self, debugger, capsys):
        for line in (10, 2, 33):
            debugger.add_breakpoint(line)
        debugger.list_breakpoints()
        # Regression: the original printed a blank line after every entry
        assert capsys.readouterr().out.splitlines() == [
            "Current breakpoints:",
            "  Line 2",
            "  Line 10",
            "  Line 33",
        ]

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
        result = debugger.continue_execution()
        assert cu.finished and cu.steps == cu.program_length
        assert result is cu

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

    @pytest.mark.xfail(
        strict=True,
        reason="continue_execution checks the breakpoint before stepping, "
        "so it cannot leave a breakpoint it is stopped on",
    )
    def test_continue_from_a_breakpoint_makes_progress(self, cu):
        cu.rip = 2
        d = Debugger(cu)
        d.add_breakpoint(3)  # rip == 2, where we are standing
        d.continue_execution()
        assert cu.steps >= 1

    @pytest.mark.xfail(
        strict=True,
        reason="same issue: a second continue never moves past the first stop",
    )
    def test_second_continue_reaches_the_next_breakpoint(self, debugger, cu):
        debugger.add_breakpoint(3)
        debugger.add_breakpoint(6)
        debugger.continue_execution()
        assert cu.rip == 2
        debugger.continue_execution()
        assert cu.rip == 5

    def test_quit_exits_cleanly(self, debugger, capsys):
        with pytest.raises(SystemExit) as exc:
            debugger.quit()
        assert exc.value.code == 0
        assert "Exiting debugger" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Register fetching
# ---------------------------------------------------------------------------


class TestReadRegisters:
    def test_all_registers_decimal(self, debugger):
        state = debugger._read_registers()
        expected_keys = (
            set(FakeRegisters.GPRS)
            | {"ZF", "CF", "SF", "OF", "PF", "TF"}
            | {"rip", "eflags"}
        )
        assert set(state) == expected_keys
        assert state["rax"] == 42 and state["rbx"] == -1
        assert state["ZF"] == 1 and state["CF"] == 0

    def test_returns_values_and_prints_nothing(self, debugger, capsys):
        result = debugger._read_registers()
        assert isinstance(result, dict)
        assert capsys.readouterr().out == ""

    def test_rip_reflects_the_control_unit(self, debugger, cu):
        cu.rip = 7
        assert debugger._read_registers("rip") == {"rip": 7}
        cu.rip = 9
        assert debugger._read_registers("rip") == {"rip": 9}

    def test_eflags_decoded_from_read_flags_bytes(self, cu):
        cu.registers = FakeRegisters(eflags=0x246)
        d = Debugger(cu)
        assert d._read_registers("eflags") == {"eflags": 0x246}
        assert d._read_registers("eflags", 16) == {"eflags": "0x246"}
        assert d._read_registers("eflags", 2) == {"eflags": "0b1001000110"}
        assert d._read_registers("eflags", 8) == {"eflags": "0o1106"}

    def test_eflags_uses_all_four_bytes(self, cu):
        cu.registers = FakeRegisters(eflags=0x80000246)
        assert Debugger(cu)._read_registers("eflags", 16) == {"eflags": "0x80000246"}

    def test_eflags_never_goes_through_read_reg(self, debugger, cu):
        # "eflags" starts with "e", so read_reg would mistake it for a 32-bit
        # alias of a register called "rflags"
        debugger._read_registers("eflags")
        assert "eflags" not in cu.registers.read_reg_calls

    @pytest.mark.parametrize("name", ["rax", "RAX", "$rax", "$RAX"])
    def test_single_register_name_forms(self, debugger, name):
        assert debugger._read_registers(name) == {"rax": 42}

    @pytest.mark.parametrize(
        "name, key, value",
        [("zf", "ZF", 1), ("$CF", "CF", 0), ("pf", "PF", 1), ("tf", "TF", 0)],
    )
    def test_single_flags(self, debugger, name, key, value):
        assert debugger._read_registers(name) == {key: value}

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
        state = debugger._read_registers(num_rep=num_rep)
        assert state["rax"] == rax and state["rbx"] == rbx

    def test_rip_follows_the_representation(self, debugger, cu):
        cu.rip = 255
        assert debugger._read_registers("rip", 16) == {"rip": "0xff"}
        assert debugger._read_registers("rip", 2) == {"rip": "0b11111111"}

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
        assert Debugger(cu)._read_registers(name) == {name: expected}

    def test_sub_registers_in_hex(self, cu):
        cu.registers = FakeRegisters(values={"rax": -1})
        d = Debugger(cu)
        assert d._read_registers("eax", 16) == {"eax": "0xffffffff"}
        assert d._read_registers("al", 16) == {"al": "0xff"}

    @pytest.mark.parametrize("name", ["foo", "r99", "$", "xmm0"])
    def test_unknown_register(self, debugger, name):
        with pytest.raises(InvalidCommandError, match="Unknown register"):
            debugger._read_registers(name)

    @pytest.mark.parametrize("num_rep", [0, 1, 3, 7, 12, 32])
    def test_unsupported_representation(self, debugger, num_rep):
        with pytest.raises(InvalidCommandError, match="UNSUPPORTED"):
            debugger._read_registers(num_rep=num_rep)

    def test_default_representation_is_the_debugger_radix(self, debugger):
        debugger.num_rep = 16
        assert debugger._read_registers("rax") == {"rax": "0x2a"}

    def test_explicit_representation_does_not_change_the_radix(self, debugger):
        debugger.num_rep = 16
        assert debugger._read_registers("rax", num_rep=10) == {"rax": 42}
        assert debugger.num_rep == 16


# ---------------------------------------------------------------------------
# Address resolution
# ---------------------------------------------------------------------------


class TestResolveAddress:
    def test_numeric_address(self, debugger):
        cmd = ExecutionCommand(Command.EXAMINE, ["", "0x1000"])
        assert debugger._resolve_address(cmd) == 0x1000

    def test_register_address(self, debugger):
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        assert debugger._resolve_address(cmd) == 0x1000

    def test_negative_register_is_masked_to_unsigned(self, cu):
        cu.registers = FakeRegisters(values={"rsp": -8})
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        assert Debugger(cu)._resolve_address(cmd) == 0xFFFFFFFFFFFFFFF8

    @pytest.mark.parametrize("radix", [2, 8, 10, 16])
    def test_always_an_int_whatever_the_radix(self, debugger, radix):
        debugger.num_rep = radix
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$rsp"])
        result = debugger._resolve_address(cmd)
        assert isinstance(result, int) and result == 0x1000

    def test_flag_register_as_address(self, debugger):
        # rip/flags are legal register names, so they must resolve to numbers
        cmd = ExecutionCommand(Command.EXAMINE, ["", "$zf"])
        assert debugger._resolve_address(cmd) == 1


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
        result = mem_debugger._examine_memory(0x1000, 1, 4, "x")
        assert isinstance(result, dict)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize(
        "unit, expected",
        [(1, "0x78"), (2, "0x5678"), (4, "0x12345678"), (8, "0xffffffff12345678")],
    )
    def test_hex_by_unit_size_is_little_endian(self, mem_debugger, unit, expected):
        assert mem_debugger._examine_memory(0x1000, 1, unit, "x") == {0x1000: expected}

    def test_multiple_units_have_consecutive_addresses(self, mem_debugger):
        result = mem_debugger._examine_memory(0x1000, 3, 4, "x")
        assert result == {
            0x1000: "0x12345678",
            0x1004: "0xffffffff",
            0x1008: "0x1",
        }

    def test_results_are_in_address_order(self, mem_debugger):
        result = mem_debugger._examine_memory(0x1000, 8, 1, "x")
        assert list(result) == [0x1000 + i for i in range(8)]

    def test_signed_decimal(self, mem_debugger):
        result = mem_debugger._examine_memory(0x1000, 2, 4, "d")
        assert result == {0x1000: 0x12345678, 0x1004: -1}

    def test_unsigned_decimal(self, mem_debugger):
        result = mem_debugger._examine_memory(0x1000, 2, 4, "u")
        assert result == {0x1000: 0x12345678, 0x1004: 4294967295}

    def test_byte_sign_handling(self, mem_debugger):
        assert mem_debugger._examine_memory(0x1004, 1, 1, "d") == {0x1004: -1}
        assert mem_debugger._examine_memory(0x1004, 1, 1, "u") == {0x1004: 255}
        assert mem_debugger._examine_memory(0x1004, 1, 1, "x") == {0x1004: "0xff"}

    def test_eight_byte_values(self, mem_debugger):
        value = 0xFFFFFFFF12345678
        assert mem_debugger._examine_memory(0x1000, 1, 8, "u") == {0x1000: value}
        assert mem_debugger._examine_memory(0x1000, 1, 8, "d") == {
            0x1000: value - (1 << 64)
        }
        assert mem_debugger._examine_memory(0x1008, 1, 8, "x") == {0x1008: "0x1"}

    def test_defaults_are_one_eight_byte_hex_value(self, mem_debugger):
        assert mem_debugger._examine_memory(0x1000) == {0x1000: "0xffffffff12345678"}

    def test_zero_count_returns_nothing(self, mem_debugger):
        assert mem_debugger._examine_memory(0x1000, 0, 4, "x") == {}

    def test_unmapped_address(self, mem_debugger):
        with pytest.raises(InvalidCommandError, match="0x2000"):
            mem_debugger._examine_memory(0x2000, 1, 4, "x")

    def test_error_names_the_first_unreadable_unit(self, mem_debugger):
        # 16 bytes are mapped; the fifth 4-byte unit starts at 0x1010
        with pytest.raises(InvalidCommandError, match="0x1010"):
            mem_debugger._examine_memory(0x1000, 5, 4, "x")

    def test_unit_straddling_the_end_of_memory_fails(self, mem_debugger):
        with pytest.raises(InvalidCommandError):
            mem_debugger._examine_memory(0x100C, 1, 8, "x")


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
        assert debugger._read_registers("rax") == {"rax": 42}
        debugger.set_radix(16)
        assert debugger._read_registers("rax") == {"rax": "0x2a"}
        debugger.set_radix(10)
        assert debugger._read_registers("rax") == {"rax": 42}

    def test_radix_does_not_change_memory_format(self, mem_debugger):
        mem_debugger.set_radix(16)
        assert mem_debugger._examine_memory(0x1004, 1, 4, "d") == {0x1004: -1}

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
        assert debugger._read_registers(cmd.register) == {"rax": "0x2a"}

    def test_examine_stack_through_a_register(self):
        cu = FakeControlUnit(memory=FakeMemory({0x1000: MEMORY_BYTES}))
        d = Debugger(cu)
        cmd = parse("x/2dw $rsp")
        values = d._examine_memory(
            d._resolve_address(cmd), cmd.count, cmd.unit, cmd.fmt
        )
        assert values == {0x1000: 0x12345678, 0x1004: -1}

    def test_examine_a_fixed_address_in_hex_after_radix_change(self):
        cu = FakeControlUnit(memory=FakeMemory({0x1000: MEMORY_BYTES}))
        d = Debugger(cu)
        d.set_radix(16)  # must not break register-based addressing
        cmd = parse("x/gx $rsp")
        values = d._examine_memory(
            d._resolve_address(cmd), cmd.count, cmd.unit, cmd.fmt
        )
        assert values == {0x1000: "0xffffffff12345678"}

    def test_break_then_continue_then_inspect(self, debugger, cu):
        cmd = parse("break 4")
        debugger.add_breakpoint(cmd.line)
        debugger.continue_execution()
        assert debugger._read_registers("rip") == {"rip": 3}

    def test_break_delete_list_cycle(self, debugger, capsys):
        for line in ("break 3", "break 8", "delete 3"):
            cmd = parse(line)
            if cmd.command is Command.BREAK:
                debugger.add_breakpoint(cmd.line)
            else:
                debugger.remove_breakpoint(cmd.line)
        debugger.list_breakpoints()
        assert capsys.readouterr().out.splitlines() == [
            "Current breakpoints:",
            "  Line 8",
        ]


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