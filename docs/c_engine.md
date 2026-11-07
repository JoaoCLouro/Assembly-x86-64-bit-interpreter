# Performance module

This module focuses on providing memory efficient and fast functions and structures to support the interpretation and the replication of the intended instruction.
It defines a memory handling module that should be used to read abd write data into memory, a register module that mimics the registers behavior used to map into register related instructions/ accesses, and an operations module that defines the major lookup table for the instructions to run.

## **Modules:**

### **Memory Engine**

 ---

### API

``` text
|===============|============================================|====================================|
|    Function   |                Parameters                  |             Results                |
|===============|============================================|====================================|
|   table_init  |                  None                      |Table pointer to the init'ed struct;|
|===============|============================================|====================================|
|  free_table   |          Table struct pointer              |Frees up the structure from memory; |
|===============|============================================|====================================|
|               |Table struct pointer;                       |(Re)Writes bytes in the memory      |
|               |uint64_t address of the data to write;      |structure. Firstly decodes the      |
|   write_mem   |uint8_t pointer to the data to write buffer;|address and then verifies if needs  |
|               |uint8_t number of bytes to write;           |to create a new page. Then writes   |
|               |uint8_t flag to enable page creation;       |byte to byte to it;                 |
|===============|============================================|====================================|
|               |Table struct pointer;                       |Writes the data from the given      |
|               |uint64_t address of the data to write;      |address stored in memory to the     |
|   read_mem    |uint8_t pointer to the data return buffer;  |given return data buffer.           |
|               |uint8_t number of bytes to write;           |Returns 0 on success and 1 on a miss|
|===============|============================================|====================================|
```

### Description

This module provides the main memory communication interface between pythons implicit memory allocation and c explicit and dynamic memory allocation. It uses a standard paging system to store memory efficiently with a costume decoder of virtual addresses that goes through the standard directories in the x86 paging system standard:

```text
Linear Address
  [ Sign Extension ] [  PML4 Index  ]    [  PDPT Index  ] [  PD Index  ]     [  PT Index  ]      [  Offset  ]
       16 bits            9 bits             9 bits          9 bits              9 bits            12 bits
                          |                  |               |                   |                  |
       CR3 Register ------+                  |               |                   |                  |
         |                                   |               |                   |                  |
         v                                   v               v                   v                  v
  +--------------+                    +--------------+    +--------------+    +------------+     +---------------+
  |  PML4 Table  | -----------------> |  PDP Table   | -> |  Page Direct.| -> | Page Table | ->  | Physical Page |
  | (512 Entries)|                    | (512 Entries)|    | (512 Entries)|    | 512 Entries|     |  (4 KB Frame) |
  +--------------+                    +--------------+    +--------------+    +------------+     +---------------+
  ```

As a write or read call is made, the given uint64_t address is converted through the decoder to pointers to entries in each table of the system above. At the last table the offset is taken into account to return to the execution the correct pointer to the intended data, and the write/read routine can be initiated.
The purpose of this is to provide a more efficient way to store memory, similarly to x86's way, thats also easy to use through access calls. This way, each table entry initialized as a pointer to the next structure to use and the algorithm can run either recusively or through a loop. If the decoder lands on an uninitialized entry it will create a new one only if the page creation flag enables it.

---

### **Register engine**

---

### API

