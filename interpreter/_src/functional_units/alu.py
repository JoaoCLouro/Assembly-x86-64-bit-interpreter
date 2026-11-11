#!/usr/bin/env python3

import ctypes
import os

from interpreter._paths import SRC_ROOT

from ..bridges.data_memory import Data_Memory
from ..bridges.register_manager import Registers_Interface
from ..parsing.instruction_parser import Operand as OP
from ..parsing.patter_matching_helpers import INSTRUCTIONS
from .common_classes import CPURegs, Info, Table

# Lookup opcodes table
ALU_OPCODES = {name.lower(): index for index, name in enumerate(INSTRUCTIONS["alu"])}


class ALU:
    __slots__ = ["lib", "state"]

    def __init__(
        self,
        registers: Registers_Interface,
        memory: Data_Memory,
        libops_path: str = os.path.join(SRC_ROOT, "lib/liboperations.so"),
    ) -> None:
        self.lib = ctypes.CDLL(os.path.abspath(libops_path))

        self.lib.create_operand_state.argtypes = []
        self.lib.create_operand_state.restype = ctypes.POINTER(Info)

        self.lib.free_operand_state.argtypes = [ctypes.POINTER(Info)]
        self.lib.free_operand_state.restype = None

        self.lib.set_registers_ref.argtypes = [
            ctypes.POINTER(Info),
            ctypes.POINTER(CPURegs),
        ]
        self.lib.set_registers_ref.restype = None

        self.lib.set_table_ref.argtypes = [ctypes.POINTER(Info), ctypes.POINTER(Table)]
        self.lib.set_table_ref.restype = None

        # Matches operations.h: (Info*, operand, address, size, op_type, is_high, is_signed)
        self.lib.set_operand_info.argtypes = [
            ctypes.POINTER(Info),  # Info*
            ctypes.c_char_p,  # operand slot ("op1" / "op2")
            ctypes.c_longlong,  # address
            ctypes.c_uint8,  # size
            ctypes.c_uint8,  # op_type (OpType enum)
            ctypes.c_uint8,  # is_high
            ctypes.c_uint8,  # is_signed
        ]
        self.lib.set_operand_info.restype = None

        # uint8_t in the header, not c_int
        self.lib.set_instruction.argtypes = [ctypes.POINTER(Info), ctypes.c_uint8]
        self.lib.set_instruction.restype = None

        self.lib.clean.argtypes = [ctypes.POINTER(Info)]
        self.lib.clean.restype = None

        self.lib.dispatch.argtypes = [ctypes.POINTER(Info)]
        self.lib.dispatch.restype = ctypes.c_uint8

        # Prepares all needed info
        self.state = self.lib.create_operand_state()
        self.lib.set_registers_ref(
            self.state, ctypes.cast(registers.regs, ctypes.POINTER(CPURegs))
        )
        self.lib.set_table_ref(
            self.state, ctypes.cast(memory.table, ctypes.POINTER(Table))
        )

    def __del__(self) -> None:
        # Best-effort: free the C-side struct once this ALU is collected.
        state = getattr(self, "state", None)
        lib = getattr(self, "lib", None)
        if state and lib:
            lib.free_operand_state(state)

    def load_values(self, instruction: str, op1: OP, op2: OP) -> None:
        """
        Initializes the c structure in operations.c

        :param instruction: Instruction to execute
        :type instruction: str
        :param op1: Operand obj for the first operand
        :param op2: Operand obj for the second operand
        """
        self.lib.clean(self.state)
        opcode: int = self.get_opcode(instruction)
        self.lib.set_instruction(self.state, opcode)

        if op1 and op1.is_valid():
            self.lib.set_operand_info(
                self.state,
                b"op1",
                op1.address,
                op1.size,
                int(op1.type),
                getattr(op1, "is_high", 0),
                getattr(op1, "is_signed", 0),
            )

        if op2 and op2.is_valid():
            self.lib.set_operand_info(
                self.state,
                b"op2",
                op2.address,
                op2.size,
                int(op2.type),
                getattr(op2, "is_high", 0),
                getattr(op2, "is_signed", 0),
            )

    def execute(self) -> None:
        """
        Executes the instruction loaded in the c structure.

        :raises: ZeroDivisionError if the dispatcher catches any zero division error
        """
        exit_code = self.lib.dispatch(self.state)
        if exit_code == 1:
            raise ZeroDivisionError
        elif exit_code == 2:
            raise NameError

    @staticmethod
    def get_opcode(instruction: str) -> int:
        """
        Retrieves the numeric opcode corresponding to the given ALU instruction.

        :param instruction: Name of the instruction (e.g., "add", "sub")
        :type instruction: str
        :return: 0-based opcode index if valid, or -1 if the instruction is unsupported
        :rtype: int
        """
        return ALU_OPCODES.get(instruction.lower(), -1)
