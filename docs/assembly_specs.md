# Assembly x86-64 Language Specification

This document defines the supported x86-64 Assembly subset, syntax constraints, preprocessing rules, memory alignment, and execution behavior for the interpreter.

---

## 1. Syntax & Preprocessing Rules

The interpreter parses `.asm` files adhering to **Intel Assembly Syntax**.

### 1.1 Operand Expression Formatting
* **No Whitespace in Complex Operands:** Address arithmetic or multi-component expressions must not contain spaces between operators and terms.
  * **Valid:** `[rbx+4*1]`, `CONSTANT+4`, `[rsp+8]`
  * **Invalid:** `[rbx + 4 * 1]`, `CONSTANT + 4`
* **Immediate Value Simplification:** All immediate numerical expressions must be pre-simplified to a single constant. Nested arithmetic expressions in instruction operands are strictly prohibited.
  * **Valid:** `58`
  * **Invalid:** `((4+3+1)*4 + 6 + (7 + 8)*2)`
* **Integer Constraints:** Immediates for general-purpose registers must be integer values (decimal, hexadecimal `0x...`, or binary `...b`). Floating-point literals are not permitted for standard ALU instructions.
  * **Valid:** `mov eax, 3`
  * **Invalid:** `mov eax, 3.14`

---

## 2. Program Sections

Assembly programs are parsed in two phases: **Phase 1 (Mapping)** validates section structures and symbol tables; **Phase 2 (Execution)** interprets instructions sequentially.

### 2.1 Section Header Syntax

Sections are declared using the full NASM form, with the `section` keyword followed by the section name:

```asm
section .text
section .data
section .rodata
section .bss
```

Bare section names without the `section` keyword (e.g. `.text` alone on a line) are **not** valid.

### 2.2 Section Types

* **`.text`**: Executable instruction section. Must contain a valid entry label (e.g., `_start:`).
* **`.data`**: Initialized readable and writable memory variables.
* **`.rodata`**: Initialized read-only constants.
* **`.bss`**: Block Started by Symbol — reserved memory for uninitialized data.

### 2.3 Entry Point Declaration

The `.text` section must declare its entry point using `global _start`, followed by the `_start:` label itself:

```asm
section .text
    global _start

_start:
    ; ... instructions ...
```

### 2.4 Comments and Labels

Standard NASM conventions apply:
* Comments begin with `;` and run to the end of the line.
* Labels are declared with a trailing colon (e.g. `loop_start:`) and referenced without one (e.g. `jmp loop_start`).

---

## 3. Directives & Constants

### 3.1 Constant Declarations
Constants defined via `equ` or `#define` are resolved during Phase 1 parsing:

* **Standard Declarations:**
  ```asm
  MAX_SIZE equ: 100
  BUFFER_LEN equ: $-buffer
  ```
* **String & Character Constants:**
  ```asm
  CHAR_A equ: 'A'
  MSG equ: "Hello, World!"
  ```
* **C-Style Definitions:**
  ```asm
  #define BUFFER_SIZE 256
  ```

### 3.2 The `times` Directive

