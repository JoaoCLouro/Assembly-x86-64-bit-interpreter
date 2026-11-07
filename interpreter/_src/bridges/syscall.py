import ctypes
import os

from ..bridges.data_memory import Data_Memory
from ..bridges.register_manager import Registers_Interface


class Syscall:
    """
    Resolves and executes syscalls triggered during instruction execution.
    Called from the control_unit via the `syscall()` entry point, which reads
    the syscall number and arguments straight from the register bridge, then
    dispatches to the matching handler.\n
    Handlers that move data (read/write/open/getrandom) go through the
    Data_Memory bridge to translate simulated addresses into real bytes, then
    hand those bytes to the compiled C module (libscl.so) which performs the
    actual operation. The C module has no notion of virtual addresses or
    paging — it only ever sees plain byte buffers and real fds.\n
    Syscall numbers follow the real x86-64 Linux ABI so that assembly written
    against standard syscall conventions works unmodified.

    :param registers: Register bridge used to read syscall number/arguments
    :type registers: Registers_Interface
    :param memory: Memory bridge used to translate simulated addresses to/from bytes
    :type memory: Data_Memory
    """

    # Simulated file descriptors always available
    STDIN: int = 0
    STDOUT: int = 1
    STDERR: int = 2

    # Real x86-64 Linux syscall numbers (see /usr/include/asm-generic/unistd.h
    # or arch/x86/entry/syscalls/syscall_64.tbl)
    SYS_READ: int = 0
    SYS_WRITE: int = 1
    SYS_OPEN: int = 2
    SYS_CLOSE: int = 3
    SYS_EXIT: int = 60
    SYS_GETRANDOM: int = 318

    # Max bytes read at once for a NUL-terminated path string pulled from
    # simulated memory (open() needs a path but has no length argument).
    MAX_PATH_LEN: int = 4096

    __slots__ = ["lib", "memory", "registers"]

    def __init__(self, registers: Registers_Interface, memory: Data_Memory):
        self.registers = registers
        self.memory = memory

        # C lib initializer
        # lib/ lives at the project root, one directory up from this file (bridges/)
        _base_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_base_dir)
        _lib_path = os.path.join(_project_root, "lib", "libscl.so")
        self.lib = ctypes.CDLL(_lib_path)

        # Setup C types as usable types in python
        # Matches execution/include/syscall.h
        self.lib.sys_read.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self.lib.sys_read.restype = ctypes.c_int64

        self.lib.sys_write.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self.lib.sys_write.restype = ctypes.c_int64

        self.lib.sys_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        self.lib.sys_open.restype = ctypes.c_int64

        self.lib.sys_close.argtypes = [ctypes.c_int]
        self.lib.sys_close.restype = ctypes.c_int64

        self.lib.sys_getrandom.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
        ]
        self.lib.sys_getrandom.restype = ctypes.c_int64

    def syscall(self) -> int:
        """
        Main entry point called by the control_unit when a syscall instruction
        is executed. Reads the syscall number from rax and its arguments from
        rdi/rsi/rdx, then dispatches to the matching handler. The handler's
        return value (if any) is written back into rax, matching x86-64
        Linux calling convention.\n
        Unrecognized syscall numbers are ignored (no-op).

        :return: -1 If an error was signaled from the syscall execution, any otherwise
        :rtype: int
        """
        code: int = self.registers.read_reg("rax")
        rdi: int = self.registers.read_reg("rdi")
        rsi: int = self.registers.read_reg("rsi")
        rdx: int = self.registers.read_reg("rdx")

        result: int | None = None

        match code:
            case self.SYS_READ:
                result = self.read(rdi, rsi, rdx)
            case self.SYS_WRITE:
                result = self.write(rdi, rsi, rdx)
            case self.SYS_OPEN:
                result = self.open(rdi, rsi, rdx)
            case self.SYS_CLOSE:
                result = self.close(rdi)
            case self.SYS_GETRANDOM:
                result = self.getrandom(rdi, rsi)
            case self.SYS_EXIT:
                return self.exit()
            case _:
                return -1

        if result is not None:
            self.registers.write_reg("rax", result, signed=True)
            return result
        return 0

    def exit(self) -> int:
        """
        Signals the termination of the simulator process.
        """
        return 1

    def read(self, fd: int, addr: int, size: int) -> int:
        """
        Reads up to `size` bytes from the real stream/file mapped to `fd`
        (0/1/2 or a real fd from open()) and writes the result into
        simulated memory at `addr`.

        :param fd: File descriptor (0/1/2, or a real fd from open())
        :type fd: int
        :param addr: Simulated memory address to write the read bytes into
        :type addr: int
        :param size: Number of bytes to read
        :type size: int
        :return: Number of bytes actually read, or -1 on error/unknown fd
        :rtype: int
        """
        buffer = (ctypes.c_uint8 * size)()
        read_count = self.lib.sys_read(fd, buffer, size)

        # (-1) error reported
        if read_count <= 0:
            return read_count

        data = bytes(buffer[:read_count])
        # Pad to the requested size so write_bytes' size check is satisfied;
        # only the first read_count bytes are meaningful.
        if len(data) < size:
            data = data.ljust(size, b"\x00")
        self.memory.write_bytes(addr, data, size)
        return read_count

    def write(self, fd: int, addr: int, size: int) -> int:
        """
        Reads `size` bytes from simulated memory at `addr` and writes them to
        the real stream/file mapped to `fd` (0/1/2 or a real fd from open()).

        :param fd: File descriptor (0/1/2, or a real fd from open())
        :type fd: int
        :param addr: Simulated memory address to read the bytes from
        :type addr: int
        :param size: Number of bytes to write
        :type size: int
        :return: Number of bytes actually written, or -1 on error/unknown fd
        :rtype: int
        """
        data = self.memory.read_bytes(addr, size)
        buffer = (ctypes.c_uint8 * size).from_buffer_copy(data)
        return self.lib.sys_write(fd, buffer, size)

    def open(self, path_addr: int, flags: int, mode: int) -> int:
        """
        Opens a real host file. The path is read as a NUL-terminated string
        out of simulated memory starting at `path_addr`.

        :param path_addr: Simulated memory address of the NUL-terminated path string
        :type path_addr: int
        :param flags: Real O_* flags (O_RDONLY, O_WRONLY, O_CREAT, ...)
        :type flags: int
        :param mode: Permission bits used only when O_CREAT is set (e.g. 0o644)
        :type mode: int
        :return: A real file descriptor (>= 0) on success, or -1 on error
        :rtype: int
        """
        path_bytes = self._read_c_string(path_addr)
        fd = self.lib.sys_open(path_bytes, flags, mode)
        return fd

    def close(self, fd: int) -> int:
        """
        Closes a real host file descriptor previously returned by open().
        Refuses to close fd 0/1/2.

        :param fd: File descriptor to close
        :type fd: int
        :return: 0 on success, or -1 on error
        :rtype: int
        """
        return self.lib.sys_close(fd)

    def getrandom(self, addr: int, size: int) -> int:
        """
        Fills simulated memory at `addr` with `size` random bytes sourced
        from the host CSPRNG.

        :param addr: Simulated memory address to write random bytes into
        :type addr: int
        :param size: Number of random bytes requested
        :type size: int
        :return: Number of random bytes actually written, or -1 on error
        :rtype: int
        """
        buffer = (ctypes.c_uint8 * size)()
        got = self.lib.sys_getrandom(buffer, size)

        # (-1) error reported
        if got <= 0:
            return got

        data = bytes(buffer[:got])
        if len(data) < size:
            data = data.ljust(size, b"\x00")
        self.memory.write_bytes(addr, data, size)
        return got

    def _read_c_string(self, addr: int, max_len: int = MAX_PATH_LEN) -> bytes:
        """
        Reads a NUL-terminated byte string out of simulated memory one byte
        at a time, stopping at the first NUL or after `max_len` bytes.

        :param addr: Simulated memory address of the string's first byte
        :type addr: int
        :param max_len: Safety cap on how many bytes to scan before giving up
        :type max_len: int
        :return: The string's bytes, NOT including the terminating NUL
        :rtype: bytes
        """
        result = bytearray()
        for offset in range(max_len):
            byte = self.memory.read_bytes(addr + offset, 1)
            if byte == b"\x00":
                break
            result.extend(byte)
        return bytes(result)
