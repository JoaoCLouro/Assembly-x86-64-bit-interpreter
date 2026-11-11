import json
import os
import sys

from ._src.helpers.storage import Storage
from ._src.parsing.control_unit import Control_Unit
from ._src.parsing.segment_mapper import Segment_Mapper
from .exit_codes import ExitCode


class Interpreter_x86:
    """
    Class to initialize and run the assembly interpreter.\n
    Requires a file path as a command line argument or user input.
    Prompts for command line arguments after validating the file path.\n
    Enables state observation after it stops running.

    Author: João Carilho Louro
    """

    __slots__ = ["cpu", "loader", "memory", "register", "state", "state_code"]

    def __init__(
        self, file_name: str | None, args: list[str] | None
    ):
        """
        Initializes and runs the interpreter.\n
        After running you can get the state of the program.\n
        When finished you need to call clean() to free all the used memory!
        """
        # current process state
        self.state: dict[str, int | str] = {}

        if not file_name:
            file_name = Interpreter_x86._get_file()
        if not args:
            args = Interpreter_x86._get_args()

        Storage.clean_cache()  # Clean cache before starting

        self.loader: Segment_Mapper = Segment_Mapper(
            file_name, len(args) if args else 0, args
        )
        self.memory = self.loader.memory
        self.register = self.loader.registers
        self.cpu: Control_Unit = Control_Unit(self.loader)

    def __del__(self):
        # Triggers all state variables cleanup
        self.cpu = None  # type: ignore
        self.loader = None  # type: ignore
        if self.memory:
            self.memory.clean()
        if self.register:
            self.register.clean()

    def run(self) -> ExitCode:
        """
        Runs the interpreter and returns the appropriate exit code sent by the interpreter in case of a savable exit code.\n
        If the program fails at segment parsing returns an unrecoverable exit status
        """
        self.state_code = (
            ExitCode.IRRECOVERABLE_ERROR
            if self.loader.exit_status != ExitCode.SUCCESS
            else self.cpu.run()
        )
        return self.state_code

    def exit(self) -> dict[str, int | str] | None:
        """
        Clears all space used by the interpreter's execution components saving its state in an accessible variable
        or returning None if the exit code was an irrecoverable error.\n
        After calling this method you can access 'self.state' and get the full information of the process when it finished
        This method also returns this same state if needed

        :return: The state of the process when it finished or None if the an irrecoverable error ended the interpreter
        :rtype: dict[str, int] | None
        """
        if self.state_code == ExitCode.IRRECOVERABLE_ERROR:
            self._clear_state()
            print("Interpreter ended on an irrecoverable error! Export invalid")
            return None
        # Safe because its ensured the string 'all' is supported
        self.state = self.get_state("all")
        self._clear_state()
        return self.state

    def _clear_state(self) -> None:
        """
        Clears attributes used in by the interpreter
        """
        self.cpu = None  # type: ignore
        self.loader = None  # type: ignore
        if self.memory:
            self.memory.clean()
        if self.register:
            self.register.clean()

    # ------------------
    # State Fetching Methods
    # ------------------

    def get_state(
        self, section: str, numerical_representation: int = 16
    ) -> dict[str, int | str]:
        """
        Returns a snapshot of observable CPU/memory state as a dict of
        name -> current value, for the given named section.\n
        This is the return-value counterpart to print_section/
        execute_state_command's inspection commands: same underlying reads,
        same threaded fetch for memory sections, but handed back as data
        instead of printed to stdout — useful for tests or any caller that
        wants to assert on or further process the state rather than just
        display it.

        :param section: Which piece of state to fetch: 'all', 'data', 'rodata', 'bss', or 'registers'
        :type section: str
        :param num_rep: Numerical Representation type to give state in (10 for decimal, 8 for octal, 16 for hexadecimal and 2 for binary)
        :type num_rep: int
        :return: Mapping of variable/register name to its current signed value
        :rtype: dict[str, int]
        :raises ValueError: If section is not one of the recognized names
        """
        if numerical_representation not in [2, 8, 10, 16]:
            print(
                f"{numerical_representation} not supported as a numerical representation type. Defaulting to 16"
            )
            numerical_representation = 16
        return self.cpu.get_state(section, numerical_representation)

    def to_json(self, path: str, numerical_representation: int = 10) -> str | None:
        """
        Exports the final state of the interpreter to a JSON file at the
        exact destination path provided by the caller.\n
        `path` is the full destination FILE path, not a directory. If a file already
        exists at `path`, it is overwritten.\n
        The parent directory of `path` must already exist; this method
        does not create directories.

        :param path: Full destination file path for the exported JSON (parent directory must already exist)
        :type path: str
        :param num_rep: Numerical Representation type to export state in (10 for decimal, 8 for octal, 16 for hexadecimal and 2 for binary)
        :type num_rep: int
        :return: The same `path` that was written to, or None if the export failed (interpreter did not exit successfully, or the parent directory doesn't exist)
        :rtype: str | None
        """
        if self.state_code == ExitCode.IRRECOVERABLE_ERROR:
            print("Interpreter ended on an irrecoverable error! Export invalid")
            return None

        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.isdir(parent_dir):
            print(
                f"Invalid path provided! Parent directory does not exist: {parent_dir}"
            )
            return None

        if numerical_representation not in [2, 8, 10, 16]:
            print(
                f"{numerical_representation} not supported as a numerical representation type. Defaulting to 16"
            )
            numerical_representation = 16

        Interpreter_x86._export_state_to(
            path, self.get_state("all", numerical_representation)
        )
        return path

    # ------------------
    # Static Methods
    # ------------------

    @staticmethod
    def _get_file() -> str:
        """
        Get the file path from command line arguments or user input.

        :return: The file path
        :rtype: str
        """
        file_path: str = ""
        if len(sys.argv) != 2 or not Interpreter_x86._valid_file(sys.argv[1]):
            while file_path == "":
                file_path = input("Enter the full path to the assembly file: ")
                if not Interpreter_x86._valid_file(file_path):
                    file_path = ""
        return file_path if file_path else sys.argv[1]

    @staticmethod
    def _valid_file(file_path: str) -> bool:
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

    @staticmethod
    def _get_args() -> list[str] | None:
        """
        Get command line arguments from user input.

        :return: List of command line arguments or None
        :rtype: list[str] | None
        """
        user_input: str = input(
            "Enter command-line arguments separated by spaces (or press Enter for none): "
        )
        args: list[str] = user_input.split() if user_input.strip() else []
        return args if args else None

    @staticmethod
    def _export_state_to(path: str, state: dict[str, int | str]) -> None:
        """
        Exports the contents of state to a json file in the `path` provided.

        :param path: Path to store the exported file at
        :type path: str
        :param state: Contents to store
        :type state: dict[str, int]
        """
        with open(path, "w") as file:
            json.dump(state, file, indent=4)
