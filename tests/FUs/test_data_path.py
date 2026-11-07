from unittest.mock import MagicMock, Mock

import pytest

# Adjust import path as needed for your module
from interpreter._src.functional_units.data_path import Data_Path

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_registers():
    regs = MagicMock()
    # Default flag states
    regs.read_zero.return_value = False
    regs.read_carry.return_value = False
    regs.read_sign.return_value = False
    regs.read_overflow.return_value = False
    regs.read_parity.return_value = False
    return regs


@pytest.fixture
def mock_memory():
    return MagicMock()


@pytest.fixture
def mock_labels():
    return {"main": 100, "loop": 200, "target": 300, "func": 500}


@pytest.fixture
def data_path(mock_registers, mock_memory, mock_labels):
    return Data_Path(registers=mock_registers, memory=mock_memory, labels=mock_labels)


def create_mock_operand(
    is_valid=True,
    type_=1,
    address=0x1000,
    size=8,
    expression="rax",
    is_high=False,
    is_signed=False,
):
    op = Mock()
    op.is_valid.return_value = is_valid
    op.type = type_  # 0: Memory, 1: Register, 2: Immediate
    op.address = address
    op.size = size
    op.expression = expression
    op.is_high = is_high
    op.is_signed = is_signed
    return op


# -----------------------------------------------------------------------------
# Test Static Helpers & Loading
# -----------------------------------------------------------------------------


def test_get_opcode():
    assert Data_Path.get_opcode("mov") == 1
    assert Data_Path.get_opcode("LEA") == 0
    assert Data_Path.get_opcode("invalid_instr") == -1


def test_load_values(data_path):
    op1 = create_mock_operand(type_=1)
    op2 = create_mock_operand(type_=3)
    data_path.load_values("mov", op1, op2)

    assert data_path.opcode == 1
    assert data_path.op1 == op1
    assert data_path.op2 == op2


def test_load_rip(data_path):
    data_path.load_rip(42)
    assert data_path.rip == 42


# -----------------------------------------------------------------------------
# Test Validations
# -----------------------------------------------------------------------------


class TestValidations:
    def test_validate_lea_success(self, data_path):
        data_path.op1 = create_mock_operand(type_=1)  # Register
        data_path.op2 = create_mock_operand(type_=0)  # Memory
        data_path.opcode = 0
        data_path.validate_data_path_instruction()  # Should not raise

    def test_validate_lea_invalid_dest(self, data_path):
        data_path.op1 = create_mock_operand(type_=0)  # Memory instead of Register
        data_path.op2 = create_mock_operand(type_=0)
        with pytest.raises(
            SyntaxError, match="destination operand for LEA must be a register"
        ):
            data_path.validate_lea_conditions()

    def test_validate_mov_rodata_write(self, data_path):
        data_path.op1 = create_mock_operand(
            type_=0, address=0x400000
        )  # Address < 0x600000
        data_path.op2 = create_mock_operand(type_=1)
        with pytest.raises(SyntaxError, match="read-only memory"):
            data_path.validate_mov_conditions()

    def test_validate_mov_mem_to_mem(self, data_path):
        data_path.op1 = create_mock_operand(type_=0, address=0x700000)
        data_path.op2 = create_mock_operand(type_=0, address=0x800000)
        with pytest.raises(SyntaxError, match="cannot both be memory addresses"):
            data_path.validate_mov_conditions()

    def test_validate_mov_size_mismatch(self, data_path):
        data_path.op1 = create_mock_operand(type_=1, size=4)
        data_path.op2 = create_mock_operand(type_=1, size=8)
        with pytest.raises(SyntaxError, match="Operand size mismatch"):
            data_path.validate_mov_conditions()

    def test_validate_stack_two_operands(self, data_path):
        data_path.op1 = create_mock_operand(type_=1)
        data_path.op2 = create_mock_operand(type_=1)
        with pytest.raises(SyntaxError, match="cannot take a second operand"):
            data_path.validate_stack_condition()

    def test_validate_call_no_rip(self, data_path):
        data_path.op1 = create_mock_operand(type_=1)
        data_path.op2 = create_mock_operand(is_valid=False)
        data_path.rip = -1
        with pytest.raises(SyntaxError, match="RIP was not loaded"):
            data_path.validate_call_condition()

    def test_validate_ret_with_operand(self, data_path):
        data_path.op1 = create_mock_operand(type_=1)
        data_path.op2 = create_mock_operand(is_valid=False)
        with pytest.raises(SyntaxError, match="Ret instructions require no operands"):
            data_path.validate_ret_condition()


