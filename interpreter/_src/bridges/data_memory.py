#!/usr/bin/env python3

import ctypes
import os

from interpreter._paths import LIBMMU_PATH

from .register_manager import Registers_Interface


class Data_Memory:
    """
    Helper class to manage memory allocation and access.
    Used by the Segment_Mapper to create the memory for the CPU.
    All memory addresses are relative to the memory base address.
    Provides methods to read and write data of various sizes and to perform stack operations.\n
    All memory is stored in a low-level paging system for efficiency.
    All stack operations (push/pop) are done with fixed 8-byte entries.
    Allows reading and writing of data in sizes of 1, 2, 4, or 8 bytes.
    All stack operations (push/pop) are done with fixed 8-byte entries.\n
    Author: João Carilho Louro


    :param memory_base: Base address of the memory
    :type memory_base: int
    :param stack_start: Starting address of the stack (default is 0x7fffffffe000)
    :type stack_start: int
    :return: An instance of Data_Memory
    :rtype: Data_Memory
    :raises MemoryError: If the memory table fails to initialize
    """

    # Memory constraints
    RODATA_BASE: int = 0x500000
    STACK_START = 0x7FFFFFFFE000
    STACK_LIMIT: int = (
        0xE000000000  # Arbitrary lower limit for stack growth to prevent overflow
    )

    __slots__ = ["_cleaned", "lib", "registers", "start", "table"]

    def __init__(
        self, registers: Registers_Interface, memory_base: int = RODATA_BASE
    ) -> None:
        self._cleaned = False
        self.start: int = memory_base
        self.registers = registers

        # C libs initializers
        # Loads C memory management lib as an instance of the class
        # lib/ lives at the project root, one directory up from this file (bridges/)
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_base_dir)
        _lib_path = LIBMMU_PATH
        self.lib = ctypes.CDLL(_lib_path)

        # Setup C types as usable types in python
        # Matches execution/include/memory_eng.h:
        #   int write_mem(Table*, uint64_t v_addr, uint8_t *data, uint8_t size, uint8_t create_page)
        #   int read_mem(Table*, uint64_t v_addr, uint8_t *result, uint8_t size)
        self.lib.table_init.restype = ctypes.c_void_p
        self.lib.free_table.argtypes = [ctypes.c_void_p]
        self.lib.write_mem.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(
                ctypes.c_uint8
            ),  # data buffer (was mistakenly a bare c_uint8)
            ctypes.c_uint8,  # size
            ctypes.c_uint8,  # create_page
        ]
        self.lib.write_mem.restype = ctypes.c_int
        self.lib.read_mem.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8),  # result buffer
            ctypes.c_uint8,  # size
        ]
        self.lib.read_mem.restype = ctypes.c_int

        self.table = self.lib.table_init()
        # Double check for table init
        if not self.table:
            raise MemoryError("Failed to initialize memory table.")

    def clean(self):
        """
        Calls the cleaning routine from the memory_eng.c to free memory
        """
        if getattr(self, "_cleaned", False):
            return
        self.lib.free_table(self.table)
        self._cleaned = True

    # ------------------------
    # Read and write methods
    # ------------------------
    def read_bytes(self, addr: int, size: int) -> bytes:
        """
        Reads a byte representation of the data at a specific address/addresses with a specific size.\n
        Uses the read_mem function from the c script to read the value from memory.\n
        Returns the read data as a bytes object. If the read operation fails (e.g., due to a segmentation fault), raises a MemoryError.

        :param addr: address to start reading from.
        :type addr: int
        :param size: size of the data to read: [1,2,4,8] bytes
        :type size: int
        :return: byte values at specific addresses
        :rtype: bytes
        :raises MemoryError: If the read operation fails (e.g., due to a segmentation fault)
        """
        # Python types to C types conversions and buffer allocation
        buffer = (ctypes.c_uint8 * size)()  # Create a buffer to hold the read bytes
        c_addr: ctypes.c_uint64 = ctypes.c_uint64(addr)  # Convert address to C type
        c_size: ctypes.c_uint8 = ctypes.c_uint8(
            size
        )  # Convert size to C type (uint8_t per memory_eng.h)

        if (
            self.lib.read_mem(self.table, c_addr, buffer, c_size) == 1
        ):  # Read memory into the buffer
            raise MemoryError(f"Segmentation Fault at 0x{hex(addr)}")
        return bytes(buffer)  # Convert the buffer to bytes and return

    def write_bytes(
        self, addr: int, data: bytes, size: int, create_page: bool = True
    ) -> None:
        """
        Writes a byte representation of the desired data with a specific size in a specific address/addresses.\n
        Uses the write_mem function from the c script to write the value to memory.\n
        If the write operation fails (e.g., due to a segmentation fault), raises a MemoryError.
        Uses a helper function to ensure that the data being written has the correct number of bytes for the specified size, padding with zeros if necessary.
        Has a flag to indicate if pages should be created if they don't exist, which affects the behavior of the write operation in case of unmapped addresses.

        :param addr: address to start writing to.
        :type addr: int
        :param size: size of the data to write: [1,2,4,8] bytes
        :type size: int
        :param data: data to write
        :type data: bytes
        :param create_page: flag to indicate if pages should be created if they don't exist (default is True)
        :type create_page: bool
        :raises MemoryError: If the write operation encounters an unmapped address (Segmentation Fault
        """
        # Verify data correctness
        if not self.valid_data_length(data, size):
            data = self.get_valid_data(data, size)

        # Python types to C types conversions and buffer allocation
        c_data = (ctypes.c_uint8 * size).from_buffer_copy(
            data
        )  # Convert data to a C array
        c_addr: ctypes.c_uint64 = ctypes.c_uint64(addr)  # Convert address to C type
        c_size: ctypes.c_uint8 = ctypes.c_uint8(
            size
        )  # Convert size to C type (uint8_t per memory_eng.h)

        if (
            self.lib.write_mem(
                self.table, c_addr, c_data, c_size, 1 if create_page else 0
            )
            == 1
        ):  # Write memory from the C array
            raise MemoryError(f"Segmentation Fault at 0x{hex(addr)}")

    # --------------------------------------
    # Data validation and formatting helpers
    # --------------------------------------

    def valid_data_length(self, data: bytes, size: int) -> bool:
        """
        Verifies if the length of the data is valid for the size attributed to the write call.\n
        Tries to prevent errors in writing when there are not enough elements in the data variable for the number of bytes to write.

        :param data: Byte representation of the data to write.
        :type data: bytes
        :param size: Number of bytes to write
        :type size: int
        :return: True if the number of bytes of the data variable matches the size given
        :rtype: bool
        """
        return len(data) == size

    def get_valid_data(self, data: bytes, size: int) -> bytes:
        """
        Returns a copy of data with the correct amount of explicit bytes.\n
        If any bytes are not explicitly written, writes them as a 0 at the end of the data, for each missing bytes.

        :param data: Byte representation of the data to write.
        :type data: bytes
        :param size: Number of bytes to write
        :type size: int
        :return: Full data with all implicit bytes written out
        :rtype: bytes
        """
        return data[:size].ljust(size, b"\x00")

    # --------------------------------------------
    #  STACK OPERATIONS (fixed 8 bytes per entry)
    # --------------------------------------------
    def push(self, value: bytes) -> None:
        """
        Push a full 8-byte (64-bit) value.
        All stack cells are 8 bytes no matter what.
        If the value provided is less than 8 bytes, it will be padded with zeros to fit the stack cell size. If it exceeds 8 bytes, an error will be raised.
        Uses the write_bytes method to write the value to the stack, ensuring that the stack pointer is updated correctly and that stack overflow is prevented by checking against a predefined stack limit.
        The create_page flag is set to True for stack operations to allow the stack to grow as needed, but stack overflow is prevented by the stack limit check.

        :param value: value to add to the stack
        :type value: bytes
        :raises MemoryError: If the stack overflows (i.e., if the stack pointer goes below an arbitrary lower limit)
        :raises ValueError: If the value exceeds the stack cell size of 8 bytes
        """
        # If the value is longer than 8 bytes, signals an error
        if len(value) > 8:
            raise ValueError("Value exceeds stack cell size of 8 bytes.")

        rsp = self.registers.read_reg("rsp")
        # Check for stack overflow before pushing
        if rsp - 8 < self.STACK_LIMIT:
            raise MemoryError("Stack overflow: cannot push more data to the stack.")

        # Ensure the value is exactly 8 bytes, padding with zeros if necessary
        if len(value) < 8:
            value = self.get_valid_data(value, 8)

        # stack grows downward
        self.registers.write_reg("rsp", rsp - 0x8)
        self.write_bytes(rsp - 0x8, value, 8)

    def pop(self) -> bytes:
        """
        Pop a full 8-byte (64-bit) value.

        :return: current value at the top of the stack
        :type: bytes
        :raises MemoryError: If the stack underflow's (i.e., if the stack pointer goes above the stack start address)
        """
        rsp = self.registers.read_reg("rsp")
        # Check for stack underflow before popping
        if rsp >= self.STACK_START:
            raise MemoryError("Stack underflow: cannot pop from an empty stack.")
        value = self.read_bytes(rsp, 8)
        self.write_bytes(
            rsp, b"\x00" * 8, 8
        )  # Clear the popped value from the stack (optional)
        self.registers.write_reg("rsp", rsp + 0x8)
        return value