```text
+==================+======================================================+=========================================+
|     Function     |                      Parameters                      |                 Results                 |
+==================+======================================================+=========================================+
| CPURegs_create   | None                                                 | CPURegs pointer to the allocated and    |
|                  |                                                      | init'ed registers structure;            |
+==================+======================================================+=========================================+
| CPURegs_free     | CPURegs struct pointer;                              | Frees up the register structure from    |
|                  |                                                      | memory;                                 |
+==================+======================================================+=========================================+
| set_reg_sign     | CPURegs struct pointer;                              | Sets the signedness flag configuration  |
|                  | uint8_t register ID;                                 | for the specified register;             |
|                  | uint8_t signed flag status;                          |                                         |
+==================+======================================================+=========================================+
| is_signed        | CPURegs struct pointer;                              | Returns 1 if the specified register is  |
|                  | uint8_t register ID;                                 | signed, and 0 otherwise;                |
+==================+======================================================+=========================================+
|                  | CPURegs struct pointer;                              | Writes an integer value of a specified  |
|                  | uint8_t register ID;                                 | byte size to the targeted register;     |
| write_reg        | int64_t value to write;                              | If the is_high flag is enabled, targets |
|                  | uint8_t byte size of the write operation;            | the high-byte sub-register;             |
|                  | uint8_t flag to target high-byte;                    |                                         |
+==================+======================================================+=========================================+
| read_8b_reg      | CPURegs struct pointer;                              | Reads and returns a full 64-bit         |
|                  | uint8_t register ID;                                 | value from the target register;         |
+==================+======================================================+=========================================+
| read_4b_reg      | CPURegs struct pointer;                              | Reads and returns a 32-bit doubleword   |
|                  | uint8_t register ID;                                 | value from the target register;         |
+==================+======================================================+=========================================+
| read_2b_reg      | CPURegs struct pointer;                              | Reads and returns a 16-bit word         |
|                  | uint8_t register ID;                                 | value from the target register;         |
+==================+======================================================+=========================================+
|                  | CPURegs struct pointer;                              | Reads and returns an 8-bit byte value;  |
| read_1b_reg      | uint8_t register ID;                                 | Targets the high-byte if the is_high    |
|                  | uint8_t flag to target high-byte;                    | flag is set to 1;                       |
+==================+======================================================+=========================================+
| read_rflags      | CPURegs struct pointer;                              | Reads and returns the raw 32-bit status |
|                  |                                                      | value of the RFLAGS register;           |
+==================+======================================================+=========================================+
| read_trap_flag   | CPURegs struct pointer;                              | Returns the state (0 or 1) of the trap  |
|                  |                                                      | status flag;                            |
+==================+======================================================+=========================================+
| read_carry_flag  | CPURegs struct pointer;                              | Returns the state (0 or 1) of the carry |
|                  |                                                      | arithmetic flag;                        |
+==================+======================================================+=========================================+
| read_zero_flag   | CPURegs struct pointer;                              | Returns the state (0 or 1) of the zero  |
|                  |                                                      | condition flag;                         |
+==================+======================================================+=========================================+
| read_sign_flag   | CPURegs struct pointer;                              | Returns the state (0 or 1) of the sign  |
|                  |                                                      | status flag;                            |
+==================+======================================================+=========================================+
|read_overflow_flag| CPURegs struct pointer;                              | Returns the state (0 or 1) of the       |
|                  |                                                      | overflow condition flag;                |
+==================+======================================================+=========================================+
| write_rflags     | CPURegs struct pointer;                              | Explicitly writes an entire 32-bit state|
|                  | uint32_t RFLAGS value to write;                      | value directly to the RFLAGS register;  |
+==================+======================================================+=========================================+
| exch_rflag       | CPURegs struct pointer;                              | Toggles or updates a single specific bit|
|                  | uint8_t target flag ID;                              | within the RFLAGS layout;               |
+==================+======================================================+=========================================+
| set_trap_flag    | CPURegs struct pointer;                              | Directly asserts (sets to 1) the trap   |
|                  |                                                      | flag for execution stepping;            |
+==================+======================================================+=========================================+
```

### Description

This module provides an abstraction layer for simulating the internal CPU register file of an x86-64 processor architecture. It models the core execution states required by a low-level interpreter or emulator, encapsulating architectural registers, bit-width variations (supporting independent 64-bit, 32-bit, 16-bit, and 8-bit access slices), signedness metadata, and individual arithmetic condition/status flags.
The fundamental purpose of this module is to decouple the runtime state of a virtual execution engine from the host machine running it.
When building software that processes machine instructions (like an assembler interpreter or custom emulation layer), you cannot safely use the physical CPU registers of your host environment to execute guest code. This module solves that boundary problem by creating a deterministic, software-defined sandbox that replicates hardware register modifications line-by-line.
Using this type of abstraction separation also enables precise stepping and debugging on the entire state of the execution. Flag operations also become more predictable and accessible from the development side which enables a whole set of operations that englobe them and even the debugging with stepping via trap flag becomes manageable.
This module should be used the same way a register is, accessing through the provided list of registers by its order, the register size is set by the number of bytes to read/write from it and the signedness state is also set to the reading/writing access. Also, each register is expressed in a costume structure that store all important aspects related to its current use such as value and signedness.

