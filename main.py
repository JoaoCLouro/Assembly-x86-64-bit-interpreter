import os
import sys
from interpreter._src.parsing.segment_mapper import Segment_Mapper
from interpreter._src.parsing.control_unit import Control_Unit
from interpreter._src.helpers.storage import Storage

def main():
    """
    Main function to initialize and run the assembly interpreter.\n
    Requires a file path as a command line argument or user input.
    Prompts for command line arguments after validating the file path.\n
    CLI Usage: python main.py /path/to/assembly_file.asm -d (debugging_flags) -- <interpreter_arguments>\n
    Supported interpreter arguments:]\n -d (debugging_flags)\n -s (strick mode)  -- (separates interpreter arguments from the assembly file path)\n
    Debugging flags can be set to enable or disable debugging mode.\n
    Strick mode disables debugging and arguments prompting if missing.\n
    
    Author: João Carrilho Louro

    :return: None
    :rtype: None
    :requires: segment_mapper.py, control_unit.py, storage.py
    :example: python main.py /path/to/assembly_file.asm
    :note: Ensure the assembly file exists at the specified path.
    """
    Storage.clean_cache()  # Clean cache before starting
    
    file = get_file()
    # seen_flags lookup:
    # first index = debugging_flags, second index = strick_mode
    # first index of each = seen, second index of each = enabled
    # 0 = -d (debugging_flags)
    # 1 = -s (strick mode)
    (flags, argv) = parse_args(sys.argv[2:])

    if argv is None:
        argvcount: int = 0
    else:
        argvcount: int = len(argv)

    loader: Segment_Mapper = Segment_Mapper(file, argvcount, argv) 
    # Debugging mode is only reprompted if neither -d nor -s flags are seen, otherwise is defaulted to false
    cpu: Control_Unit = Control_Unit(loader, is_debugging() if not flags[0] and not flags[1] else False) 
    print(f"CPU State Code: \n {cpu.run()}")
    print(f"Final State: \n {cpu.get_state("all")}")

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

def parse_args(args_list: list[str]) -> tuple[list[bool], list[str] | None]:
    """
    Parse command line arguments from a list.

    :param args_list: List of command line arguments
    :type args_list: list[str]
    :return: A tuple containing a boolean indicating if debugging is enabled and a list of parsed command line arguments
    :rtype: (list[bool], list[str] | None)
    """
    accept_args_state: bool = False
    seen_args: list[bool] = [False, False]  # [debugging, strick_mode]
    parsed_args: list[str] | None = []
    for arg in args_list:
        if arg == "-d":
            seen_args[0] = True
        elif arg == "-s":
            seen_args[1] = True
        else:
            if arg == "--":
                accept_args_state = not accept_args_state
                continue
            if accept_args_state:
                parsed_args.append(arg)
    if not parsed_args and not seen_args[1]:  # If no arguments are provided and strick mode is not enabled, prompt for arguments
        parsed_args = get_args()
    return seen_args, parsed_args

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


if __name__ == "__main__":
    main()