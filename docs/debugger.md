# Debugger

A GDB-style debugger for the x86-64 interpreter. It wraps a `Control_Unit` and lets you pause execution, step through instructions, set breakpoints, and inspect registers and memory using commands modelled on [GDB](https://sourceware.org/gdb/documentation/).

It is built in layers so any front end can sit on top of it. A plain-terminal prompt (`repl()`) is included. A richer front end, such as a Textual app, can use the same parsing, execution and data methods without touching the terminal.

- [Starting the debugger](#starting-the-debugger)
- [Sample session](#sample-session)
- [How commands are matched](#how-commands-are-matched)
- [Command reference](#command-reference)
- [What the debugger prints](#what-the-debugger-prints)
- [Examples](#examples)
- [Differences from GDB](#differences-from-gdb)
- [Notes and limitations](#notes-and-limitations)
- [Using it from code](#using-it-from-code)
- [Testing](#testing)
- [Where to learn more](#where-to-learn-more)

## Starting the debugger

The debugger wraps an existing `Control_Unit`. It does not create one.

```python
from interpreter._src.parsing.debugger import Debugger

Debugger(control_unit).repl()
```

`repl()` shows the line about to run, then reads commands at the `(debugger)` prompt until you quit. When you quit, `repl()` **returns** instead of exiting the process, so the caller decides what happens next.

## Sample session

This is real output. The program is small, with a breakpoint at line 4.

```
1: _start:
(debugger) break 4
Breakpoint set at line 4.
(debugger) run
Breakpoint hit at line 4.
4: add rax, rbx
(debugger) stepi
5: push rax
(debugger) info registers rax
rax     3
(debugger) radix hex
Output radix set to hexadecimal (base 16).
(debugger) info registers eflags
eflags  0x246
(debugger) x/2wx $rsp
0x1000:   0x12345678   0xffffffff
(debugger) x/2dw $rsp
0x1000:   305419896    -1
(debugger) continue
hello from the program
Program finished.
(debugger) quit
Exiting debugger.
```

Text the program itself prints while it runs (`hello from the program` above) appears before the message saying why execution stopped.

Type `help` at any time to list the available commands.

## How commands are matched

Input is case-insensitive and matched in three steps, so you rarely need to type a full command:

1. **Exact aliases** are checked first (`r`, `s`, `si`, `c`, `b`, `d`, `i`, `h`, `q`).
2. **Exact command names** come next.
3. **Unique prefixes** are accepted last. If a prefix matches more than one command, you get an "ambiguous" error instead of a guess.

This works on both words of `info` commands, so all of these mean the same thing:

```
info registers
inf re
i r
```

Bad input never ends the session. You get an error message and the prompt comes back. Blank lines are ignored.

## Command reference

| Command | Aliases | What it does |
|---|---|---|
| `run` | `r` | Run until a breakpoint or the end of the program |
| `step instruction` | `s`, `si`, `stepi`, `step` | Execute exactly one instruction |
| `continue` | `c` | Resume until the next breakpoint or the end |
| `break LINE` | `b` | Set a breakpoint at a line number |
| `delete LINE` | `d` | Remove the breakpoint at a line number |
| `info breakpoints` | `i b`, `info b` | List all breakpoints |
| `info registers [REG]` | `i r`, `info reg` | Show all registers, or just one |
| `x/NFU ADDRESS` | `x` | Examine memory |
| `radix [BASE]` | | Show or change the numerical representation |
| `help` | `h` | List commands |
| `quit` | `q`, `exit` | Leave the debugger |

`run` and `continue` do the same thing. Neither restarts the program.

### Running

- **`step instruction`** executes one instruction and shows the next line.
- **`run` / `continue`** execute until a breakpoint is reached or the program ends. The first instruction always runs before breakpoints are checked, so continuing while stopped on a breakpoint moves past it. The same applies to `run` from the starting line: a breakpoint on that line does not stop it.
- After the program has ended, `continue` says `The program is not being run.` and `step` says `Program has finished.` Neither executes anything.

### Breakpoints

- `break LINE` and `delete LINE` take a positive line number, counted from 1.
- Setting a breakpoint that already exists, or deleting one that doesn't, is reported and changes nothing.
- `info breakpoints` lists the lines currently set, in numeric order.

### Registers

`info registers` shows every register. `info registers REG` shows one. The leading `$` is optional here (`rax` and `$rax` are equivalent), and names are case-insensitive.

You can request:

- **64-bit general-purpose registers:** `rax`, `rbx`, `rcx`, `rdx`, `rsi`, `rdi`, `rbp`, `rsp`, `r8` to `r15`
- **Sub-registers:** `eax`, `ax`, `al`, `ah`, `si`, `sil`, `r8d`, and so on, shown at their real width
- **`rip`:** the instruction pointer (see [Notes](#notes-and-limitations))
- **`eflags`:** the whole flags register, read directly from the register file
- **Individual flags:** `zf`, `cf`, `sf`, `of`, `pf`, `tf`

### Examining memory

```
x/NFU ADDRESS
```

`N`, `F` and `U` are all optional. The count comes first, then the format and unit letters in any order.

| Part | Meaning | Values | Default |
|---|---|---|---|
| `N` | How many units to show | any positive number | `1` |
| `F` | Format | `x` hex, `d` signed decimal, `u` unsigned decimal | `x` |
| `U` | Unit size | `b` 1 byte, `h` 2 bytes, `w` 4 bytes, `g` 8 bytes | `g` |

`ADDRESS` is either a number (`0x4010a0` or `4198560`) or a register written **with** a `$` (`$rsp`). Memory is read little-endian.

### Numerical representation

```
radix            show the current base
radix 16         switch to hexadecimal
radix hex        same thing
```

Accepted values are `2`, `8`, `10`, `16`, or `bin`, `oct`, `dec`, `hex`. The default is `10`.

The radix applies to **register output**. `x/` has its own format letters and is not affected by it.

## What the debugger prints

| Situation | Output |
|---|---|
| Stopped after a step | `5: push rax` (the next line, as `N: instruction`) |
| Stopped at a breakpoint | `Breakpoint hit at line 4.` then the line |
| Program ended normally | `Program finished.` |
| Program called `sys.exit` | `Program exited with code 3 at line 7.` (with the code's name when it has one, e.g. `7 (INVALID_SYSCALL)`) |
| Emulated CPU fault | `CPU exception: <message> at line 4.` |
| `info registers` | One row per register: the name padded to 8 characters, then the value |
| `x/NFU` | Rows of an address and then the values. Hex values are zero-padded to the unit width. Rows hold 8 bytes or halfwords, 4 words, or 2 giants |
| Problem with a command | The error message, for example `Unknown register: 'foo'.` or `Cannot access memory at 0x9000: ...` |

If a line is a label, it is shown as the label (`1: _start:`).

## Examples

Stop at line 20 and look at the state:

```
(debugger) break 20
(debugger) run
(debugger) info registers
(debugger) info registers rax
(debugger) info registers eflags
```

Walk the program one instruction at a time:

```
(debugger) stepi
(debugger) si
(debugger) info registers rip
```

See registers in hexadecimal, then go back:

```
(debugger) radix hex
(debugger) info registers
(debugger) radix dec
```

Look at the top of the stack:

```
(debugger) x/4gx $rsp         4 eight-byte values, in hex
(debugger) x/8bx $rsp         8 single bytes, in hex
(debugger) x/2dw $rsp         2 four-byte values, signed decimal
(debugger) x/gx 0x7ffe0000    one eight-byte value at a fixed address
```

Manage breakpoints:

```
(debugger) break 12
(debugger) break 30
(debugger) info breakpoints
(debugger) delete 12
(debugger) continue
```

Partial commands:

```
(debugger) inf re rax         info registers rax
(debugger) br 12              break 12
(debugger) cont               continue
(debugger) ra hex             radix hex
```

## Differences from GDB

| GDB | This debugger |
|---|---|
| `stepi` / `si` | `step instruction`, with `stepi`, `si` and `s` as aliases |
| `set output-radix 16` | `radix 16` |
| `run` restarts the program | `run` behaves like `continue` |
| An empty line repeats the last command | Empty lines are ignored |
| `info registers` shows `rip` as an address | `rip` is an instruction index |
| `info registers eflags` decodes flags, like `[ ZF PF ]` | `eflags` is shown as a number, in the current radix |
| `x/s`, `x/i`, `x/c`, `x/o`, `x/t` | Only formats `x`, `d`, `u` |
| Unit letters `b h w g` | Same |
| Breakpoints by function, symbol or `*address` | Breakpoints by line number only |
| `x/4dw my_array` (symbols as addresses) | Addresses must be numbers or `$register` |

## Notes and limitations

- **`rip` is an instruction index, not a memory address.** Breakpoints are compared against it, so `break N` stops at line `N` of the program. Label lines count as lines, so the first line shown can be the `_start:` label. Stepping past it is a no-op.
- **Registers in addresses are read as numbers.** `x/4gx $rsp` works in any radix, because the address lookup always uses base 10 internally.
- **Radix only affects registers.** Use `x/` format letters to choose how memory is shown.
- **Unreadable memory is reported, not fatal.** Only `MemoryError` from the memory model is turned into a "Cannot access memory" message. Any other exception from it is a bug and propagates.
- **Program output is captured, not printed.** Anything the emulated program writes through Python's `sys.stdout` while it runs is collected and returned (`take_output()` / `CommandResult.output`). Output written by other means, such as `os.write`, and anything the program reads from stdin, bypass this.
- **`sys.exit` inside the interpreter is caught.** The control unit exits the process on some errors, such as a bad instruction or a missing exit. The debugger reports these as a stop (`Program exited with code N`) and carries on.
- **`quit` does not exit the process.** It ends `repl()` or sets `CommandResult.quit`. The caller decides what happens next.
- **Errors never end the session.** Only `quit` and Ctrl-D do. Ctrl-C at the prompt prints a reminder instead of quitting.

## Using it from code

Everything except `read_command` and `repl` is free of `print`, `input` and `sys.exit`, so a GUI or TUI can use it safely. A test enforces this.

### Layers

| Layer | Methods | Returns |
|---|---|---|
| Parsing | `parse(line)` | A validated `ExecutionCommand`. No I/O. Raises `InvalidCommandError` for bad input |
| Executing | `execute(ec)`, `submit(line)` | A `CommandResult`. Never raises for user errors. `submit` also parses, and returns an empty result for a blank line |
| Running | `step()`, `run_chunk(n)`, `continue_execution()` | A `Stop`. `run_chunk` returns `None` if `n` instructions ran and the program is still going |
| Fetching | `read_registers(reg, num_rep)`, `examine_memory(addr, count, unit, fmt)`, `resolve_address(ec)` | Dicts of values |
| Breakpoints | `add_breakpoint(line)`, `remove_breakpoint(line)`, `breakpoint_lines()` | `bool`, `bool`, `list[int]` (1-based) |
| Source | `source_lines()`, `current_line()`, `program_lines()` | `SourceLine` objects, or display strings |
| Settings | `set_radix(base=None)` | The base in effect (queries it when `base` is `None`) |
| Output | `take_output()` | Program text printed since the last call, then cleared |
| Console | `read_command()`, `repl()` | The only methods that use the terminal |

### Result types

- **`CommandResult`:** `lines` holds the text to show, `ok` is `False` when the command was rejected, `output` is captured program text, and `quit` is set by `quit`. The other fields carry the same information as data so panels need no text parsing: `stop`, `registers`, `memory` (with `memory_unit` and `memory_fmt`), `breakpoints` and `radix`. `text` joins `lines`.
- **`Stop`:** `reason` is a `StopReason` (`STEPPED`, `BREAKPOINT`, `FINISHED`, `EXITED`, `FAULT`), plus `line` (1-based, the next line to run) and, for exits and faults, `exit_code`, `exit_name` and `message`.
- **`SourceLine`:** `number` (1-based), `text`, `is_current` and `has_breakpoint`.

### Staying responsive

`run` and `continue` block until the program stops, so `execute` blocks on them too. A front end that must stay responsive should run the program in chunks instead:

```python
stop = None
while stop is None:
    stop = debugger.run_chunk(1000)
    await asyncio.sleep(0)  # let the UI breathe
result = debugger.stop_result(Command.CONTINUE, stop)  # lines + captured output
```

Because chunks run on the event loop, the front end can also stop between them, and nothing reads the simulator's state from another thread.

After each command, refresh the panels from `read_registers()`, `source_lines()` and `breakpoint_lines()`, and close when `result.quit` is set.

## Testing

The tests are in `tests/parser/test_debugger.py` and run with `pytest`. They use small fakes of the control unit, register file and memory, so they don't need the compiled C library.

Two settings at the top of the test file may need adjusting:

- `DEBUGGER_MODULE` is the import path of the debugger.
- `UNMAPPED_ERROR` is the exception the fake memory raises for an unmapped address. It is `MemoryError`, matching what `Data_Memory.read_bytes` raises.

`TestRealRegisterPattern` runs against the project's real `REGISTER_PATTERN`, so a failure there means the parser rejects a register name the register file supports.

## Where to learn more

Since the command syntax follows GDB, its documentation is the best reference for anything not covered here.

- **GDB documentation home:** <https://sourceware.org/gdb/documentation/>
- **GDB User Manual (current):** <https://sourceware.org/gdb/current/onlinedocs/gdb/>
- **Breakpoints:** <https://sourceware.org/gdb/current/onlinedocs/gdb/Set-Breaks.html>
- **Continuing and stepping:** <https://sourceware.org/gdb/current/onlinedocs/gdb/Continuing-and-Stepping.html>
- **Examining memory (`x`):** <https://sourceware.org/gdb/current/onlinedocs/gdb/Memory.html>
- **Registers:** <https://sourceware.org/gdb/current/onlinedocs/gdb/Registers.html>
- **Output formats and radix:** <https://sourceware.org/gdb/current/onlinedocs/gdb/Output-Formats.html> and <https://sourceware.org/gdb/current/onlinedocs/gdb/Numbers.html>

If GDB is installed locally, `help COMMAND` inside it (for example `help x`) and `info gdb` in a terminal show the same material offline.
