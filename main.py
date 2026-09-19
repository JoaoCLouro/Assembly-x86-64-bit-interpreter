import os
import sys

from interpreter.exit_codes import ExitCode
from interpreter._src.parsing.segment_mapper import Segment_Mapper
from interpreter._src.parsing.control_unit import Control_Unit
from interpreter._src.helpers.storage import Storage

HELP_TEXT = """\
Usage: python main.py <path-to-assembly-file> [flags] [-- program-args...]

Flags:
  -d                    Force debugging mode ON (skips the interactive prompt).
  -s                    Strict mode: force debugging OFF and skip prompting
                        for the program's argv if none were supplied via --.
  -r, --num-rep <base>  Numeric base for the final-state printout: 2, 8, 10
                        (default), or 16. Same bases get_state()/to_json()
                        support in the Python API.
  -o, --output <path>   Export the final state as JSON to <path> (its parent
                        directory must already exist). Only written if the
                        interpreter didn't end on an irrecoverable error.
  -q, --quiet           Suppress the "CPU State Code" / "Final State" printout.
  -h, --help            Show this message and exit.
  --                    Toggles collection of the simulated program's own
                        argv. Everything between a -- and the next -- (or
                        end of the command line) is passed through as an
                        argument to the simulated program.

Examples:
  python main.py program.asm
  python main.py program.asm -d -- arg1 arg2
  python main.py program.asm -s -r 16 -o state.json
  python main.py program.asm -q -o state.json
"""

def main():
    """
    Main function to initialize and run the assembly interpreter.\n
    Requires a file path as a command line argument or user input.
    Prompts for command line arguments after validating the file path.\n
    CLI Usage: python main.py /path/to/assembly_file.asm -d (debugging_flags) -- <interpreter_arguments>\n
    Supported interpreter arguments:]\n -d (debugging_flags)\n -s (strick mode)  -- (separates interpreter arguments from the assembly file path)\n
    -r/--num-rep <base>, -o/--output <path>, -q/--quiet, -h/--help\n
    Debugging flags can be set to enable or disable debugging mode.\n
    Strick mode disables debugging and arguments prompting if missing.\n
    
    Author: João Carrilho Louro

    :return: None
    :rtype: None
    :requires: segment_mapper.py, control_unit.py, storage.py
    :example: python main.py /path/to/assembly_file.asm
    :note: Ensure the assembly file exists at the specified path.
    """
    if "-h" in sys.argv or "--help" in sys.argv:
        print(HELP_TEXT)
        return

    Storage.clean_cache()  # Clean cache before starting
    
    file = get_file()
    # seen_flags lookup:
    # first index = debugging_flags, second index = strick_mode
    # first index of each = seen, second index of each = enabled
    # 0 = -d (debugging_flags)
    # 1 = -s (strick mode)
    (flags, argv, num_rep, output_path, quiet) = parse_args(sys.argv[2:])

    if argv is None:
        argvcount: int = 0
    else:
        argvcount: int = len(argv)

    loader: Segment_Mapper = Segment_Mapper(file, argvcount, argv) 
    # -d forces debugging ON directly. -s (without -d) forces it OFF
    # without prompting. If neither flag is present, fall back to the
    # interactive prompt.
    if flags[0]:
        debugging = True
    elif flags[1]:
        debugging = False
    else:
        debugging = is_debugging()
    cpu: Control_Unit = Control_Unit(loader, debugging) 
    exit_code = cpu.run()
    state = cpu.get_state("all", num_rep)

    if not quiet:
        print(f"CPU State Code: \n {exit_code}")
        print(f"Final State: \n {state}")

    if output_path is not None:
        export_state(output_path, state, exit_code)

def get_file() -> str:
    """
    Get the file path from command line arguments or user input.

    :return: The file path
    :rtype: str
    """
    file_path: str = ""
    if len(sys.argv) != 2 or not valid_file(sys.argv[1]):
        while (file_path == ""):
                file_path = input("Enter the full path to the assembly file: ")
                if not valid_file(file_path):
                    file_path = ""
    return file_path if file_path else sys.argv[1]

