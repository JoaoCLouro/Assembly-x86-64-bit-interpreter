from ..bridges.data_memory import Data_Memory
from ..bridges.register_manager import Registers_Interface
from ..helpers.my_types import LabelMap
from ..parsing.instruction_parser import Operand
from ..parsing.patter_matching_helpers import INSTRUCTIONS

# Cached O(1) lookup dictionary for data path instruction opcodes
DATA_PATH_OPCODES = {
    name.lower(): index for index, name in enumerate(INSTRUCTIONS["data_path"])
}


class Data_Path:
    """
    Data Path component responsible for parsing, validating, and executing assembly
    instructions related to data movement, stack management, and control flow operations.

    Interfaces with register state, data memory, and label tables to execute
    instructions (e.g., MOV, LEA, PUSH, POP, CALL, RET, and conditional jumps)
    while maintaining instruction pointer (RIP) alignment and operand validation.
    """

    __slots__ = [
        "_execute_data_path_map",
        "labels",
        "memory",
        "op1",
        "op2",
        "opcode",
        "registers",
        "rip",
    ]

    def __init__(
        self, registers: Registers_Interface, memory: Data_Memory, labels: LabelMap
    ) -> None:

        self.registers = registers
        self.memory = memory
        self.labels = labels
        self.rip = -1

        self._execute_data_path_map = (
            self.execute_lea,  # 0: lea
            self.execute_mov,  # 1: mov
            self.execute_push,  # 2: push
            self.execute_pop,  # 3: pop
            self.execute_call,  # 4: call
            self.execute_ret,  # 5: ret
            self.execute_jmp,  # 6: jmp
            self.execute_je,  # 7: je
            self.execute_je,  # 8: jz (alias)
            self.execute_jne,  # 9: jne
            self.execute_jne,  # 10: jnz (alias)
            self.execute_jb,  # 11: jb
            self.execute_jb,  # 12: jc (alias)
            self.execute_jb,  # 13: jnae (alias)
            self.execute_jnb,  # 14: jnb
            self.execute_jnb,  # 15: jnc (alias)
            self.execute_jnb,  # 16: jae (alias)
            self.execute_ja,  # 17: ja
            self.execute_ja,  # 18: jnbe (alias)
            self.execute_jbe,  # 19: jbe
            self.execute_jbe,  # 20: jna (alias)
            self.execute_jl,  # 21: jl
            self.execute_jl,  # 22: jnge (alias)
            self.execute_jge,  # 23: jge
            self.execute_jge,  # 24: jnl (alias)
            self.execute_jg,  # 25: jg
            self.execute_jg,  # 26: jnle (alias)
            self.execute_jle,  # 27: jle
            self.execute_jle,  # 28: jng (alias)
            self.execute_js,  # 29: js
            self.execute_jns,  # 30: jns
            self.execute_jo,  # 31: jo
            self.execute_jno,  # 32: jno
            self.execute_jp,  # 33: jp
            self.execute_jp,  # 34: jpe (alias)
            self.execute_jnp,  # 35: jnp
            self.execute_jnp,  # 36: jpo (alias)
        )

        self.opcode: int
        self.op1: Operand
        self.op2: Operand

    def load_values(self, instruction: str, op1: Operand, op2: Operand) -> None:
        """
        Initializes the operands and instruction's opcode to be make the execution runnable

        :param instruction: Instruction to execute
        :type instruction: str
        :param op1: Operand obj for the first operand
        :param op2: Operand obj for the second operand
        """
        self.opcode = self.get_opcode(instruction)

        if op1 and op1.is_valid():
            self.op1 = op1

        if op2 and op2.is_valid():
            self.op2 = op2

    def load_rip(self, rip: int) -> None:
        """
        Loads the rip parameter of this class if a call operation is about to be performed

        :param rip: Current Instruction Pointer of control unit
        :type rip: int
        """
        self.rip = rip

    def execute(self):
        """
        Executes the instructions valid in the data path

        :raises RuntimeError: If comes across any invalid condition to the operation's execution or an error is raised during execution
        """
        try:
            self.validate_data_path_instruction()
            return self._execute_data_path_map[self.opcode]()
        except SyntaxError as e:
            print(e)
            raise RuntimeError(e) from e
        except NotImplementedError as e:
            print(e)
            raise RuntimeError(e) from e

    # ----------------
    # Static helpers
    # ----------------

    @staticmethod
    def get_opcode(instruction: str) -> int:
        """
        Retrieves the numeric opcode corresponding to the given data path instruction (e.g., mov, lea, jmp).

        :param instruction: Name of the instruction (e.g., "mov", "lea", "jmp")
        :type instruction: str
        :return: 0-based opcode index if valid, or -1 if the instruction is unsupported
        :rtype: int
        """
        return DATA_PATH_OPCODES.get(instruction.lower(), -1)

    # ----------------------
    # Conditions Validation
    # ----------------------

    def validate_data_path_instruction(self) -> None:
        """
        Routes the parsed integer opcode to the correct validation logic.

        :param opcode: The 0-based ordinal index of the data path instruction.
        :raises NotImplementedError: If an invalid opcode is provided.
        """
        opcode = self.opcode

        if opcode == 0:
            self.validate_lea_conditions()
        elif opcode == 1:
            self.validate_mov_conditions()
        elif opcode == 2 or opcode == 3:
            self.validate_stack_condition()
        elif opcode == 4:
            self.validate_call_condition()
        elif opcode == 5:
            self.validate_ret_condition()
        elif 6 <= opcode < len(self._execute_data_path_map):
            self.validate_jump_conditions()
        else:
            raise NotImplementedError(
                f"Validation for data path opcode {opcode} is not implemented."
            )

    def validate_lea_conditions(self) -> None:
        """
        Validates the conditions for the LEA (Load Effective Address) instruction.
        Optimized for high-performance instruction decoding.

        :raises SyntaxError: If any LEA execution rules are violated.
        """
        op1 = self.op1
        op2 = self.op2

        # 1. Fast-fail validity check
        if not op1.is_valid() or not op2.is_valid():
            raise SyntaxError(
                "Both destination and source operands must exist for the LEA instruction."
            )

        # 2. Destination MUST be a register (Type 1)
        if op1.type != 1:
            raise SyntaxError("The destination operand for LEA must be a register.")

        # 3. Source MUST be a memory expression (Type 0)
        if op2.type != 0:
            raise SyntaxError(
                "The source operand for LEA must be a memory address expression."
            )

    def validate_mov_conditions(self) -> None:
        """
        Validates the conditions for the MOV instruction to be executed correctly.
        Optimized for high-performance instruction decoding.

        :raises SyntaxError: If any of the MOV instruction execution rules are violated.
        """

        op1 = self.op1
        op2 = self.op2

        # 1. Fast-fail validity check
        if not op1.is_valid() or not op2.is_valid():
            raise SyntaxError(
                "Both destination and source operands must exist for the MOV instruction."
            )

        op1_type = op1.type
        op2_type = op2.type

        # 2. Destination cannot be an immediate
        if op1_type == 2:
            raise SyntaxError(
                "The destination operand cannot be an immediate value or constant for the MOV instruction."
            )

        dest_is_mem = op1_type == 0

        # 3. Read-Only Memory Protection (.rodata segment validation)
        if dest_is_mem and op1.address < 0x600000:
            raise SyntaxError(
                "The destination memory address lies in read-only memory (.rodata/.text) and cannot be written to."
            )

        # 4. Memory-to-Memory check
        if dest_is_mem and op2_type == 0:
            raise SyntaxError(
                "The source and destination operands cannot both be memory addresses for the MOV instruction."
            )

        op1_size = op1.size
        op2_size = op2.size

        # 5. Operand size mismatch check
        if op1_size and op2_size and op2_type != 2 and op1_size != op2_size:
            raise SyntaxError(
                f"Operand size mismatch for MOV instruction: "
                f"Destination size is {op1_size} byte(s), but source size is {op2_size} byte(s)."
            )

        # 6. High-register byte access mismatch
        if op1.is_high and not op2.is_high and op2_size == 8:
            raise SyntaxError(
                "Cannot mix high 8-bit registers (AH, BH, CH, DH) with 64-bit registers or extended byte registers."
            )

    def validate_stack_condition(self) -> None:
        """
        Validates the conditions for all stack instructions.

        :raises SyntaxError: If stack instructions execution rules are violated.
        """
        op1 = self.op1
        op2 = self.op2

        if not op1.is_valid():
            raise SyntaxError("Stack instructions require exactly one operand.")
        if op2.is_valid():
            raise SyntaxError("Stack instructions cannot take a second operand.")

        if op1.type == 2 and self.opcode != 2:
            raise SyntaxError(
                "Pop instruction requires a Register or a memory operator as arguments. No other operator type are supported"
            )

        if self.opcode == 3 and op1.type == 0 and op1.address < 0x600000:
            raise SyntaxError(
                "The destination memory address lies in read-only memory (.rodata/.text) and cannot be written to."
            )

    def validate_call_condition(self) -> None:
        """
        Validates the conditions for the call instruction.

        :raises SyntaxError: If call instructions execution rules are violated.
        """
        op1 = self.op1
        op2 = self.op2

        if not op1.is_valid():
            raise SyntaxError("Call instructions require exactly one operand.")
        if op2.is_valid():
            raise SyntaxError("Call instructions cannot take a second operand.")
        if self.rip == -1:
            raise SyntaxError("RIP was not loaded.")
        if op1.expression not in self.labels:
            raise SyntaxError(
                f"Undefined label '{op1.expression}' for call instruction."
            )

    def validate_ret_condition(self) -> None:
        """
        Validates the conditions for the ret instruction.

        :raises SyntaxError: If ret instructions execution rules are violated.
        """
        op1 = self.op1
        op2 = self.op2

        if op1.is_valid() or op2.is_valid():
            raise SyntaxError("Ret instructions require no operands.")

    def validate_jump_conditions(self) -> None:
        """
        Validates the conditions for all branching and jump instructions (jmp, je, jne, etc.).
        Optimized for high-performance instruction decoding.

        :raises SyntaxError: If jump instruction execution rules are violated.
        """
        # Cache references locally
        op1 = self.op1
        op2 = self.op2

        # 1. Must have exactly one valid operand (the destination)
        if not op1.is_valid():
            raise SyntaxError(
                "Control flow instructions require exactly one destination operand."
            )

        # 2. Ensure the parser didn't accidentally attach a second operand
        if op2.is_valid():
            raise SyntaxError("Control flow instructions cannot take a second operand.")

    # -----------------
    # Implementations
    # -----------------

    def execute_lea(self) -> None:
        """
        LEA (Load Effective Address):
        Loads the calculated memory address of op2 directly into the destination register op1.
        Does NOT dereference memory.

        :raises SyntaxError: if the write fails
        """
        op1 = self.op1
        op2 = self.op2

        # LEA ignores memory contents and writes the computed address into op1
        effective_address = op2.address
        # op1 is already verified to be a register
        try:
            self.registers.write_reg(op1.expression, effective_address)
        except ValueError as e:
            raise SyntaxError from e

    def execute_mov(self) -> None:
        """
        MOV: Copies the value from op2 (Immediate, Register, or Memory)
        into op1 (Register or Memory).

        :raises SyntaxError: if the write or read fails
        """
        op1 = self.op1
        op2 = self.op2
        op2_type = op2.type
        size = op1.size

        # 1. Read value from source (op2)
        if op2_type == 2:  # IMMEDIATE
            val = op2.address  # Immediate value is stored in the address field
        elif op2_type == 1:  # REGISTER
            try:
                val = self.registers.read_reg(op2.expression)
            except ValueError as e:
                raise SyntaxError from e
        else:  # MEMORY (op2_type == 0)
            try:
                val = self.memory.read_bytes(op2.address, op2.size)
            except MemoryError as e:
                raise SyntaxError from e

        # 2. Write value to destination (op1)
        if op1.type == 1:  # REGISTER
            val = int.from_bytes(val, "little") if isinstance(val, bytes) else val
            try:
                self.registers.write_reg(op1.expression, val)
            except ValueError as e:
                raise SyntaxError from e
        else:  # MEMORY
            if isinstance(val, int):
                mask = (1 << (size * 8)) - 1
                val = (val & mask).to_bytes(size, byteorder="little")
            try:
                self.memory.write_bytes(op1.address, val, op1.size)
            except MemoryError as e:
                raise SyntaxError from e

    def execute_push(self) -> None:
        """
        PUSH: pushes the value from op1 (Immediate, Register, or Memory)
        into the stack (using the data memory interface for the stack).

        :raises RuntimeError: if the push operation runs into a stack overflow
        """

        op1 = self.op1
        op1_type = op1.type
        size = op1.size or 8

        # 1. Read value from source (op2)
        if op1_type == 2:  # IMMEDIATE
            val = op1.address  # Immediate value is stored in the address field
        elif op1_type == 1:  # REGISTER
            try:
                val = self.registers.read_reg(op1.expression)
            except ValueError as e:
                raise RuntimeError(e) from e
        else:  # MEMORY (op1_type == 0)
            try:
                val = self.memory.read_bytes(op1.address, op1.size)
            except MemoryError as e:
                raise RuntimeError(e) from e

        if isinstance(val, int):
            mask = (1 << (size * 8)) - 1
            val = (val & mask).to_bytes(size, byteorder="little")

        try:
            self.memory.push(val)
        except MemoryError as e:
            raise RuntimeError(e) from e

    def execute_pop(self) -> None:
        """
        POP: pops the value from the stack
        into op1 (using the data memory interface for the stack).

        :raises RuntimeError: if the pop operation runs into a stack underflow

        """

        op1 = self.op1
        op1_type = op1.type

        try:
            val = self.memory.pop()
        except MemoryError as e:
            raise RuntimeError(e) from e

        if op1_type == 1:  # REGISTER
            val = int.from_bytes(val, "little") if isinstance(val, bytes) else val  # type: ignore
            try:
                self.registers.write_reg(op1.expression, val, bool(op1.is_signed))
            except ValueError as e:
                raise RuntimeError(e) from e

        elif op1_type == 0:  # MEMORY
            try:
                self.memory.write_bytes(op1.address, val, op1.size)
            except MemoryError as e:
                raise RuntimeError(e) from e

    def execute_call(self) -> int:
        """
        Calls a function by pushing the current rip to the stack and jumping to the function.\n
        'call' functionality expects a ret somewhere over in the code but won't bother if none is find and will behave as a normal 'jmp' operation

        :param label: label of the function to call
        :type label: str
        :raises RuntimeError: if the push operation runs into a stack overflow
        """
        try:
            return_address_bytes = (self.rip).to_bytes(8, "little")
            self.memory.push(return_address_bytes)
        except MemoryError as e:
            raise RuntimeError(e) from e
        return self.execute_jmp()

    def execute_ret(self) -> int:
        """
        Jumps back to the address previously pushed by the 'call' operation.\n
        Stack management must be correct to work as intended.

        :raises RuntimeError: if the pop operation runs into a stack underflow
        """
        try:
            target_rip = int.from_bytes(self.memory.pop(), "little")
            self.rip = target_rip
            return target_rip
        except (MemoryError, ValueError) as e:
            raise RuntimeError(e) from e

    def execute_jmp(self) -> int:
        try:
            target_rip = self.labels[self.op1.expression]
            self.rip = target_rip
            return target_rip
        except KeyError:
            self.rip = -1
            return -1

    def execute_je(self) -> int | None:
        """Jump if Equal / Jump if Zero (ZF == 1)."""
        if self.registers.read_zero():
            return self.execute_jmp()
        return None

    def execute_jne(self) -> int | None:
        """Jump if Not Equal / Jump if Not Zero (ZF == 0)."""
        if not self.registers.read_zero():
            return self.execute_jmp()
        return None

    def execute_jb(self) -> int | None:
        """Jump if Below / Jump if Carry (CF == 1). Unsigned comparison."""
        if self.registers.read_carry():
            return self.execute_jmp()
        return None

    def execute_jnb(self) -> int | None:
        """Jump if Not Below / Not Carry (CF == 0)."""
        if not self.registers.read_carry():
            return self.execute_jmp()
        return None

    def execute_ja(self) -> int | None:
        """Jump if Above (CF == 0 and ZF == 0). Unsigned comparison."""
        if not self.registers.read_carry() and not self.registers.read_zero():
            return self.execute_jmp()
        return None

    def execute_jbe(self) -> int | None:
        """Jump if Below or Equal (CF == 1 or ZF == 1)."""
        if self.registers.read_carry() or self.registers.read_zero():
            return self.execute_jmp()
        return None

    def execute_jl(self) -> int | None:
        """Jump if Less (SF != OF). Signed comparison."""
        sf = self.registers.read_sign()
        of = self.registers.read_overflow()
        if sf != of:
            return self.execute_jmp()
        return None

    def execute_jg(self) -> int | None:
        """Jump if Greater (ZF == 0 and SF == OF). Signed comparison."""
        zf = self.registers.read_zero()
        sf = self.registers.read_sign()
        of = self.registers.read_overflow()
        if not zf and (sf == of):
            return self.execute_jmp()
        return None

    def execute_jge(self) -> int | None:
        """Jump if Greater or Equal (SF == OF)."""
        if self.registers.read_sign() == self.registers.read_overflow():
            return self.execute_jmp()
        return None

    def execute_jle(self) -> int | None:
        """Jump if Less or Equal (ZF == 1 or SF != OF)."""
        if self.registers.read_zero() or (
            self.registers.read_sign() != self.registers.read_overflow()
        ):
            return self.execute_jmp()
        return None

    def execute_js(self) -> int | None:
        """Jump if Sign (SF == 1). Negative result."""
        if self.registers.read_sign():
            return self.execute_jmp()
        return None

    def execute_jns(self) -> int | None:
        """Jump if Not Sign / Positive (SF == 0)."""
        if not self.registers.read_sign():
            return self.execute_jmp()
        return None

    def execute_jo(self) -> int | None:
        """Jump if Overflow (OF == 1)."""
        if self.registers.read_overflow():
            return self.execute_jmp()
        return None

    def execute_jno(self) -> int | None:
        """Jump if Overflow (OF == 1)."""
        if not self.registers.read_overflow():
            return self.execute_jmp()
        return None

    def execute_jp(self) -> int | None:
        """Jump if Parity Even (PF == 1)."""
        if self.registers.read_parity():
            return self.execute_jmp()
        return None

    def execute_jnp(self) -> int | None:
        """Jump if Parity Odd (PF == 0)."""
        if not self.registers.read_parity():
            return self.execute_jmp()
        return None
