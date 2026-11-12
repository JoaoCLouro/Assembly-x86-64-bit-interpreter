"""
Tests for Control_Unit (execution/control_unit.py).

Control_Unit.__init__ wires up real Data_Path/ALU/FPU/Syscall instances and
real register/memory bridges, none of which should be real for a unit test
of Control_Unit's own dispatch logic. Every test here bypasses __init__ via
object.__new__ and injects Mocks for every collaborator (registers, memory,
data_path, alu, fpu, syscall, instruction_parser) plus plain Python objects
for the parsed-section attributes (text_section, labels, etc.).

patter_matching_helpers.INSTRUCTIONS is a module-level dict loaded from a
real JSON file in the actual project; tests monkeypatch it directly via
control_unit.INSTRUCTIONS so is_valid_instruction/valid_operand_count are
testable without that file.

execute_state_command's interactive input() loop is intentionally out of
scope for this suite.
"""

from unittest.mock import Mock

import pytest
from _pytest.monkeypatch import MonkeyPatch

from interpreter._src.parsing import control_unit as cu_module
from interpreter._src.parsing.control_unit import Control_Unit, CPUException
from interpreter._src.parsing.instruction_parser import Operand
from interpreter.exit_codes import ExitCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def control_unit():
    """
    Builds a Control_Unit instance without running __init__, so no real
    Data_Path/ALU/FPU/Syscall/register/memory objects are constructed.
    Every collaborator is a bare Mock; individual tests configure whichever
    methods/attributes they need.
    """
    unit = object.__new__(Control_Unit)
    unit.registers = Mock()
    unit.memory = Mock()
    unit.data_path = Mock()
    unit.alu = Mock()
    unit.fpu = Mock()
    unit.syscall = Mock()
    unit.rip = 0
    unit.text_section = []
    unit.rodata_section = {}
    unit.data_section = {}
    unit.bss_section = {}
    unit.labels = {}
    unit.constants = {}
    unit.finished = False
    unit.current_fu = "cpu"
    unit.current_instruction = ""
    unit.op1 = Operand()
    unit.op2 = Operand()
    unit.instruction_parser = Mock()
    return unit


@pytest.fixture
def instructions_patch(monkeypatch):
    """
    Replaces the module-level INSTRUCTIONS dict that is_valid_instruction/
    valid_operand_count read from, so tests don't depend on the real
    valid_instructions.json content.
    """

    def _apply(mapping: dict) -> None:
        monkeypatch.setattr(cu_module, "INSTRUCTIONS", mapping)

    return _apply


# ---------------------------------------------------------------------------
# is_valid_instruction
# ---------------------------------------------------------------------------