```text
+=========+=======================+===================================================+
|  Reg ID |     Register Name     |                     Description                   |
+=========+=======================+===================================================+
|    0    | rax                   | Accumulator Register                              |
+=========+=======================+===================================================+
|    1    | rbx                   | Base Register                                     |
+=========+=======================+===================================================+
|    2    | rcx                   | Counter Register                                  |
+=========+=======================+===================================================+
|    3    | rdx                   | Data Register                                     |
+=========+=======================+===================================================+
|    4    | rsi                   | Source Index                                      |
+=========+=======================+===================================================+
|    5    | rdi                   | Destination Index                                 |
+=========+=======================+===================================================+
|    6    | rbp                   | Base Pointer                                      |
+=========+=======================+===================================================+
|    7    | rsp                   | Stack Pointer                                     |
+=========+=======================+===================================================+
|    8    | r8                    | General Purpose Register 8                        |
+=========+=======================+===================================================+
|    9    | r9                    | General Purpose Register 9                        |
+=========+=======================+===================================================+
|    10   | r10                   | General Purpose Register 10                       |
+=========+=======================+===================================================+
|    11   | r11                   | General Purpose Register 11                       |
+=========+=======================+===================================================+
|    12   | r12                   | General Purpose Register 12                       |
+=========+=======================+===================================================+
|    13   | r13                   | General Purpose Register 13                       |
+=========+=======================+===================================================+
|    14   | r14                   | General Purpose Register 14                       |
+=========+=======================+===================================================+
|    15   | r15                   | General Purpose Register 15                       |
+=========+=======================+===================================================+
```

---

### **Operations Engine**

---

### API

```text
+======================+======================================================+=========================================+
|       Function       |                      Parameters                      |                 Results                 |
+======================+======================================================+=========================================+
| create_operand_state | None                                                 | Info pointer to the newly allocated and |
|                      |                                                      | initialized operand/instruction state;  |
+======================+======================================================+=========================================+
| free_operand_state   | Info struct pointer;                                 | Frees up the entire Info state structure|
|                      |                                                      | from heap memory;                       |
+======================+======================================================+=========================================+
| set_registers_ref    | Info struct pointer;                                 | Binds a reference of the CPURegs state  |
|                      | CPURegs struct pointer;                              | to the main instruction execution state;|
+======================+======================================================+=========================================+
| set_table_ref        | Info struct pointer;                                 | Binds a reference of the paging Table   |
|                      | Table struct pointer;                                | structure to the current execution state;|
+======================+======================================================+=========================================+
|                      | Info struct pointer;                                 | Populates detailed metadata for an      |
|                      | char pointer to operand string;                      | instruction operand, including parsed   |
| set_operand_info     | long long absolute memory address;                   | address boundaries, immediate values,   |
|                      | long long evaluated operand value;                   | operand size, and typing classification;|
|                      | uint8_t byte size of the operand data;               |                                         |
|                      | char pointer to operand type token;                  |                                         |
|                      | uint8_t visual representation encoding flag;         |                                         |
+======================+======================================================+=========================================+
| set_instruction      | Info struct pointer;                                 | Sets the raw assembly instruction string|
|                      | char pointer to tokenized instruction mnemonic;      | context to be processed next;           |
+======================+======================================================+=========================================+
| clean                | Info struct pointer;                                 | Clears and resets the internal transient|
|                      |                                                      | instruction/operand data fields;        |
+======================+======================================================+=========================================+
| dispatch             | Info struct pointer;                                 | Routes and executes the decoded command |
|                      |                                                      | by changing register or memory state;   |
+======================+======================================================+=========================================+
```

### Description

This module serves as the central control unit and execution pipeline for the assembly interpreter. It acts as the bridge connecting your simulated hardware components—the CPU registers (CPURegs) and the paging memory structures (Table)—with the raw assembly instructions being parsed.
By utilizing a unified Info tracking state, the module acts like an architectural pipeline latch. It aggregates tokenized instruction mnemonics, extracts operand source/destination metadata, computes effective memory addresses, and maps out the exact visual representation of the execution cycle before routing the final decoded command to its designated backend executor.
The primary purpose of this module is to implement the Decode and Execute stages of a classic CPU instruction cycle within a software environment.
Instead of forcing individual instruction handlers to manually parse text, verify pointers, or resolve addresses, this module centralizes the heavy lifting. It ingests an instruction, builds its runtime execution context (Info), binds the necessary hardware resources safely via reference passing, and then cleanly fires the instruction through a central dispatch routing mechanism to modify the machine state uniformly.

