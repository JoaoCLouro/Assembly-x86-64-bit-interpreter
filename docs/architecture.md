# System Architecture & Design

This document details the high-level architecture of the Assembly x86-64 Interpreter. The system is designed as a hybrid model: Python orchestrates the high-level control flow and text parsing, while a compiled C engine handles the low-level hardware state and mathematical execution.

---

## 1. Core Philosophy & Responsibility Matrix

The interpreter divides responsibilities across language boundaries to maximize both development flexibility and execution accuracy.

### Python's Domain

* **Parsing & Lexing:** Reading the `.asm` file, stripping comments, and resolving expressions/declarations.
* **Syntax Validation:** Ensuring operands match expected x86-64 structural rules before execution begins.
* **Control Flow:** Managing the program counter (instruction pointer) and the main execution loop.
* **Dispatching:** Routing parsed instructions to their corresponding Functional Units.

### C's Domain

* **Hardware State:** Maintaining the exact bit-layout of the 64-bit registers, FPU state, and EFLAGS.
* **Memory Management:** Simulating a 4-level page table to handle virtual memory mapping and stack bounds.
* **Opcode Execution:** Performing the actual bitwise and arithmetic operations natively to accurately simulate CPU overflow, carry, and sign conditions.

---

## 2. The Execution Pipeline

```text
.asm file
   │
   ▼
┌─────────────────────┐
│  segment_mapper.py  │     Phase 1 — Mapping & Pre-processing
│ parse→validate→map  │     (Runs once, before execution)
└──────────┬──────────┘
           │ symbol table, memory layout, initialized data
           ▼
 Phase 2 — Execution Loop
┌─────────────────────┐       1. raw instruction      ┌───────────────────────┐
│   control_unit.py   │──────────────────────────────►│ instruction_parser.py │
│                     │◄──────────────────────────────│ parse&decode operands │
│      ┌───────┐      │       2. parsed operands      └───────────────────────┘
│      │ fetch │◄──|  │
│      └───┬───┘   |  │       3. decoded instruction  ┌───────────────────────┐
│          ▼       |  │          + operands           │   FUs/ (Functional    │
│     ┌──────────┐ |  │──────────────────────────────►│   Units execution)    │
│     │ validate │ |  │                               └──────────┬────────────┘
│     └────┬─────┘ |  │                                          │ calls bridge
│          ▼       |  │                                          ▼
│     ┌──────────┐ |  │                               ┌───────────────────────┐
│     │ dispatch │ |  │                               │   bridges/ (ctypes)   │
│     └────┬─────┘ |  │                               │ register_mgr/data_mem │
│          │       |  │                               └──────────┬────────────┘
│          └───────|  |                                          │ mutates state
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

---

## 3. Phase 1: Mapping (`segment_mapper.py`)

Before a single instruction is executed, the interpreter scans the entire file. This is crucial for resolving forward references (e.g., jumping to a label defined later in the file) and setting up the initial memory layout.

1. Section Identification: Divides the code into `.data`, `.rodata`, `.bss`, and `.text`.
2. Memory Allocation:
    - Allocates bytes for constants and strings in `.data` and `.rodata`.
    - Reserves uninitialized space for `.bss` directives (e.g., `times 10 db 0`).
    - Writes initial values into the C Virtual Memory engine via the bridge.
3. Symbol Table Generation: Records the exact line number/address for every label (functions, variable names, jump targets).
4. Pre-Validation: Checks for missing `_start` labels, duplicated symbols, or malformed data declarations.

---

## 4. Phase 2: Execution (`control_unit.py`)

Once mapping is complete, the `control_unit.py` takes over. It acts as the system clock, driving the fetch-execute cycle until the program issues a termination syscall or reaches the end of the executable section (issuing an error exit code at the end).

1. **Fetch**: Retrieves the next instruction string based on the current logical instruction pointer.
2. **Parse**: Passes the raw string to `instruction_parser.py` to extract the opcode (e.g., mov) and its arguments (e.g., rax, [rbx+4]).
3. **Validate**: Ensures the operand types are legal for the given opcode (e.g., rejecting memory-to-memory direct transfers).
4. **Dispatch**: Hands the normalized operands to the correct Functional Unit.

---

## 5. Functional Units (FUs)

Located in `interpreter/_src/FUs/`, Functional Units are the translation layer between Python's understanding of an instruction and C's execution of it.

* Base Structure (`common_classes.py`): Defines the interface all FUs must follow, ensuring they accept parsed operands and return execution status.
* `alu.py` (Arithmetic Logic Unit): Handles math and logic. If the instruction is `add rax, rbx`, the ALU reads the current value of `rbx` via the bridge, reads `rax`, and calls the C `op_add64` function, which writes the result back to rax and updates `EFLAGS`.
* `data_path.py`: Handles control flow operations (`jmp`, `je`, `call`, `ret`) and stack operations (`push`, `pop`), heavily interacting with the MMU and modifying the instruction pointer in the Control Unit.
* `fpu.py`: Dedicated routing for floating-point instructions to the FPU registers.
