# Assembly x86 64 bit python Interpreter

A simple assembly x86 64-bit interpreter with sequential execution and error detection.


## About the Project

This project aims to simulate the behavior of a CPU while executing simple Assembly x86-64bit code with Intel syntax.
In order to execute this projects goal, cpu component classes were implemented simulating its behavior:

- registers: general purpose register, fpu registers and the flag register;
- manageable memory memory allocation interface built using the standard x86 paging system;
- an operation dispatcher that directs the execution flow the the desired operation

Python owns parsing and control flow. C owns the actual machine state and the raw execution of each operation. The two talk to each other through a thin ctypes bridge layer.

During the parsing stage of the execution there is a light checkup on syntax correctness trying to match expected syntax cases, code correctness like operand count or type.
During each interpretation execution more validation is run to make sure the current state is valid for the instruction being executed

This projects offers two main interfaces:

- A main.py script that run the code directly
- A class with similar behavior as main that enables you to get the state of the program from its object before shutting down

Before using please make sure your code follows the [Code format references](#code-format-and-syntax-references)

## Installation & Distribution

> **Prerequisites:** Python 3.14+, `gcc` (or another C compiler), and `make`.
> The interpreter's register/memory state is implemented in C and loaded via
> `ctypes` at runtime — **the C shared libraries must be compiled locally
> regardless of which installation method you use below**, since compiled
> binaries aren't distributed as part of the wheel.

### 1. From GitHub Releases (Pre-built Package)

Download and install the pre-compiled wheel directly from the
[v0.3.2 GitHub Release](https://github.com/JoaoCLouro/Assembley-x86-64-bit-interpreter/releases/tag/v0.3.2):

```bash
pip install https://github.com/JoaoCLouro/Assembley-x86-64-bit-interpreter/releases/download/v0.3.2/cpu_simulator-0.3.2-py3-none-any.whl
```

You'll still need the C libraries built locally (see step 3 below) — clone
the repository separately and run `make` from its root before the
interpreter can actually execute anything.

### 2. From Source

Clone the repository:
```bash
git clone https://github.com/JoaoCLouro/Assembley-x86-64-bit-interpreter.git
cd Assembley-x86-64-bit-interpreter
```

Create and activate a virtual environment (recommended, keeps the
project's dependencies isolated from your system Python):
```bash
python3 -m venv .venv

# bash/zsh
source .venv/bin/activate
# fish
source .venv/bin/activate.fish
```

Install the project in editable mode:
```bash
pip install -e .
```

### 3. Build the C libraries

Required for both installation methods above — this compiles
`libreg.so`, `libmmu.so`, `liboperations.so`, and `libscl.so` into
`interpreter/_src/lib/`:
```bash
make clean && make
```

Verify the install resolved correctly:
```bash
python -c "import interpreter; print(interpreter.__file__)"
```
This should print a path inside your cloned repository.

### 4. Running the test suite (optional)

The test suite uses `pytest`, which isn't installed automatically by
either method above:
```bash
pip install pytest
pytest tests/ -v
```

Alternatively, build local distribution wheels yourself instead of using
a pre-built release:
```bash
python -m pip install pyproject-build
pyproject-build
pip install dist/cpu_simulator-0.3.2-py3-none-any.whl
```


## Quick Start & Usage 

### CLI Usage

Execute assembly files using the `main.py` runner or installed package entry point:
```bash 
# Direct runner
python main.py <path-to-your-asm-file>

# Interactive prompt mode (when no file argument is provided)
python main.py
```

### Programmatic Python API

The top-level `interpreter` package exposes `Interpreter` and `ExitCode` for
programmatically controlling and inspecting simulation runs.

> **Note:** both `file_name` and `args` are required positional arguments —
> there's no default that skips them silently. Passing `None`, or an empty
> list, or omitting `args` doesn't run the program with "no arguments" —
> it makes the constructor **block on an interactive `input()` prompt**
> asking for them. For non-interactive/programmatic use, always pass a
> real file path and a list — use a placeholder like `["_"]` if the
> program itself doesn't read `argv`.

#### `Interpreter(file_name: str, args: list[str], debugging: bool = False)`

Constructs the interpreter: loads and parses the given `.asm` file (via
the segment mapper), initializing memory/register state. Does **not**
execute the program — call `.run()` separately to do that.

- `file_name` — path to the `.asm` file to load.
- `args` — command-line arguments the simulated program receives (as
  `argc`/`argv`); pass a placeholder list if the program doesn't use them.
- `debugging` — when `True`, enables trap-flag-driven single-step
  execution instead of running straight through.

#### `.run() -> ExitCode`

Executes the loaded program until it terminates (via an exit syscall,
falling off the end of `.text`, or an error), then returns the resulting
`ExitCode`. If the file failed to parse during construction, returns
`ExitCode.IRRECOVERABLE_ERROR` without attempting execution.

#### `.get_state(section: str, numerical_representation: int = 16) -> dict[str, int | str]`

Returns a snapshot of CPU/memory state as `name -> value`, without
tearing anything down — can be called repeatedly, including mid-run if
you're driving execution manually.

- `section` — `"all"`, `"data"`, `"rodata"`, `"bss"`, or `"registers"`.
- `numerical_representation` — the base to render values in: `10`
  (decimal, returned as plain `int`), `2` (binary), `8` (octal), or `16`
  (hexadecimal, the default) — the latter three are returned as
  Python-style prefixed strings (e.g. `"0x2a"`). Negative values are
  shown as their two's-complement bit pattern at the value's actual
  width, not a signed `"-0x.."` string. An unsupported value falls back
  to `16` with a warning printed.

#### `.to_json(path: str, numerical_representation: int = 10) -> str | None`

Exports the final state (equivalent to `get_state("all", ...)`) to a
JSON file at `path`. `path` is the full destination *file* path, not a
directory — its parent directory must already exist, and an existing
file at that path is overwritten. Returns `path` on success, or `None`
if the interpreter ended on an irrecoverable error or the destination is
invalid.

#### `.exit() -> dict[str, int | str] | None`

Fetches the final state (same as `get_state("all")`), then frees the
interpreter's underlying memory/register resources — call this once
you're done inspecting state and won't need the interpreter instance
again. Returns `None` instead if the interpreter ended on an
irrecoverable error, in which case there's no valid state to return.

```python
from interpreter import Interpreter, ExitCode

# Initialize the CPU simulator with an assembly program.
# args=[] would trigger an interactive prompt - pass a placeholder
# list instead if the program doesn't read argv.
sim = Interpreter("path/to/program.asm", args=["_"])

# Execute program until termination or error
exit_status = sim.run()

if exit_status == ExitCode.SUCCESS:
    # Inspect final CPU registers or memory state (hex by default)
    print(f"Registers: {sim.get_state('registers')}")

    # Export the full final state to a JSON file, in decimal
    sim.to_json("run_state.json", numerical_representation=10)
else:
    print(f"Execution failed with status: {exit_status}")

# Free the interpreter's underlying resources once you're done with it
sim.exit()
```

---

## Pipeline

A `.asm` file is mapped once (symbol table, memory layout), then executed
one instruction at a time: the control unit fetches and decodes each
instruction, dispatches it to the matching Functional Unit, which calls
into the compiled C engine through the ctypes bridge layer.

```text
.asm file
   │
   ▼
┌─────────────────────┐
│  segment_mapper.py  │     Phase 1 — mapping
│ parse→validate→map  │     (runs once, before execution)
└──────────┬──────────┘
           │ symbol table, memory layout
           ▼
 Phase 2 — execution loop
┌─────────────────────┐       1. raw instruction      ┌───────────────────────┐
│   control_unit.py   │──────────────────────────────►│ instruction_parser.py │
│                     │◄──────────────────────────────│ parse&decode operands │
│      ┌───────┐      │       2. parsed operands      └───────────────────────┘
│      │ fetch │◄──|  │
│      └───┬───┘   |  │       3. decoded instruction  ┌───────────────────────┐
│          ▼       |  │          + operands           │   FUs/ (Functional    │
│     ┌──────────┐ |  │──────────────────────────────►│   Units execution)    │
│     │ validate │ |  │                               └──────────┬────────────┘
│     └────┬─────┘ |  │                                          │ calls C
│          ▼       |  │                                          ▼
│     ┌──────────┐ |  │                               ┌───────────────────────┐
│     │ dispatch │ |  │                               │   bridges/ (ctypes)   │
│     └────┬─────┘ |  │                               │ register_mgr/data_mem │
│          │       |  │                               └──────────┬────────────┘
│          └───────|  |                                          │ memory/reg
│                     │                                          ▼
│                     │                               ┌───────────────────────┐
│                     │ 4. returns control / state    │    execution/ (C)     │
│                     │◄──────────────────────────────│  registers.c/memory.c │
└──────────┬──────────┘                               └───────────────────────┘
           │
           │ (loop finishes / exit code)
           ▼
┌─────────────────────┐
│  Final Interpreter  │
│  State (CPU state)  │
└─────────────────────┘
```

## Project layout

```text
CPU_SIMULATOR/
├── interpreter/                 # Main Python package
│   ├── _src/                    # Internal engine code & execution units
│   │   ├── bridges/             # C-to-Python ctypes bindings
│   │   ├── execution/           # C execution engine source & headers
│   │   ├── FUs/                 # Functional Units (ALU, FPU, DataPath)
│   │   ├── helpers/             # Shared utility modules
│   │   ├── lib/                 # Compiled shared libraries (.so)
│   │   ├── parsing/             # Segment mapper, control unit, and instruction parsers
│   │   └── program_cache/       # Program layout cache
│   ├── __init__.py              # Public API exports (Interpreter, ExitCode)
│   ├── exit_codes.py            # ExitCodes enum class holder
│   └── interpreter.py           # Program's core runner class
├── tests/                       # C and Python test suites
├── docs/                        # Project documentation
├── .gitignore
├── main.py                      # CLI entry point script
├── Makefile                     # Build targets for C shared libraries
└── pyproject.toml               # Setuptools distribution metadata
```

## Building

```bash
# Build C shared libraries (libreg.so, libmmu.so, liboperations.so)
make

# Run C-level engine unit tests
make test

# Run Python integration and bridge test suite
pytest tests/ -v
```

---

## **Implementation and Decisions**

Interpreting a `.asm` file happens in two phases:
 
**1. Mapping (`parsing/segment_mapper.py`)**
Reads the assembly file once, before anything executes. It walks each
section, maps variables and instructions into simulated memory, builds the
label/symbol table, and validates that the file is well-formed — checking
syntax and instruction structure so that malformed input is caught up front
rather than failing mid-execution.
 
**2. Execution (`parsing/control_unit.py`)**
The actual execution loop. Starting from the beginning of the program, it
interprets one instruction at a time, running until it hits an exit call (or
the last executable instruction). For each instruction, it resolves operands,
dispatches to the matching Functional Unit, and lets the C side carry out the
real side effects — register writes, memory writes, flag updates — through
the bridge layer.  

**Functional Units (`FUs/`)**
Each instruction (`add`, `mov`, `cmp`, `xor`, ...) has a corresponding FU
class. The control unit resolves which FU handles a given instruction and
hands it the decoded operands; the FU is responsible for reading its inputs,
invoking the correct C operation, and writing the result back.
**The bridge layer (`bridges/`)**
Python can't touch raw CPU state directly, so every register read/write and
every memory access goes through `ctypes` into compiled C:

- `register_manager.py` → `lib/libreg.so` — register file, sub-register
  resolution (`rax`/`eax`/`ax`/`al`/`ah`, etc.), flags.
- `data_memory.py` → `lib/libmmu.so` — a 4-level page table for virtual
  memory, plus stack push/pop.
Both are deliberately thin: they translate calls and manage types, the actual
logic lives in C.

### Data handling

#### Data normalization occurs in two stages:

1. **Caller Level**: During the data parsing phase the data size is found and the data itself is parsed to a python bytes type for easier pre-validation.

2. **Definitive Level**: The Data_Memory class ensures the bytes object perfectly match the required hardware size before the write occurs and calls on the c write operation to the data buffer created with the specific size.

#### Structure of processed values to be written:

- **Initial Value:**
    - int 0x1234 (Size: 4 bytes)
- **Byte Conversion:**
    - b'\34\12' (Length: 2)
- **Final Processed Data:**
    - b'\34\12\00\00' (Length: 4)

#### Little endian implementation:
Byte writing will change the order by which values appear in the variable to be able to write them in a little endian format at the bytarray. In this format, and following the given example, the byte b'\34' will be written first at the base address and the following bytes of the processed data will be written in higher level addresses in a sequential order.

### Reading Memory:

Memory reading will follow the same structure of the writing, returning the first value read at the first position of the bytes variable.

#### Structure of read values:

- **Address to Read and Number of Bytes**:
    - 0x4001 (Size: 4 bytes)
- **Value Returned:**
    - b'\34\12\00\00'
- **Real Value:**
    - 0x1234

#### Reading Logic:

Reading will always take a start address and a number of bytes to read. This method then will start reading bytes at the given address and stop only when the number of bytes above that address is met or a null value is found.

> **Note:** the internal reads described above always operate on raw
> bytes. When fetching state for external use via `get_state()` /
> `to_json()`, values can additionally be rendered in decimal, binary,
> octal, or hexadecimal — see the `numerical_representation` parameter in
> the [Programmatic Python API](#programmatic-python-api) section.

---

## Code format and syntax references

### Supported instructions

| Category | Instructions |
| :--- | :--- |
| **Data movement** | `mov`, `lea`, `push`, `pop` |
| **Control flow** | `call`, `ret`, `jmp` |
| **Conditional jumps** | `je`/`jz`, `jne`/`jnz`, `jb`/`jc`/`jnae`, `jnb`/`jnc`/`jae`, `ja`/`jnbe`, `jbe`/`jna`, `jl`/`jnge`, `jge`/`jnl`, `jg`/`jnle`, `jle`/`jng`, `js`, `jns`, `jo`, `jno`, `jp`/`jpe`, `jnp`/`jpo` |
| **Arithmetic** | `add`, `adc`, `sub`, `sbb`, `inc`, `dec`, `cmp`, `mul`, `imul`, `div`, `idiv` |
| **Bitwise logic** | `and`, `or`, `xor`, `not`, `neg`, `xchg` |
| **Shifts & rotates** | `shl`/`sal`, `shr`, `sar`, `rol`, `ror`, `rcl`, `rcr` |
| **System calls** | `syscall` — see [Exit codes status reference](#exit-codes-status-reference) for related error codes; refer to `bridges/syscall.py` for the specific syscall numbers currently supported |

`mul`/`imul`/`div`/`idiv` only support the standard single-operand NASM
form (e.g. `mul rbx`, not the two/three-operand `imul` variants).
FPU instructions are not yet implemented — see [Roadmap](#roadmap).

### Allowed declarations

In the broadest terms possibly **all nasm supported syntax for the implemented operations is supported**. The only (known) exception to this are the multiplication and division operation in which only 1 operand declarations are supported.

#### Useful declaration syntax guide lines

For more clarification on specific supported declarations syntax or preferred syntax:

- Immediate/variable numerical values should be always declared using either binary, decimal or hexadecimal numeration.

- "times" directive use is only allowed following a specific syntax:
    All "times" declarations must follow the structure:

    ```asm
    ; <label>: times <count> <size_specifier> <init_value>
    buffer: times 10 db 0
    ```

Constants declarations are a bit more nuanced. Allowed declarations include:

- Standard declarations:

    * <constant_uppercased_label> equ: <integer_value>;
    * <constant_uppercased_label> equ: <string_size_calculation>;

- String declarations:

    * <constant_uppercased_label> equ: '<character_value>';
    * <constant_uppercased_label> equ: "<string_value>";

- Standard c constant definitions:
    * #define <constant_uppercased_label> <value>


### Operand syntax rules

- Operands written with different components should have no spaces in between each component of the expression:

    ex.:
        - What to avoid: [rbx + 4 * 1] or CONSTANT + 4
        - Correct version: [rbx+4*1]   or CONSTANT+4

- If an operand is an immediate value it should always be simplified to the maximum extent possible avoiding complex nested parentheses expression:

    ex.:
        - What to avoid: ((4+3+1)*4 + 6 + (7 + 8)*2)
        - Correct version: 58

- All immediate values should be integer values (not decimal point values)

    ex.:
        - What to avoid: mov eax, 3.14
        - Correct version: mov eax, 3

---

### Exit codes status reference

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

## Contributions

**Adding a new instruction**

1. Implement the operation and its flag-update logic in
   `execution/src/operations.c`.
2. Add or extend a Functional Unit in `FUs/` to decode the instruction's
   operands and call into the new operation.
3. Register the instruction in `parsing/pattern_matching_helpers.py` under **INSTRUCTIONS** so it dispatches to
   the right FU.
4. Add coverage: a C-level test under `tests/execution_tests/`, and a
   Python-level test under `tests/<specific folder>/`

**Changing registers or memory internals**

1. Update the corresponding header in `execution/include/`.
2. Rebuild with `make clean && make`.
3. Re-implement and run the test suites for the all c Level implementations as they are interconnected.
4. Re-run `pytest tests/bridge/ -v` — a signature change that isn't mirrored
   in the Python `ctypes` bindings will show up here rather than as a silent
   runtime bug.

**General expectations**

- Keep C changes and their Python bindings in sync in the same change —
  a mismatch between the two is the most common source of bugs in this
  project so far.
- New behavior should come with a test at the layer it lives in: C-level
  logic gets a C test, bridge/ctypes plumbing gets a Python bridge test.
- Different tasks in the interpreter should be kept separate at separate folders and well integrated to the core parsing and execution loops.

---

## Roadmap

### Recently added

- Signed and unsigned multiplication/division (`mul`, `imul`, `div`, `idiv`, single-operand NASM form only);
- Bit shifts and rotations, with and without carry (`shl`/`sal`, `shr`, `sar`, `rol`, `ror`, `rcl`, `rcr`);
- Configurable numeric representation (decimal, binary, octal, hexadecimal) for `get_state()`/`to_json()` output.

### Planned improvement

- Implement FPU operations, not yet available;

- Reinforcing the syscall's supported by the program;

- Implement a debugging execution type with gdb commands and one instruction at a time execution using the trap flag mechanism already implemented;

---

## Contributors

### - João Louro @FCUL