# -----------------------------------------------------------------------------
# Test Data Movement & Stack Instructions
# -----------------------------------------------------------------------------


class TestDataExecution:
    def test_execute_lea(self, data_path, mock_registers):
        data_path.op1 = create_mock_operand(type_=1, expression="rax")
        data_path.op2 = create_mock_operand(type_=2, address=0x7FFFF000)

        data_path.execute_lea()
        mock_registers.write_reg.assert_called_once_with("rax", 0x7FFFF000)

    def test_execute_mov_reg_to_reg(self, data_path, mock_registers):
        data_path.op1 = create_mock_operand(type_=1, expression="rax")
        data_path.op2 = create_mock_operand(type_=1, expression="rbx")
        mock_registers.read_reg.return_value = 1234

        data_path.execute_mov()

        mock_registers.read_reg.assert_called_once_with("rbx")
        mock_registers.write_reg.assert_called_once_with("rax", 1234)

    def test_execute_mov_imm_to_mem(self, data_path, mock_memory):
        data_path.op1 = create_mock_operand(type_=0, address=0x700000, size=4)
        data_path.op2 = create_mock_operand(type_=2, address=0xFF)  # Immediate 0xFF

        data_path.execute_mov()

        # 0xFF as 4-byte little endian: b'\xff\x00\x00\x00'
        mock_memory.write_bytes.assert_called_once_with(
            0x700000, b"\xff\x00\x00\x00", 4
        )

    def test_execute_push_and_pop(self, data_path, mock_registers, mock_memory):
        # Push
        data_path.op1 = create_mock_operand(type_=1, expression="rax", size=8)
        mock_registers.read_reg.return_value = 0x123456789ABCDEF0
        data_path.execute_push()

        mock_memory.push.assert_called_once()

        # Pop
        mock_memory.pop.return_value = b"\xf0\xde\xbc\x9a\x78\x56\x34\x12"
        data_path.execute_pop()
        mock_registers.write_reg.assert_called_with("rax", 0x123456789ABCDEF0, False)


# -----------------------------------------------------------------------------
# Test Control Flow & Jump Execution
# -----------------------------------------------------------------------------


class TestControlFlow:
    def test_execute_jmp_updates_rip(self, data_path):
        data_path.op1 = create_mock_operand(expression="target")
        target_pc = data_path.execute_jmp()

        assert target_pc == 300
        assert data_path.rip == 300

    def test_execute_call_and_ret(self, data_path, mock_memory):
        # Setup Call
        data_path.load_rip(10)
        data_path.op1 = create_mock_operand(expression="func")

        target_pc = data_path.execute_call()

        mock_memory.push.assert_called_once_with((10).to_bytes(8, "little"))
        assert target_pc == 500
        assert data_path.rip == 500

        # Setup Ret
        mock_memory.pop.return_value = (10).to_bytes(8, "little")
        ret_pc = data_path.execute_ret()

        assert ret_pc == 10
        assert data_path.rip == 10

    def test_execute_je_taken_mutates_rip(self, data_path, mock_registers):
        mock_registers.read_zero.return_value = True
        data_path.op1 = create_mock_operand(expression="target")

        result_pc = data_path.execute_je()

        assert result_pc == 300
        assert data_path.rip == 300

    def test_execute_je_not_taken_leaves_rip(self, data_path, mock_registers):
        mock_registers.read_zero.return_value = False
        data_path.rip = 5
        data_path.op1 = create_mock_operand(expression="target")

        result_pc = data_path.execute_je()

        assert result_pc is None
        assert data_path.rip == 5  # Unchanged

    def test_execute_jl_signed_condition(self, data_path, mock_registers):
        # SF != OF -> Condition met
        mock_registers.read_sign.return_value = True
        mock_registers.read_overflow.return_value = False
        data_path.op1 = create_mock_operand(expression="loop")

        result_pc = data_path.execute_jl()

        assert result_pc == 200
        assert data_path.rip == 200
