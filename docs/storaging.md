# Storage

A static-method utility class for reading and writing JSON files with one primary functionality:

* **General-purpose JSON storage** (`save_file`, `save_file_dictionary`,
   `load_file`, `load_file_lines`, `convert_to_json`) — these always operate
   relative to `PROJECT_DIR`, the folder containing `storage.py` itself, so
   the class manages its own files consistently no matter where the program
   is launched from.

```python
from storage import Storage
```

Every method is a `@staticmethod` — you never instantiate `Storage`, you just
call `Storage.method_name(...)`.

---

## Function reference

### `Storage.save_file(file_name: str, data: list[str] | list[list[str]]) -> None`

Writes `data` to `file_name` as pretty-printed JSON (`indent=4`), inside
`PROJECT_DIR`. Always overwrites if the file already exists.

- **Raises `SyntaxError`** if `file_name` does not end in `.json`.
- **Use case:** persist a cleaned list of instruction lines, or any
  list-shaped data, as JSON.

```python
Storage.save_file("lines.json", ["mov eax, 1", "add eax, ebx"])
```

---

### `Storage.save_file_dictionary(file_name: str, data: dict[str, str | dict[str, int]]) -> None`

Writes a dictionary to `file_name` as pretty-printed JSON, inside
`PROJECT_DIR` — but **only if the file does not already exist**. If it
exists, this call is a silent no-op (existing content is preserved).

- **Raises `SyntaxError`** if `file_name` does not end in `.json`.
- **Use case:** seed a default settings/config file once, without ever
  clobbering an existing, possibly customized, copy.

```python
Storage.save_file_dictionary("settings.json", {"valid start": "_start", "alu": {}})
```

---

### `Storage.load_file(file_name: str) -> str`

Reads and returns the full text contents of `file_name` from `PROJECT_DIR`.

- **On a missing file:** prints an error message and calls `sys.exit(-1)` —
  this terminates the program rather than raising a normal exception the
  caller could catch (only `SystemExit` propagates).
- **Use case:** read a raw source file (e.g. an assembly listing) before
  further processing.

```python
text = Storage.load_file("program.asm")
```

---

### `Storage.load_file_lines(file_name: str) -> list[str]`

Reads `file_name` from `PROJECT_DIR` as JSON and returns the parsed result
(typically a `list[str]` previously written by `save_file`/`convert_to_json`).

- **Raises `FileNotFoundError`** if the file doesn't exist — there is no
  try/except here, unlike `load_file`.
- **Raises `json.JSONDecodeError`** if the file's contents aren't valid JSON.
- **Use case:** re-load a previously converted/cleaned instruction list.

```python
lines = Storage.load_file_lines("program.json")
```

---

### `Storage.convert_to_json(file_name: str) -> str`

Converts an arbitrary text file into a JSON array of "cleaned" lines, and
returns the new file's name.

Steps:
1. Reads `file_name` via `load_file`.
2. Splits on `"\n"`.
3. For each line, if it contains a `;`, keeps only the text before the `;`
   (comment stripping).
4. Strips whitespace from each surviving line.
5. Writes the resulting list to `<name-without-extension>.json` via
   `save_file`.

- **New filename rule:** the new name is `file_name.split(".")[0] + ".json"` —
  so `program.asm` → `program.json`. Note that for names with more than one
  dot, e.g. `my.program.asm`, everything after the *first* dot is discarded,
  giving `my.json`.
- **Use case:** turn a semicolon-commented assembly source file into a clean
  JSON list of instruction lines, stripping inline comments.

```python
json_name = Storage.convert_to_json("program.asm")  # -> "program.json"
```

**A subtlety worth knowing:** the empty-line skip check (`if line == "":
continue`) compares the text *before* stripping. A line like
`"  ; a comment"` becomes `"  "` after splitting on `;` — not `""` — so it is
not skipped; an empty string is appended instead. Only comment-only lines
with **zero** characters before the `;` (e.g. `";comment"`) are actually
dropped from the output. This is documented and covered by tests so it stays
predictable even if not the most obvious behavior at a glance.

---


## Typical usage flow

```python
from storage import Storage

# Clean up a raw assembly source file into a JSON list of instructions
json_file = Storage.convert_to_json("program.asm")
program_lines = Storage.load_file_lines(json_file)

# Validate each line's opcode against `instructions`, using `start_label`
#    to check the entry point declaration, etc.
```

---

## Other implementation notes

- **`save_file_dictionary` never force-overwrites.** If you need to replace
  an existing settings file, delete it first or use `save_file` directly
  (note `save_file`'s type hint expects a list, though Python won't stop you
  from passing a dict at runtime).
- **`load_file` vs. `load_file_lines` error handling differs.** `load_file`
  catches `FileNotFoundError` and exits the process; `load_file_lines` lets
  `FileNotFoundError` propagate normally to the caller.
- **`convert_to_json` derives its output name from the first `.` in the
  input name**, not the last one.

---

## Running the tests

Keep `test_storage.py` in your own tests directory alongside a copy of (or
import path to) `storage.py`.

```bash
pip install pytest
pytest test_storage.py -v
```

The suite uses `pytest`'s `tmp_path` and `monkeypatch` fixtures to sandbox
every test in its own temporary directory — including pointing
`Storage.PROJECT_DIR` at that directory and `chdir`-ing into it — so tests
never touch real project files, never depend on where the test file itself
lives, and never affect each other. It covers:

- Normal-path behavior for every method.
- Error paths (`SyntaxError`, `FileNotFoundError`, `KeyError`,
  `json.JSONDecodeError`, `SystemExit`).
- The cwd-vs-`PROJECT_DIR` split between the general storage helpers and the
  execution-start helpers, as explicit tests, so the intended behavior is
  locked in and any future change is a deliberate, visible one.
- The comment-stripping subtlety in `convert_to_json`, and the first-dot
  filename derivation.
- Integration tests exercising the natural `initialize → read` and
  `convert → load` round trips.