```text
   =========================================================================================
                                  OPERAND STRUCTURE DATA LAYOUT
   =========================================================================================
+==================+=======================+===================================================+
|    Field Name    |       Data Type       |                     Description                   |
+==================+=======================+===================================================+
| address          | long long             | Absolute computed target physical/virtual address;|
+==================+=======================+===================================================+
| value            | long long             | Evaluated immediate integer or data payload;      |
+==================+=======================+===================================================+
| size             | uint8_t               | Data boundary size constraint (1, 2, 4, or 8 B);  |
+==================+=======================+===================================================+
| op_type          | char *                | Tokenized string indicating the type info;        |
+==================+=======================+===================================================+
| visual_rep       | uint8_t               | Log mode toggle (1 for text representation,       |
|                  |                       | 0 for numerical display representation);          |
+==================+=======================+===================================================+

   =========================================================================================
                               PIPELINE EXECUTION LATCH (INFO)
   ========================================================================================
+==================+=======================+===================================================+
|    Field Name    |       Data Type       |                     Description                   |
+==================+=======================+===================================================+
| instruction      | char *                | Raw tokenized string name of the instruction;     |
+==================+=======================+===================================================+
| op1              | Operand               | Struct data block isolating the first operand;    |
+==================+=======================+===================================================+
| op2              | Operand               | Struct data block isolating the second operand;   |
+==================+=======================+===================================================+
| registers        | CPURegs *             | Handle pointer to the active CPU register file;   |
+==================+=======================+===================================================+
| table            | Table *               | Handle pointer to the root paging memory tree;    |
+==================+=======================+===================================================+
| result           | Operand               | Storage slice for tracking output modifications;  |
+==================+=======================+===================================================+

   =========================================================================================
                            INSTRUCTION ROUTING DISPATCH MATRIX
   =========================================================================================
+=======================+============================+=========================================+
|  Mnemonic (String)    |   Backend C Execution Link |       Instruction Group Category        |
+=======================+============================+=========================================+
| "cmp"                 | exec_cmp                   | Data Path (Comparison Matrix)           |
+=======================+============================+=========================================+
| "add"                 | exec_add                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "adc"                 | exec_adc                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "sub"                 | exec_sub                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "sbb"                 | exec_sbb                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "inc"                 | exec_inc                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "dec"                 | exec_dec                   | Arithmetic Logic Unit (ALU)             |
+=======================+============================+=========================================+
| "and"                 | exec_and                   | Arithmetic Logic Unit (ALU Bits)        |
+=======================+============================+=========================================+
| "or"                  | exec_or                    | Arithmetic Logic Unit (ALU Bits)        |
+=======================+============================+=========================================+
| "xor"                 | exec_xor                   | Arithmetic Logic Unit (ALU Bits)        |
+=======================+============================+=========================================+
| "not"                 | exec_not                   | Arithmetic Logic Unit (ALU Bits)        |
+=======================+============================+=========================================+
| "neg"                 | exec_neg                   | Arithmetic Logic Unit (ALU Bits)        |
+=======================+============================+=========================================+
| "xchg"                | exec_xchg                  | Arithmetic Logic Unit (Data Swap)       |
+=======================+============================+=========================================+
```

---

## Shared Libraries (`interpreter/_src/lib/`)

### Overview

To maintain maximum runtime execution speed while keeping parsing and control flow high-level, all hardware state representation and execution logic are compiled into native shared objects (`.so`). These dynamic libraries are loaded at runtime by Python’s `ctypes` bridge layer (`interpreter/_src/bridges/`).

Dividing the C execution engine into separate dynamic libraries enforces modularity, isolates memory management from register manipulation, and speeds up incremental builds during development.

---

### Library Breakdown