The `times directive is supported in .(ro)data and .bss sictions to declare repeated data buffers:

```asm
; Syntax: <label>: times <count> <size_specifier> <init_value>
buffer: times 10 db 0
array: times 5 dd 0x01
```

#### Supported Sixe Specifiers:
- `db` - Byte
- `dw` - Word
- `dd` - Double Word
- `dq` - Quad Word

### 3.3 Data/Rodata/Bss Variable Declarations

Variables are declared NASM-style, with a label, colon, size specifier, and value(s):

```asm
counter: dd 42
flag: dd 1
```

**Multiple comma-separated numeric values** are supported on one line and are laid out contiguously in memory, one `size specifier`-wide slot per value:

```asm
array: dd 1, 2, 3, 4
```

**String literals** are supported as a value in a `db` declaration, and can be combined with additional comma-separated numeric values on the same line (e.g. to append a trailing byte like a newline):

```asm
msg: db "hi", 0x0a
```

```asm
msg: db "hi"
```

---

## 4. Hardware State & Data Layout
Hardware state (registers and virtual memory) is managed in C shared libraries (`libreg.so` and `libmmu.so`) accessed via Python `ctypes` bindings (`interpreter/_src/bridges/`).

### 4.1 Register File

* 64-bit General Purpose Registers: rax, rbx, rcx, rdx, rsi, rdi, rbp, rsp, r8–r15.
* Sub-Register Mapping: Writes to sub-registers modify the corresponding sub-slice of the 64-bit parent register:
    - 32-bit: eax, ebx, ecx, edx, etc.
    - 16-bit: ax, bx, cx, dx, etc.
    - 8-bit Low/High: al/ah, bl/bh, cl/ch, dl/dh, dil, sil, bpl, spl.
* FPU Registers: Floating-point unit register set.
* EFLAGS Register: Maintained during operation execution in C (operations.c).
    - ZF (Zero Flag)
    - PF (Parity Flag)
    - CF (Carry Flag)
    - SF (Sign Flag)
    - OF (Overflow Flag)
    - TF (Trap Flag — reserved for step-by-step debugging)

### 4.2 Memory Representation & Endianness

* Virtual Memory: Implemented as a 4-level page table system in interpreter/_src/execution/src/memory_eng.c.
* Little-Endian Format: Byte sequences are written and read in Little-Endian order.
    - Example: Writing integer 0x1234 (4 bytes) places byte 0x34 at the base target address, followed by 0x12, 0x00, 0x00 at higher contiguous addresses.
* Stack: Grows downward from higher virtual addresses managed via rsp.

### 4.3 State Inspection (`get_state`)

`Control_Unit.get_state(section)` returns a snapshot of observable state as a flat `dict[str, int]`. Supported section values: `"data"`, `"rodata"`, `"bss"`, `"registers"`, and `"all"`.

`"all"` merges every section into a single flat dictionary — variable names and register names are both top-level keys in the same dict (e.g. `state["counter"]` for a `.data` variable and `state["rax"]` for a register both appear alongside each other, not nested under section-specific sub-dicts).

---

## 5. Functional Units (FUs) & Instruction Routing

The `control_unit.py` fetches and decodes instructions, dispatching operands to dedicated Functional Units in `interpreter/_src/FUs/`:

* ALU (`alu.py`): Arithmetic (`add`, `sub`, `inc`, `dec`), bitwise logic (`xor`, `and`, `or`), comparisons (`cmp`)
* FPU (`fpu.py`): Floating-point calculation and register operations.
* Data Path (`data_path.py`): Stack control (`push`, `pop`), data transfer (`mov`) and program counter manipulation (jumps, call, ret).

### 5.1 Currently Supported Instructions

The authoritative list lives in `INSTRUCTIONS` (`patter_matching_helpers.py`), organized by the functional unit that handles each instruction. The number in parentheses is the required operand count.

**CPU (`control_unit.py`):**
* `syscall` (0 operands) — see Section 7 for the supported syscall numbers and their semantics

**Data Path (`data_path.py`):**
* Data movement / addressing: `lea` (2), `mov` (2)
* Stack: `push` (1), `pop` (1)
* Subroutines: `call` (1), `ret` (0)
* Unconditional jump: `jmp` (1)
* Conditional jumps (1 operand each):
  | Mnemonic(s) | Condition |
  |---|---|
  | `je`, `jz` | Equal / Zero (ZF == 1) |
  | `jne`, `jnz` | Not Equal / Not Zero (ZF == 0) |
  | `jb`, `jc`, `jnae` | Below / Carry / Not Above-or-Equal (CF == 1) |
  | `jnb`, `jnc`, `jae` | Not Below / Not Carry / Above-or-Equal (CF == 0) |
  | `ja`, `jnbe` | Above / Not Below-or-Equal (CF == 0 and ZF == 0) |
  | `jbe`, `jna` | Below-or-Equal / Not Above (CF == 1 or ZF == 1) |
  | `jl`, `jnge` | Less / Not Greater-or-Equal (SF != OF) |
  | `jge`, `jnl` | Greater-or-Equal / Not Less (SF == OF) |
  | `jg`, `jnle` | Greater / Not Less-or-Equal (ZF == 0 and SF == OF) |
  | `jle`, `jng` | Less-or-Equal / Not Greater (ZF == 1 or SF != OF) |
  | `js` | Sign / Negative (SF == 1) |
  | `jns` | Not Sign / Positive (SF == 0) |
  | `jo` | Overflow (OF == 1) |
  | `jno` | Not Overflow (OF == 0) |
  | `jp`, `jpe` | Parity / Parity Even (PF == 1) |
  | `jnp`, `jpo` | Not Parity / Parity Odd (PF == 0) |

**ALU (`alu.py`):**

* 2-operand: `cmp`, `add`, `adc`, `sub`, `sbb`, `and`, `or`, `xor`, `xchg`, `shl`, `sal`, `shr`, `sar`, `rol`, `rcl`, `ror`, `rcr`
* 1-operand: `inc`, `dec`, `not`, `neg`, `mul`, `imul`, `div`, `idiv`

**FPU (`fpu.py`):**
* No instructions currently registered (functional unit exists but is not yet wired up — see 5.2).

### 5.2 Not Yet Supported

* FPU operations (functional unit exists but no instructions are wired up yet)

### 5.3 Operand Size Inference

When an instruction pairs a register operand with a memory operand that has no explicit size directive (`byte`/`word`/`dword`/`qword`), the memory operand's size is inferred from the register's size:

```asm
mov rax, [exit]     ; valid: size inferred as 8 bytes (rax's width)
```

If neither operand is a register (e.g. both operands are unsized memory references), the size cannot be inferred and this is a genuine syntax error, matching standard NASM behavior, which requires an explicit size directive in that case.

---

## 6. Exit codes status reference

The application returns the following exit codes to indicate success or specific failure states during execution:

| Code | Enum Constant | Description |
| :--- | :--- | :--- |
| **-1000** | `IRRECOVERABLE_ERROR` | Unsuccessful exit due to a critical, non-recoverable runtime or state error. |
| **-3** | `CONSTANT_DECLARATION_ERROR` | Unsuccessful exit due to an incorrect constant declaration format. |
| **-2** | `BSS_FORMAT_ERROR` | Unsuccessful exit due to incorrect `.bss` format detected in the parsing phase. |
| **-1** | `DATA_FORMAT_ERROR` | Unsuccessful exit due to incorrect `.data`/`.rodata` format detected in the parsing phase. |
| **0** | `SUCCESS` | Successful execution and exit. |
| **1** | `NO_START_LABEL` | Unsuccessful exit due to not finding an entry point to the program during `.text` parsing. |
| **2** | `DUPLICATE_LABEL` | Unsuccessful exit due to a duplicated label declaration found during `.text` parsing. |
| **4** | `UNOPENABLE_FILE` | Unsuccessful exit because the target file could not be opened or read. |
| **5** | `STACK_OVERFLOW` | Unsuccessful exit due to a detected stack overflow (stack exceeds allowed limits). |
| **10** | `INVALID_INSTRUCTION_SYNTAX` | Unsuccessful exit due to a syntax error in an instruction during parsing. |
| **11** | `RESERVED_KEYWORD_VIOLATION` | Unsuccessful exit due to conflict in label declaration with a reserved keyword. |
| **12** | `INVALID_SYSCALL` | Unsuccessful exit due to an unsupported or malformed system call. |
| **13** | `NO_EXIT_FOUND` | Unsuccessful exit due to reaching end-of-program without encountering an explicit exit syscall or termination instruction. |
| **14** | `INVALID_OR_UNSUPPORTED_INSTRUCTION` | Unsuccessful exit due to an unrecognized or unimplemented instruction mnemonic. |
| **15** | `BY_0_DIVISION_ERROR` | Unsuccessful exit due to a division by 0 error. |
| **109101** | `SOFTWARE_ERROR` | Unsuccessful exit due to an internal software bug (ASCII representation of "me"). |

---

## 7. System Calls

The simulator exposes a small set of Linux x86-64-compatible system calls,
letting simulated programs perform real I/O, allocate heap space, generate
random data, and terminate — without the simulator needing to implement a
full kernel.

A syscall is invoked the same way it is on real x86-64 Linux: the syscall
number is placed in `rax`, up to three arguments are placed in `rdi`, `rsi`,
and `rdx`, and a `syscall` instruction transfers control. The control unit
intercepts this instruction and hands execution to the `Syscall` class rather
than emulating a real `syscall` trap.

Syscall numbers match the real x86-64 Linux ABI (as defined in
`arch/x86/entry/syscalls/syscall_64.tbl`) wherever an equivalent syscall is
supported. This means assembly written against standard Linux syscall
conventions runs unmodified — the numbers are not simulator-specific.

### Architecture

Syscall handling is split across two layers, mirroring the rest of the
simulator's Python/C split:

```
control_unit
     |
     v
Syscall.syscall()  (Python)
     |
     |  reads rax/rdi/rsi/rdx via Registers_Interface
     |  dispatches to the matching handler method
     |  translates simulated addresses <-> real bytes via Data_Memory
     v
libscl.so  (C, via ctypes)
     |
     |  performs the actual host operation
     |  (real file I/O, real CSPRNG, real fd management)
     v
Host OS
```

**The C layer knows nothing about simulated memory, virtual addresses, or
paging.** Every C function operates purely on plain host byte buffers and
real file descriptors. All translation between a simulated memory address
and an actual buffer of bytes happens on the Python side, via the
`Data_Memory` bridge (`read_bytes`/`write_bytes`). This keeps the C module a
thin, testable I/O layer, and keeps all knowledge of the simulator's own
address space in one place.

### File descriptors

Three file descriptors are always available and behave like their real
counterparts:

| fd | Stream |
|----|--------|
| 0  | stdin  |
| 1  | stdout |
| 2  | stderr |

Any other file descriptor must first be obtained via `open` (see below). The
simulator does not maintain its own fd table — descriptors returned by
`open` are real host file descriptors, used as-is in subsequent
`read`/`write`/`close` calls.

`close` refuses to operate on fd 0/1/2; the simulator treats the standard
streams as always-open for the lifetime of the process.

## Supported syscalls

### `read` (0)

Reads bytes from a file descriptor into simulated memory.

| Register | Meaning |
|----------|---------|
| `rdi`    | File descriptor (0/1/2, or a real fd from `open`) |
| `rsi`    | Simulated memory address to write the bytes into |
| `rdx`    | Number of bytes to read |
| `rax` (return) | Number of bytes actually read, or `-1` on error |

Bytes are read from the real file descriptor into a host buffer, then
copied into simulated memory at the given address via `Data_Memory.write_bytes`.
A short read (fewer bytes available than requested, e.g. near end-of-file)
still succeeds; only the bytes actually read are meaningful, and the
remainder of the requested region is zero-padded.

### `write` (1)

Writes bytes from simulated memory to a file descriptor.

| Register | Meaning |
|----------|---------|
| `rdi`    | File descriptor (0/1/2, or a real fd from `open`) |
| `rsi`    | Simulated memory address to read the bytes from |
| `rdx`    | Number of bytes to write |
| `rax` (return) | Number of bytes actually written, or `-1` on error |

Bytes are read out of simulated memory via `Data_Memory.read_bytes`, then
written to the real file descriptor.

### `open` (2)

Opens a real host file, given a path stored in simulated memory.

| Register | Meaning |
|----------|---------|
| `rdi`    | Simulated memory address of a NUL-terminated path string |
| `rsi`    | Real `O_*` flags (`O_RDONLY`, `O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`, `O_APPEND`, ...) |
| `rdx`    | Permission bits, used only when `O_CREAT` is set (e.g. `0644`) |
| `rax` (return) | A real file descriptor (`>= 0`) on success, or `-1` on error |

The path is read one byte at a time from simulated memory starting at the
given address, stopping at the first NUL byte (capped at 4096 bytes as a
safety limit against a missing terminator). The resulting real fd is
returned directly in `rax` and can be used with `read`, `write`, and `close`
exactly like any other fd.

### `close` (3)

Closes a real host file descriptor previously returned by `open`.

| Register | Meaning |
|----------|---------|
| `rdi`    | File descriptor to close |
| `rax` (return) | `0` on success, or `-1` on error |

Attempting to close fd 0, 1, or 2 always fails (`-1`) — the standard streams
are protected and cannot be closed through this syscall.

### `getrandom` (318)

Fills simulated memory with random bytes sourced from the host's
cryptographically secure random number generator.

| Register | Meaning |
|----------|---------|
| `rdi`    | Simulated memory address to write random bytes into |
| `rsi`    | Number of random bytes requested |
| `rax` (return) | Number of random bytes actually written, or `-1` on error |

Uses the real `getrandom(2)` syscall on Linux hosts, falling back to reading
`/dev/urandom` if unavailable. As with `read`, a short result is zero-padded
to the requested size; only the actually-written bytes are meaningful.

### `exit` (60)

Terminates the simulator process immediately.

| Register | Meaning |
|----------|---------|
| (none)   | No arguments are read |

Calling this syscall ends the Python process itself via `sys.exit(0)` — it
does not merely halt the simulated program's execution loop. If the control
unit needs to keep running afterward (for example, inside a test harness
processing multiple programs in one session), this is the one syscall that
cannot currently be "recovered" from; the whole host process ends.

## Error convention

Every syscall that returns a value follows the same convention as real
x86-64 Linux: success returns a non-negative value in `rax` (meaning depends
on the syscall — a byte count, a file descriptor, an address), and failure
returns `-1`. There is currently no `errno`-equivalent detail available
beyond this single sentinel value.
