# Debugger

A small GDB-style debugger for the x86-64 interpreter. It wraps a `Control_Unit` and lets you pause execution, step through instructions, set breakpoints, and inspect registers and memory using commands modelled on [GDB](https://sourceware.org/gdb/documentation/).

- [Quick start](#quick-start)
- [How commands are matched](#how-commands-are-matched)
- [Command reference](#command-reference)
- [Examples](#examples)
- [Differences from GDB](#differences-from-gdb)
- [Notes and limitations](#notes-and-limitations)
- [Python API](#python-api)
- [Where to learn more](#where-to-learn-more)

## Quick start

The debugger prompt is:

```
(debugger)
```

Type a command and press Enter. A good first session:

```
(debugger) break 12
(debugger) run
(debugger) info registers
(debugger) x/4gx $rsp
(debugger) stepi
(debugger) continue
(debugger) quit
```

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

Bad input never crashes the prompt. You get a usage message and are asked again.

## Command reference

| Command | Aliases | What it does |
|---|---|---|
| `run` | `r` | Run the program until a breakpoint or the end |
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

### Breakpoints

- `break LINE` and `delete LINE` take a positive line number, counted from 1.
- `info breakpoints` lists the lines currently set.

### Registers

`info registers` shows every register. `info registers REG` shows one. The leading `$` is optional here (`rax` and `$rax` are equivalent), and names are case-insensitive.

You can request:

- **64-bit general-purpose registers:** `rax`, `rbx`, `rcx`, `rdx`, `rsi`, `rdi`, `rbp`, `rsp`, `r8` to `r15`
- **Sub-registers:** `eax`, `ax`, `al`, `ah`, `sil`, `r8d`, and so on, shown at their real width
- **`rip`:** the instruction pointer (see [Notes](#notes-and-limitations))
- **`eflags`:** the whole flags register
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
| `info registers` shows `rip` as an address | `rip` is an instruction index |
| `x/s`, `x/i`, `x/c`, `x/o`, `x/t` | Only formats `x`, `d`, `u` |
| Unit letters `b h w g` | Same |
| Breakpoints by function, symbol or `*address` | Breakpoints by line number only |
| `x/4dw my_array` (symbols as addresses) | Addresses must be numbers or `$register` |
| Only 6 status flags tracked | `eflags` is built from the flags the simulator stores, so untracked flags read as 0 |

## Notes and limitations

- **`rip` is an instruction index, not a memory address.** Breakpoints are compared against it, so `break N` stops at line `N` of the program.
- **Registers in addresses are read as numbers.** `x/4gx $rsp` works in any radix, because the address lookup always uses base 10 internally.
- **Radix only affects registers.** Use `x/` format letters to choose how memory is shown.
- **Bad memory reads** (for example an unmapped address) report an error instead of crashing.
- **Errors never exit the debugger.** Only `quit` does.

## Python API

For tests or scripting, the same functionality is available without the prompt. Methods that fetch data return values and do not print.

| Method | Returns |
|---|---|
| `read_command()` | A validated `ExecutionCommand` from the prompt |
| `add_breakpoint(line)` / `remove_breakpoint(line)` | Updates the breakpoint set |
| `list_breakpoints()` | Prints the current breakpoints |
| `step()` | Runs one instruction |
| `continue_execution()` | Runs until a breakpoint or the end |
| `set_radix(base=None)` | The base now in effect (queries it if `base` is `None`) |
| `_read_registers(register=None, num_rep=None)` | `{name: value}` for one or all registers, in the current radix |
| `_examine_memory(address, count, unit, fmt)` | `{address: value}` in address order |

`ExecutionCommand` holds the parsed command with its validated arguments: `line` for breakpoints, `register` for `info registers`, `count`, `fmt`, `unit` and the address for `x`, and `radix` for `radix`.

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