#### 1. `libreg.so` — Register File Manager
* **Source Files:** `interpreter/_src/execution/src/registers.c`, `interpreter/_src/execution/include/registers.h`
* **Python Bridge:** `interpreter/_src/bridges/register_manager.py`
* **Responsibilities:**
  * Allocates and maintains the hardware register state (General Purpose Registers, FPU registers, `EFLAGS`).
  * Implements bit-masking and offset logic for sub-register resolution (e.g., mapping read/write requests for `eax`, `ax`, `al`, and `ah` onto the underlying 64-bit `rax` storage).
  * Manages flag register manipulation (`ZF`, `CF`, `SF`, `OF`, `TF`).

#### 2. `libmmu.so` — Memory Management Unit
* **Source Files:** `interpreter/_src/execution/src/memory_eng.c`, `interpreter/_src/execution/include/memory_eng.h`
* **Python Bridge:** `interpreter/_src/bridges/data_memory.py`
* **Responsibilities:**
  * Implements the simulated **4-level page table** virtual memory system.
  * Handles dynamic allocation of memory pages upon demand (Phase 1 mapping and runtime execution writes).
  * Enforces stack boundary constraints (`rsp` tracking) and triggers stack overflow conditions.
  * Handles multi-byte read and write operations, converting input byte streams into Little-Endian storage order within page allocations.

#### 3. `liboperations.so` — Execution & ALU Engine
* **Source Files:** `interpreter/_src/execution/src/operations.c`, `interpreter/_src/execution/include/operations.h`
* **Python Bridge:** Called through Functional Units (`interpreter/_src/FUs/`)
* **Responsibilities:**
  * Performs actual hardware-level machine instructions (`add`, `sub`, `mov`, `cmp`, `xor`, bitwise shifts, etc.).
  * Calculates arithmetic and logical conditions to update `EFLAGS` automatically following instruction execution.
  * Interacts with `libreg.so` and `libmmu.so` structures to mutate machine state during instruction execution.

---

### Compilation & Build System

The shared libraries are built using GCC with Position-Independent Code (`-fPIC`) enabled. The standard build flow is defined in the root `Makefile`:

```makefile
# Compiler & Flags
CC     = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC -Iinterpreter/_src/execution/include
LDFLAGS = -shared

LIB_DIR = interpreter/_src/lib
BUILD_DIR = build

# Targets
all: $(LIB_DIR)/libreg.so $(LIB_DIR)/libmmu.so $(LIB_DIR)/liboperations.so

$(LIB_DIR)/libreg.so:$(BUILD_DIR)/registers.o
	$(CC)$(LDFLAGS) -o $@ $^

$(LIB_DIR)/libmmu.so:$(BUILD_DIR)/memory_eng.o
	$(CC)$(LDFLAGS) -o $@ $^

$(LIB_DIR)/liboperations.so:$(BUILD_DIR)/operations.o
	$(CC)$(LDFLAGS) -o $@ $^
```

### Build Commands:

- `make`: Compiles all C source files into object files in `build/` and outputs `.so` libraries into `interpreter/_src/lib/`.
- `make clean`: Removes binary artifacts in `build/` and compiled `.so` shared libraries.

### C/Python & Symbol Binding

To ensure seamless interfacing with `ctypes`:

1. **Explicit C Calling Conventions**: All public interfaces functions in the C engine use default C calling conventions (`cdecl`).
2. **Opaque Pointer Passing**: Complex C structures (like the Page Table root or state structs) are passed back to Python as opaque pointer handles (void*/c_void_p), preventing Python from directly mutating low-level C pointers.
3. **Buffer Passing**: Data transfer for memory reads and writes uses contiguous unsigned byte buffers (`uint8_t*` mapped to `ctypes.POINTER(ctypes.c_uint8)`), minimizing translation overhead across the language boundary.

---

## Virtual Memory Architecture (`memory_eng.c`)

### 1. 4-Level Page Table Simulation
The virtual memory system models a standard x86-64 paging mechanism to provide a realistic 64-bit virtual address space while minimizing host memory consumption:

* **Page Directories:** Structured as a 4-level hierarchy (PML4 $\rightarrow$ PDPT $\rightarrow$ PD $\rightarrow$ PT).
* **Page Allocation:** Memory pages (4 KB) are dynamically allocated on demand during Phase 1 mapping or when write operations target unallocated valid virtual addresses.
* **Address Translation:** Virtual addresses are decomposed into 9-bit indices for each table level plus a 12-bit page offset:
  * Bits `47–39`: PML4 Index
  * Bits `38–30`: PDPT Index
  * Bits `29–21`: PD Index
  * Bits `20–12`: PT Index
  * Bits `11–0`: Page Offset

