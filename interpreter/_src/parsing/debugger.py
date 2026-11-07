"""
Debugging utilities for the parser.
"""

from enum import Enum
import sys

from interpreter._src.parsing.control_unit import Control_Unit

class InvalidCommandError(Exception):
    """Raised when an invalid command is entered in the debugger."""
    def __init__(self, command: str):
        print(f"Invalid command: {command}. Type 'help' for a list of commands.")

class Command(Enum):
    """GDB-like Debugger commands."""
    STEP = "step"
    CONTINUE = "continue"
    BREAK = "break"
    REMOVE_BREAK = "remove_break"
    LIST_BREAKS = "list_breaks"
    QUIT = "quit"

class Debugger:
    """
    A simple debugger for the parser.
    
    Main Fixtures:
        - GDB like commands for stepping through the parsing process.
        - Logging of parsing events and state changes.
        - `Textual` based CLI interface for interactive debugging.
    """
    
    def __init__(self, control_unit: Control_Unit):
        self.control_unit: Control_Unit = control_unit
        self.breakpoints: set[int] = set()
    
    def read_command(self) -> Command:
        """Read a command from the user."""
        command = input("(debugger) ").strip()
        try:
            return self._match_command(command)
        except InvalidCommandError as e:
            print(e)
            return self.read_command()  # Prompt again for a valid command
    
    
    # === Breakpoint Management ===
    
    def add_breakpoint(self, line_number: int):
        """Add a breakpoint at the specified line number."""
        self.breakpoints.add(line_number - 1)  # Adjust for 0-based indexing
        
    def remove_breakpoint(self, line_number: int):
        """Remove a breakpoint from the specified line number."""
        self.breakpoints.discard(line_number - 1)  # Adjust for 0-based indexing
    
    def list_breakpoints(self):
        """List all current breakpoints."""
        if not self.breakpoints:
            print("No breakpoints set.")
        else:
            print("Current breakpoints:")
            for bp in sorted(self.breakpoints):
                print(f"  Line {bp + 1}\n")
    
    # === Execution Control ===
    
    def step(self):
        """Step through the next instruction."""
        self.control_unit._step() # type: ignore
    
    def continue_execution(self) -> Control_Unit:
        """Continue execution until the next breakpoint or end of program."""
        while not self.control_unit.finished:
            if self.control_unit.rip in self.breakpoints:
                break
            else:
                self.step()
        return self.control_unit
    
    def quit(self):
        """Quit the debugger and exit the program."""
        print("Exiting debugger.")
        sys.exit(0)
        
            
    # === Command Matching ===
    
    def _match_command(self, command: str) -> Command:
        """
        Approximate the user input to a Command enum using fuzzy matching.
        If the input is ambiguous or does not match any command, raise an InvalidCommandError.
                
        :param command: The user input command string.
        :type command: str
        :return: The matched Command enum.
        :rtype: Command
        :raises InvalidCommandError: If the input is ambiguous or does not match any command.
        """
        possible_commands = [cmd for cmd in Command if cmd.value.startswith(command.lower())]                
        
        if len(possible_commands) == 1:
            return possible_commands[0]
        elif len(possible_commands) > 1:
            raise InvalidCommandError(f"Command '{command}' is ambiguous.")
        else:
            raise InvalidCommandError(f"Command '{command}' is not recognized.")