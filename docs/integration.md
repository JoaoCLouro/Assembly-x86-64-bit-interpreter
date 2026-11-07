# Python ↔ C Linking Module (`bridges/`)

This module is the bridge layer between the Python-side assembly interpreter and the
C-side CPU state (registers, flags, and memory). It uses `ctypes` to load compiled
shared libraries and expose their functions as typed Python methods to the rest of
the interpreter (`parsing/`, `FUs/`, `helpers/`, `main.py`).

It's made up of two components:

- **`bridges/register_manager.py`** — `Registers_Interface`: reads/writes CPU
  registers and flags backed by a C struct (declared in `execution/include/registers.h`).
- **`bridges/data_memory.py`** — `Data_Memory`: reads/writes emulated memory and
  performs stack operations, backed by a C paging system (declared in
  `execution/include/memory_eng.h`).

## Architecture

```
Interpreter/
├── bridges/                  ← this module
│   ├── __init__.py
│   ├── register_manager.py   → Registers_Interface (loads lib/libreg.so)
│   └── data_memory.py        → Data_Memory (loads lib/libmmu.so)
├── execution/
│   ├── include/               (registers.h, memory_eng.h, operations.h)
│   └── src/                   (C implementation, compiled via Makefile)
├── build/                     (compilation artifacts)
├── lib/                        ← compiled shared objects live here
│   ├── libreg.so
│   └── libmmu.so
├── parsing/                   (control_unit.py, segment_mapper.py)
├── FUs/, helpers/
├── tests/, conftest.py
└── main.py
```

```
┌──────────────────────┐        ctypes         ┌───────────────────────┐
│  bridges/ (Python)   │  ───────────────────▶ │  lib/*.so (C, compiled│
│                      │                        │  from execution/)    │
│ Registers_Interface  │ ── lib/libreg.so ────▶│ CPURegs struct + ops  │
│ Data_Memory          │ ── lib/libmmu.so ────▶│ page table + ops      │
└──────────────────────┘                        └───────────────────────┘
```

`Data_Memory` holds a reference to a `Registers_Interface` instance (it needs `rsp`
for stack operations), so construct `Registers_Interface` first and pass it in.

## Requirements

- Compiled shared objects `libreg.so` and `libmmu.so` in the project-root `lib/`
  directory (built from `execution/`, via the top-level `Makefile`).
- Python 3.9+ (uses `tuple[str, int]` built-in generic syntax).
- No third-party Python dependencies — only the standard library (`ctypes`, `os`).

## Usage

```python
from bridges.register_manager import Registers_Interface
from bridges.data_memory import Data_Memory

regs = Registers_Interface()
mem = Data_Memory(registers=regs)

regs.write_reg("eax", 42)
value = regs.read_reg("al")

mem.push(b"\x01\x00\x00\x00\x00\x00\x00\x00")
top = mem.pop()
```

## `Registers_Interface`

Wraps a `CPURegs` C struct representing the general-purpose registers (`rax`–`r15`)
and the flags register.

### Construction

```python
regs = Registers_Interface()
```

Loads `libreg.so`, configures `argtypes`/`restype` for every bound C function, and
then allocates the C-side register struct via `CPURegs_create`.

### Register naming

Accepts standard x86-64 register names and resolves sub-registers to their parent:

| Form   | Examples                          | Size  |
|--------|------------------------------------|-------|
| 64-bit | `rax`, `r8`, `rsi`, `rsp`           | qword |
| 32-bit | `eax`, `r8d`                        | dword |
| 16-bit | `ax`, `r8w`, `si`, `di`, `bp`, `sp`  | word  |
| 8-bit  | `al`, `ah`, `r8b`, `sil`, `dil`, `bpl`, `spl` | byte |

### Reading and writing

```python
regs.write_reg("eax", 42)
regs.write_reg("al", -5, signed=True)
value = regs.read_reg("al")
```

- `write_reg(expression, value, signed=False)` — validates the value fits the target
  register's size (respecting `signed`), resolves the parent register, and writes
  through to C. Raises `ValueError` on an unknown register name or an out-of-range
  value.
- `read_reg(expression)` — resolves size/parent, reads the raw value from C, and
  applies two's-complement conversion if the register is marked signed.

### Flags

```python
regs.read_carry()  # bool
regs.read_zero()  # bool
regs.read_sign()  # bool
regs.read_overflow()  # bool
regs.read_trap_flag()  # bool
regs.read_flags()  # 4 bytes, little-endian
regs.write_flags(value)
regs.exch_flag(flag_id)
regs.Exch_trap_flag()
```

## `Data_Memory`

Wraps a C-side page table for emulated process memory, including a downward-growing
stack.

### Construction

```python
mem = Data_Memory(registers=regs)
```

Requires a `Registers_Interface` instance (used internally for `rsp` during stack
ops). Loads `libmmu.so` and initializes the page table via `table_init`. Raises
`MemoryError` if the table fails to allocate.

### Byte-level access

```python
mem.write_bytes(addr, data, size)
value = mem.read_bytes(addr, size)
```

- `size` must be one of `1, 2, 4, 8`.
- `write_bytes` pads/truncates `data` to `size` bytes if it doesn't already match.
- Both raise `MemoryError` on a segmentation fault (unmapped address, depending on
  `create_page`).

### Stack operations

Every stack entry is a fixed 8 bytes; the stack grows downward from
`STACK_START` (`0x7fffffffe000`) toward `STACK_LIMIT` (`0xe000000000`).

```python
mem.push(value)  # value: bytes, up to 8 bytes (zero-padded if shorter)
value = mem.pop()  # returns 8 bytes, clears the popped slot
```

- `push` raises `ValueError` if `value` is longer than 8 bytes, and `MemoryError` on
  stack overflow (past `STACK_LIMIT`).
- `pop` raises `MemoryError` on stack underflow (`rsp` at or past `STACK_START`).