### 2. Stack Management & Bounds
* **Growth Direction:** The stack grows downward from higher virtual memory addresses toward lower addresses.
* **Stack Pointer (`rsp`):** Initialized to the top of the allocated stack region during setup.
* **Stack Overflow Detection:** PUSH operations evaluate whether the updated `rsp` breaches the minimum stack boundary. If an illegal boundary crossing occurs, execution halts and returns the `STACK_OVERFLOW` (exit code `5`) error state.

### 3. Endianness & Memory Buffers
* **Little-Endian Layout:** All multi-byte numerical writes store the least significant byte (LSB) at the base target address and most significant bytes at higher contiguous addresses.
* **Read Logic:** Reading $N$ bytes starting at address $A$ returns a contiguous byte sequence, stopping when either $N$ bytes have been retrieved or a null-terminator boundary is hit depending on the calling context.

---

## Register File Engine (`registers.c`)

### 1. Storage Structure
The register file maintains the full CPU state in native contiguous C memory blocks:

* **16 General Purpose 64-bit Registers:** `rax`, `rbx`, `rcx`, `rdx`, `rsi`, `rdi`, `rbp`, `rsp`, `r8` through `r15`.
* **FPU Register Set:** Dedicated floating-point registers.
* **EFLAGS Register:** A 32-bit register holding status flags.

### 2. Sub-Register Bit-Masking & Resolution
Sub-register accesses do not store separate values; instead, they apply dynamic masks and bit-shifts directly against the 64-bit parent register:

| Sub-Register | Bit Range Access | Operation / Mask |
| :--- | :--- | :--- |
| **64-bit** (e.g., `rax`) | Bits `0–63` | Direct 64-bit read/write |
| **32-bit** (e.g., `eax`) | Bits `0–31` | Read: `val & 0xFFFFFFFF`<br>Write: Zero-extends upper 32 bits |
| **16-bit** (e.g., `ax`) | Bits `0–15` | Read: `val & 0xFFFF`<br>Write: Preserves upper 48 bits |
| **8-bit Low** (e.g., `al`) | Bits `0–7` | Read: `val & 0xFF`<br>Write: Preserves upper 56 bits |
| **8-bit High** (e.g., `ah`) | Bits `8–15` | Read: `(val >> 8) & 0xFF`<br>Write: Preserves bits `0–7` and `16–63` |

### 3. EFLAGS Condition Codes
Instructions mutate status flags inside `EFLAGS` via dedicated C bit-manipulation helpers:

* **Zero Flag (`ZF`):** Set if the result of an operation is zero.
* **Sign Flag (`SF`):** Set if the most significant bit (MSB) of the result is 1 (negative).
* **Carry Flag (`CF`):** Set if an unsigned arithmetic operation generated a carry out or borrow.
* **Overflow Flag (`OF`):** Set if a signed arithmetic operation resulted in a signed overflow.
* **Trap Flag (`TF`):** Reserved bit set to enable single-step execution debugging mode.

---

## Operations & Execution Engine (`operations.c`)

### 1. Instruction Operations
`operations.c` contains native C functions for executing primitive machine operations:

* **Arithmetic:** `add`, `sub`, `inc`, `dec`, `imul`, `idiv`
* **Logical:** `and`, `or`, `xor`, `not`, `shl`, `shr`
* **Data Movement:** `mov`, `push`, `pop`
* **Comparison:** `cmp`, `test`

### 2. Automated Flag Calculation
Every arithmetic and logical function automatically re-evaluates and updates `EFLAGS` in `libreg.so` upon completion:

```c
  // Conceptual pattern for arithmetic addition in operations.c
  uint64_t op_add64(uint64_t dest, uint64_t src) {
      uint64_t result = dest + src;

      // Update EFLAGS
      set_flag_zf(result == 0);
      set_flag_sf((result & (1ULL << 63)) != 0);
      set_flag_cf(result < dest); // Unsigned overflow
      set_flag_of(((dest ^ result) & (src ^ result) & (1ULL << 63)) != 0); // Signed overflow

      return result;
  }
```
