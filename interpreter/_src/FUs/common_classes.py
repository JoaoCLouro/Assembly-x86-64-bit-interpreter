import ctypes


# Opaque pointer types for C structs passed by pointer
class CPURegs(ctypes.Structure):
    pass


class Table(ctypes.Structure):
    pass


# Structure for each ALU operand's necessary info
class Operand(ctypes.Structure):
    _fields_ = [
        ("address", ctypes.c_longlong),  # long long
        ("op_type", ctypes.c_int),  # OpType (enum)
        ("size", ctypes.c_uint8),  # uint8_t
        ("is_high", ctypes.c_uint8),  # uint8_t
        ("is_signed", ctypes.c_uint8),  # uint8_t
    ]


# Structure for all necessary instruction info
class Info(ctypes.Structure):
    _fields_ = [
        ("registers", ctypes.POINTER(CPURegs)),  # CPURegs*
        ("table", ctypes.POINTER(Table)),  # Table*
        ("res_value", ctypes.c_ulonglong),  # unsigned long long
        ("op1_value", ctypes.c_ulonglong),  # unsigned long long
        ("op2_value", ctypes.c_ulonglong),  # unsigned long long
        ("op1", Operand),  # Operand
        ("op2", Operand),  # Operand
        ("result", Operand),  # Operand
        ("opcode", ctypes.c_int),  # Opcode (enum)
    ]
