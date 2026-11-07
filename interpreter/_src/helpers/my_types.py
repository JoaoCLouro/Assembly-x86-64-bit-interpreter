from typing import TYPE_CHECKING, TypeAlias, Union

if TYPE_CHECKING:
    # Only needed for static type checking -- importing these for real at
    # module load time creates a circular import, since data_path.py (and
    # friends) import LabelMap/etc. from this module.
    from interpreter._src.functional_units.alu import ALU
    from interpreter._src.functional_units.data_path import Data_Path
    from interpreter._src.functional_units.fpu import FPU

# Keep it simple and clean
Address: TypeAlias = int
WordSize: TypeAlias = int

# Section Info Aliases
# .data and .rodata: Mapping a name to its address and size
DataSectionInfo: TypeAlias = dict[str, dict[str, list[Address] | int]]

# .bss: Mapping a name to its list of addresses and size
BssSectionInfo: TypeAlias = dict[str, dict[str, list[Address] | int]]

# .text labels: Mapping a name to its index
LabelMap: TypeAlias = dict[str, int]

# Constants: Mapping name to its value and index
ConstantMap: TypeAlias = dict[str, dict[str, int | str]]

# For getting info on the valid_instructions.json file
InstructionSet: TypeAlias = dict[str, list[str] | dict[str, int]]

FU: TypeAlias = Union["ALU", "FPU", "Data_Path"]
