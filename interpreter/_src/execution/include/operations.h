#ifndef OPERATIONS_H
#define OPERATIONS_H

#ifdef _WIN32
    #define EXPORT __declspec(dllexport)
#else
    #define EXPORT
#endif

#include "../include/memory_eng.h"
#include "../include/registers.h"
#include <string.h>
#include <ctype.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

// Compilation: gcc -O3 -shared -o libops.so -fPIC operations.c


// --------------------------------------------------
// Exposed Structures
// --------------------------------------------------

// Operation Info structure
typedef struct Info Info;

typedef enum {
    OP_MEMORY,
    OP_REGISTER,
    OP_IMMEDIATE
} OpType;

typedef enum {
    OP_NULL = -1,

    // ALU
    OP_CMP,
    OP_ADD,
    OP_ADC,
    OP_SUB,
    OP_SBB,
    OP_INC,
    OP_DEC,
    OP_AND,
    OP_OR,
    OP_XOR,
    OP_NOT,
    OP_NEG,
    OP_XCHG,
    OP_MUL,
    OP_IMUL,
    OP_DIV,
    OP_IDIV,
    OP_SHL,
    OP_SAL,
    OP_SHR,
    OP_SAR,
    OP_ROL,
    OP_ROR,
    OP_RCL,
    OP_RCR,

    // FPU
    // TO IMPLEMENT LATER
    OP_COUNT // Sentinel value representing total number of opcodes
} Opcode;

// ---------------------------------------------------
// Prototypes
// ---------------------------------------------------

// Pointer creation
/**
 * @brief Creates a pointer to the operand Info structure and returns it.
 */
EXPORT Info* create_operand_state ();

// Pointer freeing
/**
 * @brief Frees up the pointer from memory.
 * * Mainly for integration with python
 *
 * @param ptr Pointer to free
 */
EXPORT void free_operand_state (Info* ptr);

// Essential data structure setters

/**
 * @brief Sets the register reference to use for operations.
 *
 * @param current_state Pointer to the Info structure holding all operand, instruction result and registers info
 * @param r             Register structure holding all register info
 */
EXPORT void set_registers_ref (Info *current_state, CPURegs *r);

/**
 * @brief Sets the table reference to use for memory access operations.
 *
 * @param current_state Pointer to the Info structure holding all operand, instruction result and registers info
 * @param t             Table structure holding all paging info for memory access operations
 */
EXPORT void set_table_ref (Info *current_state, Table *t);

// Info setters
/**
 * @brief Sets the operand info in the structure.
 *
 * @param current_instruction_state Pointer to the Info structure holding all operand, instruction, registers and results info
 * @param operand   Address for the sequence of characters that define the operand to update
 * @param address   64 bit long Address of the operand if any
 * @param size      Number of bytes that the operand take (number of bytes as a char)
 * @param type      Address for the sequence of characters that define the data type of this operands value
 * @param is_high   Flag to state if the operand is the high low byte on the supported registers (ah/bh/ch/dh)
 * @param is_signed Flag to state if the operand is signed (1) or unsigned (0)
 */
EXPORT void set_operand_info (Info *current_instruction_state, char* operand, long long address, uint8_t size, uint8_t op_type, uint8_t is_high, uint8_t is_signed);

/**
 * @brief Sets the current instruction in use.
 *
 * @param current_instruction_state Pointer to the Info structure holding all operand, instruction, registers and results info
 * @param instruction               Instruction to execute
 */
EXPORT void set_instruction(Info *current_instruction_state, uint8_t instruction);

// Infor cleaner
/**
 * @brief Resets all Operand fields and Instruction of the Info structure to their default values (NULL for pointers, 0 for numerical values).
 *
 * @param current_instruction_state Pointer to the Info structure holding all operand, instruction, registers and results info
 */
EXPORT void clean(Info *current_instruction_state);

// Instruction dispatching prototypes
/**
 * @brief Instruction dispatcher using the lookup table in InstructionMap.
 * * Calls the function associated to the instruction string.
 *
 * @param current_state Pointer to the Info structure holding all operand, instruction and results info
 * @return 0 if the exit was successful, 1 if caught any 0 division
 */
EXPORT uint8_t dispatch(Info *current_instruction_state);

#endif // OPERATIONS_H