def valid_file(file_path: str) -> bool:
    """
    Check if the provided file path points to a valid file.

    :param file_path: Path to the file to be checked
    :type file_path: str
    :return: True if the file exists, False otherwise
    :rtype: bool
    """
    if not os.path.isfile(file_path):
        print("File not found. Please try again.\n")
        return False
    return True

def get_args() -> list[str] | None:
    """
    Get command line arguments from user input.

    :return: List of command line arguments or None
    :rtype: list[str] | None
    """

    user_input: str = input("Enter command-line arguments separated by spaces (or press Enter for none): ")
    args: list[str] = user_input.split() if user_input.strip() else []
    return args if args else None

def parse_args(args_list: list[str]) -> tuple[list[bool], list[str] | None, int, str | None, bool]:
    """
    Parse command line arguments from a list.

    :param args_list: List of command line arguments
    :type args_list: list[str]
    :return: A tuple of (seen_flags [debugging, strict_mode], the simulated
        program's argv or None, the numeric base to print/export state in,
        the output JSON path or None, and whether -q/--quiet was given)
    :rtype: (list[bool], list[str] | None, int, str | None, bool)
    """
    accept_args_state: bool = False
    seen_args: list[bool] = [False, False]  # [debugging, strick_mode]
    parsed_args: list[str] | None = []
    num_rep: int = 10
    output_path: str | None = None
    quiet: bool = False

    i = 0
    while i < len(args_list):
        arg = args_list[i]
        if arg == "-d":
            seen_args[0] = True
        elif arg == "-s":
            seen_args[1] = True
        elif arg == "-q" or arg == "--quiet":
            quiet = True
        elif arg == "-r" or arg == "--num-rep":
            i += 1
            if i >= len(args_list):
                print(f"{arg} requires a value (2, 8, 10, or 16). Defaulting to 10.")
            else:
                try:
                    candidate = int(args_list[i])
                    if candidate in (2, 8, 10, 16):
                        num_rep = candidate
                    else:
                        print(f"{candidate} is not a supported numeric base (2, 8, 10, 16). Defaulting to 10.")
                except ValueError:
                    print(f"'{args_list[i]}' is not a valid integer for {arg}. Defaulting to 10.")
        elif arg == "-o" or arg == "--output":
            i += 1
            if i >= len(args_list):
                print(f"{arg} requires a destination path. Output export skipped.")
            else:
                output_path = args_list[i]
        else:
            if arg == "--":
                accept_args_state = not accept_args_state
                i += 1
                continue
            if accept_args_state:
                parsed_args.append(arg)
        i += 1

    if not parsed_args and not seen_args[1]:  # If no arguments are provided and strick mode is not enabled, prompt for arguments
        parsed_args = get_args()
    return seen_args, parsed_args, num_rep, output_path, quiet

def is_debugging():
    """
    Verifies if the program should be run in debugging mode.

    :return: True if debug is wanted, False otherwise
    :rtype: bool
    """
    debugging:int = -1
    while debugging == -1:
        answer:str = input("Run debugging mode? (yes/no)")
        match answer:
            case "yes":
                debugging = 1
            case "no":
                debugging = 0
            case _:
                continue
    return True if debugging == 1 else False

def export_state(path: str, state: dict[str, int | str], exit_code: ExitCode) -> None:
    """
    Exports the final state to a JSON file at the given path, mirroring
    Interpreter_x86.to_json()'s behavior: only writes if the parent
    directory already exists, and skips (with a message) if the
    interpreter's exit code indicates an irrecoverable error.

    :param path: Full destination file path for the exported JSON
    :type path: str
    :param state: The state dict to export (as returned by Control_Unit.get_state)
    :type state: dict[str, int | str]
    :param exit_code: The ExitCode returned by cpu.run()
    """
    import json
    from interpreter.exit_codes import ExitCode

    if exit_code == ExitCode.IRRECOVERABLE_ERROR:
        print("Interpreter ended on an irrecoverable error! Export skipped.")
        return

    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.isdir(parent_dir):
        print(f"Invalid output path! Parent directory does not exist: {parent_dir}")
        return

    with open(path, "w") as file:
        json.dump(state, file, indent=4)
    print(f"State exported to {path}")


if __name__ == "__main__":
    main()