class TestIsValidInstruction:
    def test_syscall_always_sets_cpu_fu_and_returns_true(
        self, control_unit, instructions_patch
    ):
        instructions_patch(
            {}
        )  # not even present in INSTRUCTIONS; syscall short-circuits
        control_unit.current_fu = "alu"  # prove it gets overwritten

        result = control_unit._is_valid_instruction("syscall")

        assert result is True
        assert control_unit.current_fu == "cpu"

    def test_known_instruction_sets_matching_fu(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}, "fpu": {"fadd": 2}})

        result = control_unit._is_valid_instruction("add")

        assert result is True
        assert control_unit.current_fu == "alu"

    def test_known_instruction_in_different_fu(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}, "fpu": {"fadd": 2}})

        result = control_unit._is_valid_instruction("fadd")

        assert result is True
        assert control_unit.current_fu == "fpu"

    def test_unknown_instruction_returns_false(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}})

        result = control_unit._is_valid_instruction("nonexistent_op")

        assert result is False

    def test_unknown_instruction_does_not_change_current_fu(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.current_fu = "data_path"

        control_unit._is_valid_instruction("nonexistent_op")

        assert control_unit.current_fu == "data_path"


# ---------------------------------------------------------------------------
# get_current_fu
# ---------------------------------------------------------------------------


class TestGetCurrentFu:
    def test_returns_data_path_instance(self, control_unit):
        control_unit.current_fu = "data_path"
        assert control_unit._get_current_fu() is control_unit.data_path

    def test_returns_alu_instance(self, control_unit):
        control_unit.current_fu = "alu"
        assert control_unit._get_current_fu() is control_unit.alu

    def test_returns_fpu_instance(self, control_unit):
        control_unit.current_fu = "fpu"
        assert control_unit._get_current_fu() is control_unit.fpu

    def test_unknown_fu_raises_value_error(self, control_unit):
        control_unit.current_fu = "not_a_real_fu"
        with pytest.raises(ValueError):
            control_unit._get_current_fu()


# ---------------------------------------------------------------------------
# valid_operand_count
# ---------------------------------------------------------------------------


class TestValidOperandCount:
    def test_matching_operand_count_returns_true(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.current_fu = "alu"
        control_unit.current_instruction = "add"
        control_unit.op1.set("rax", 1, 0, 8)
        control_unit.op2.set(
            "rbx", 1, 1, 8
        )  # both valid -> count 2, matches expected 2

        assert control_unit._valid_operand_count() is True

    def test_mismatched_operand_count_returns_false(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.current_fu = "alu"
        control_unit.current_instruction = "add"
        control_unit.op1.set("rax", 1, 0, 8)
        control_unit.op2.clear()  # only 1 valid operand, expected 2

        assert control_unit._valid_operand_count() is False

    def test_zero_operand_instruction(self, control_unit, instructions_patch):
        instructions_patch({"data_path": {"ret": 0}})
        control_unit.current_fu = "data_path"
        control_unit.current_instruction = "ret"
        control_unit.op1.clear()
        control_unit.op2.clear()

        assert control_unit._valid_operand_count() is True


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


class TestFetch:
    def test_label_only_line_is_skipped(self, control_unit, instructions_patch):
        instructions_patch({})
        control_unit.text_section = [["my_label"]]
        control_unit.labels = {"my_label": 0}
        control_unit.rip = 0

        control_unit._fetch()  # should return without raising or setting instruction

        control_unit.instruction_parser.parse.assert_not_called()

    def test_valid_instruction_line_parses_and_sets_state(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["add", "rax", "rbx"]]
        control_unit.rip = 0
        control_unit.op1.set("rax", 1, 0, 8)
        control_unit.op2.set("rbx", 1, 1, 8)  # so valid_operand_count() passes

        control_unit._fetch()

        assert control_unit.current_instruction == "add"
        assert control_unit.current_fu == "alu"
        control_unit.instruction_parser.parse.assert_called_once()

    def test_empty_line_exits_with_software_error(
        self, control_unit, instructions_patch
    ):
        instructions_patch({})
        control_unit.text_section = [[]]
        control_unit.rip = 0

        with pytest.raises(SystemExit) as exc_info:
            control_unit._fetch()

        assert exc_info.value.code == ExitCode.SOFTWARE_ERROR

    def test_invalid_instruction_raises_value_error(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["totally_bogus_instruction"]]
        control_unit.rip = 0

        with pytest.raises(ValueError):
            control_unit._fetch()

    def test_invalid_operand_count_exits(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["add", "rax"]]
        control_unit.rip = 0
        control_unit.op1.set("rax", 1, 0, 8)
        control_unit.op2.clear()  # only 1 valid operand, expected 2

        with pytest.raises(SystemExit) as exc_info:
            control_unit._fetch()

        assert exc_info.value.code == ExitCode.INVALID_INSTRUCTION_SYNTAX
        # op1/op2 should have been cleared on the invalid-count path
        assert control_unit.op1.valid is False
        assert control_unit.op2.valid is False

    def test_parser_syntax_error_exits(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["add", "rax", "rbx"]]
        control_unit.rip = 0
        control_unit.instruction_parser.parse.side_effect = SyntaxError("bad syntax")

        with pytest.raises(SystemExit) as exc_info:
            control_unit._fetch()

        assert exc_info.value.code == ExitCode.INVALID_INSTRUCTION_SYNTAX

    def test_parser_value_error_exits(self, control_unit, instructions_patch):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["add", "rax", "rbx"]]
        control_unit.rip = 0
        control_unit.instruction_parser.parse.side_effect = ValueError("bad value")

        with pytest.raises(SystemExit) as exc_info:
            control_unit._fetch()

        assert exc_info.value.code == ExitCode.INVALID_INSTRUCTION_SYNTAX


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_cpu_fu_calls_syscall(self, control_unit):
        control_unit.current_fu = "cpu"
        control_unit.syscall.syscall.return_value = 0

        control_unit._execute("syscall")

        control_unit.syscall.syscall.assert_called_once()

    def test_cpu_fu_invalid_syscall_exits(self, control_unit):
        control_unit.current_fu = "cpu"
        control_unit.syscall.syscall.return_value = -1

        with pytest.raises(SystemExit) as exc_info:
            control_unit._execute("syscall")

        assert exc_info.value.code == ExitCode.INVALID_SYSCALL

    def test_alu_fu_loads_values_and_executes(self, control_unit):
        control_unit.current_fu = "alu"
        control_unit.alu.execute.return_value = None
        control_unit.rip = 5

        control_unit._execute("add")

        control_unit.alu.load_values.assert_called_once_with(
            "add", control_unit.op1, control_unit.op2
        )
        control_unit.alu.execute.assert_called_once()
        assert control_unit.rip == 5  # unchanged since execute() returned None

    def test_fpu_fu_loads_values_and_executes(self, control_unit):
        control_unit.current_fu = "fpu"
        control_unit.fpu.execute.return_value = None

        control_unit._execute("fadd")

        control_unit.fpu.load_values.assert_called_once_with(
            "fadd", control_unit.op1, control_unit.op2
        )
        control_unit.fpu.execute.assert_called_once()

    def test_data_path_call_instruction_loads_rip_first(self, control_unit):
        control_unit.current_fu = "data_path"
        control_unit.rip = 42
        control_unit.data_path.execute.return_value = None

        control_unit._execute("call")

        control_unit.data_path.load_rip.assert_called_once_with(42)
        control_unit.data_path.load_values.assert_called_once_with(
            "call", control_unit.op1, control_unit.op2
        )

    def test_data_path_non_call_instruction_does_not_load_rip(self, control_unit):
        control_unit.current_fu = "data_path"
        control_unit.data_path.execute.return_value = None

        control_unit._execute("jmp")

        control_unit.data_path.load_rip.assert_not_called()

    def test_functional_unit_return_value_updates_rip(self, control_unit):
        control_unit.current_fu = "data_path"
        control_unit.rip = 10
        control_unit.data_path.execute.return_value = 99  # e.g. a jump target

        control_unit._execute("jmp")

        assert control_unit.rip == 99

    def test_functional_unit_runtime_error_exits(self, control_unit):
        control_unit.current_fu = "alu"
        control_unit.alu.execute.side_effect = RuntimeError("bad op")

        with pytest.raises(SystemExit) as exc_info:
            control_unit._execute("add")

        assert exc_info.value.code == ExitCode.INVALID_INSTRUCTION_SYNTAX


# ---------------------------------------------------------------------------
# step
# ---------------------------------------------------------------------------


class TestStep:
    def test_step_fetches_executes_and_advances_rip(
        self, control_unit, instructions_patch, monkeypatch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["add", "rax", "rbx"]]
        control_unit.rip = 0
        control_unit.op1.set("rax", 1, 0, 8)
        control_unit.op2.set("rbx", 1, 1, 8)
        control_unit.alu.execute.return_value = None

        control_unit._step()

        assert control_unit.rip == 1  # advanced past the executed instruction

    def test_step_past_end_of_text_section_forces_exit(self, control_unit):
        control_unit.text_section = []
        control_unit.rip = 0

        with pytest.raises(SystemExit) as exc_info:
            control_unit._step()

        assert exc_info.value.code == ExitCode.NO_EXIT_FOUND

    def test_step_label_line_does_not_execute_but_advances_rip(
        self, control_unit, instructions_patch
    ):
        instructions_patch({})
        control_unit.text_section = [["my_label"]]
        control_unit.labels = {"my_label": 0}
        control_unit.rip = 0

        control_unit._step()

        control_unit.alu.execute.assert_not_called()
        control_unit.fpu.execute.assert_not_called()
        control_unit.data_path.execute.assert_not_called()
        assert control_unit.rip == 1

    def test_step_value_error_from_fetch_exits_with_code_1(
        self, control_unit, instructions_patch
    ):
        instructions_patch({"alu": {"add": 2}})
        control_unit.text_section = [["totally_bogus"]]
        control_unit.rip = 0

        with pytest.raises(SystemExit) as exc_info:
            control_unit._step()

        assert exc_info.value.code == ExitCode.INVALID_OR_UNSUPPORTED_INSTRUCTION


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_increments_rip_before_looping(self, control_unit, monkeypatch):
        control_unit.rip = 0
        control_unit.finished = True  # loop body never runs
        control_unit.registers.read_trap_flag.return_value = 0

        control_unit.run()

        assert control_unit.rip == 1

    def test_run_calls_step_until_finished(self, control_unit, monkeypatch):
        control_unit.rip = -1  # becomes 0 after the pre-increment
        control_unit.registers.read_trap_flag.return_value = 0
        call_count = {"n": 0}

        def fake_step(self):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                self.finished = True

        # Control_Unit uses __slots__, so instance-level monkeypatching of a
        # method (monkeypatch.setattr(control_unit, "step", ...)) is not
        # possible — there's no per-instance __dict__ to shadow the class
        # attribute. Patch the class method instead.
        monkeypatch.setattr(Control_Unit, "_step", fake_step)

        control_unit.run()

        assert call_count["n"] == 3

    def test_run_catches_exceptions_from_step_and_marks_finished(
        self,
        control_unit: Control_Unit,
        monkeypatch: MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        control_unit.rip = -1
        control_unit.registers.read_trap_flag.return_value = 0

        def raising_step(self):
            raise CPUException("something went wrong")

        monkeypatch.setattr(type(control_unit), "_step", raising_step)

        control_unit.run()

        assert control_unit.finished is True
        assert "CPU Exception" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# print_section
# ---------------------------------------------------------------------------


class TestPrintSection:
    def test_empty_section_prints_placeholder(self, control_unit, capsys):
        control_unit._print_section({})

        captured = capsys.readouterr()
        assert "(empty section)" in captured.out

    def test_prints_all_variables_with_correct_signed_values(
        self, control_unit, capsys
    ):
        store = {}

        def make_var(base, size, value):
            data = value.to_bytes(size, "little", signed=True)
            for i, b in enumerate(data):
                store[base + i] = b
            return {"size": size, "addresses": list(range(base, base + size))}

        section = {
            "positive_var": make_var(0x1000, 4, 100),
            "negative_var": make_var(0x2000, 8, -50),
        }

        def fake_read_bytes(addr, size):
            return bytes(store.get(addr + i, 0) for i in range(size))

        control_unit.memory.read_bytes.side_effect = fake_read_bytes

        control_unit._print_section(section)

        captured = capsys.readouterr()
        assert "positive_var: 0x64" in captured.out
        assert "negative_var: 0xffffffffffffffce" in captured.out

    def test_preserves_original_variable_order_in_output(self, control_unit, capsys):
        store = {}
        section = {}
        names_in_order = [f"var_{i}" for i in range(10)]
        for i, name in enumerate(names_in_order):
            base = 0x1000 + i * 8
            data = i.to_bytes(8, "little", signed=True)
            for j, b in enumerate(data):
                store[base + j] = b
            section[name] = {"size": 8, "addresses": list(range(base, base + 8))}

        control_unit.memory.read_bytes.side_effect = lambda addr, size: bytes(
            store.get(addr + i, 0) for i in range(size)
        )

        control_unit._print_section(section)

        captured = capsys.readouterr()
        lines = [l for l in captured.out.strip().split("\n") if l]
        printed_names = [l.split(":")[0] for l in lines]
        assert printed_names == names_in_order
