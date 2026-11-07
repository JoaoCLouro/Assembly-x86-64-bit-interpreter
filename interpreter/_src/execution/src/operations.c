#include "../include/operations.h"


// --------------------------------------------------------------------------------
// Structures implementations
// --------------------------------------------------------------------------------

// Structure for each alu operand's necessary info
typedef struct Operand{
    long long address;  // virtual address for memory or index for registers
    OpType op_type;
    uint8_t size;       // 1,2,4,8
    uint8_t is_high;
    uint8_t is_signed;  // only for registers
} Operand;

// To be implemented a fpu operand struct

// Structure for all necessary instruction info
struct Info {
    CPURegs* registers;
    Table* table;
    unsigned long long res_value;
    unsigned long long op1_value;
    unsigned long long op2_value;
    Operand op1;
    Operand op2;
    Operand result;
    Opcode opcode;
};

// --------------------------------------------------------------------------------
// Prototypes
// --------------------------------------------------------------------------------
static void set_operands_values(Info* s);
static unsigned long long get_operand_value(Info* s, Operand* op);
static void exec_cmp(Info *s);
static void exec_add(Info *s);
static void exec_adc(Info *s);
static void exec_sub(Info *s);
static void exec_sbb(Info *s);
static void exec_inc(Info *s);
static void exec_dec(Info *s);
static void exec_and(Info *s); static void exec_or(Info *s);
static void exec_xor(Info *s);
static void exec_not(Info *s);
static void exec_neg(Info *s);
static void exec_xchg(Info *s);
static void exec_mul(Info *s);
static void exec_imul(Info *s);
static void exec_div(Info *s);
static void exec_idiv(Info *s);
static void exec_shl(Info *s);
static void exec_sal(Info *s);
static void exec_shr(Info *s);
static void exec_sar(Info *s);
static void exec_rol(Info *s);
static void exec_rcl(Info *s);
static void exec_ror(Info *s);
static void exec_rcr(Info *s);
static void set_result_info(Info *current_state);
static void commit_operand (Info* current_instruction_state, Operand* op, long long value);

// --------------------------------------------------------------------------------
// Lookup Table
// --------------------------------------------------------------------------------

// Instructions link struct
// Typedef for instruction handler function pointers
typedef void (*InstructionHandler)(Info*);

// Direct O(1) indexed lookup table
const InstructionHandler dispatch_table[OP_COUNT] = {
    // Data Path
    [OP_CMP]  = exec_cmp,
    // ALU
    [OP_ADD]  = exec_add,
    [OP_ADC]  = exec_adc,
    [OP_SUB]  = exec_sub,
    [OP_SBB]  = exec_sbb,
    [OP_INC]  = exec_inc,
    [OP_DEC]  = exec_dec,
    [OP_AND]  = exec_and,
    [OP_OR]   = exec_or,
    [OP_XOR]  = exec_xor,
    [OP_NOT]  = exec_not,
    [OP_NEG]  = exec_neg,
    [OP_XCHG] = exec_xchg,
    [OP_MUL]  = exec_mul,
    [OP_IMUL] = exec_imul,
    [OP_DIV]  = exec_div,
    [OP_IDIV] = exec_idiv,
    [OP_SHL]  = exec_shl,
    [OP_SAL]  = exec_sal,
    [OP_SHR]  = exec_shr,
    [OP_SAR]  = exec_sar,
    [OP_ROL]  = exec_rol,
    [OP_RCL]  = exec_rcl,
    [OP_ROR]  = exec_ror,
    [OP_RCR]  = exec_rcr

    // FPU
};


// --------------------------------------------------------------------------------
// Operand fetching, setting and cleaning functions
// --------------------------------------------------------------------------------

// -------------------
// Operand state init
// -------------------

Info* create_operand_state ()
{
    Info *op_state = (Info*)calloc(1, sizeof(Info));

    if (op_state == NULL)
    {
        printf("Operand table creation error. NULL pointer was achieved!\n");
        return NULL;
    }
    return op_state;
}

void free_operand_state (Info* s)
{
    if (s) free(s);
}

// ----------------------------
// Info setters
// ----------------------------

void set_operand_info (Info *current_instruction_state, char *operand, long long address, uint8_t size, uint8_t op_type, uint8_t is_high, uint8_t is_signed)
{
    if (operand != NULL && strcmp(operand, "op1") == 0 )
    {
        current_instruction_state->op1.address = address;
        current_instruction_state->op1.size = size;
        current_instruction_state->op1.op_type = op_type;
        current_instruction_state->op1.is_high = is_high;
        current_instruction_state->op1.is_signed = is_signed;
    } else
    {
        current_instruction_state->op2.address = address;
        current_instruction_state->op2.size = size;
        current_instruction_state->op2.op_type = op_type;
        current_instruction_state->op2.is_high = is_high;
        current_instruction_state->op2.is_signed = is_signed;
    }
}

void set_instruction (Info *current_instruction_state, uint8_t instruction)
{
    current_instruction_state->opcode = instruction;
}

void set_registers_ref (Info *current_state, CPURegs *r)
{
    current_state->registers = r;
}

void set_table_ref (Info *current_state, Table *t)
{
    current_state->table = t;
}

/**
 * @brief Commits the result of an operation to the appropriate destination (memory or register) based on the operand type.
 * * This function is called after an operation has been executed and the result is ready to be stored.
 * @param current_instruction_state Pointer to the Info structure holding all operand, instruction, registers and results info
 * @param op Pointer to the Operand structure that holds the destination information (address, type, size, etc.)
 * @param value The result value to be committed to the destination
 * @warning This function assumes that the operand type is either "memory" or "register". If the operand type is unknown, an error message will be printed.
 */
static void commit_operand (Info *current_instruction_state, Operand *op, long long value)
{
    if (op->op_type == OP_MEMORY) {
        write_mem(current_instruction_state->table, op->address, (uint8_t*)&value, op->size, 1);
    } else if (op->op_type == OP_REGISTER) {
        write_reg(current_instruction_state->registers, op->address, value, op->size, op->is_high);
    }
    else
    {
        printf("Error: Unknown operand type %d\n", (uint8_t)op->op_type);
    }
}

// -------------------
// Cleaners
// -------------------


void clean(Info *s) {
    memset(&s->op1, 0, sizeof(Operand));
    memset(&s->op2, 0, sizeof(Operand));
    memset(&s->result, 0, sizeof(Operand));
    s->opcode = OP_NULL;
    s->res_value = 0;
    s->op1_value = 0;
    s->op2_value = 0;
}

//--------------------------------
// Instruction execution functions
//--------------------------------

uint8_t dispatch(Info *s)
{
    Opcode op = s->opcode;

    // Failsafe verification. Python calls should always make sure this is not triggered
    if (op < 0 || op >= OP_COUNT || dispatch_table[op] == NULL)
    {
        printf("Error: invalid or unimplemented opcode (%d)\n", (int)op);
        clean(s);
        return 2;
    }

    set_result_info(s);
    set_operands_values(s);

    if (op == OP_DIV || op == OP_IDIV)
    {
        if (s->op1_value == 0) return 1;
    }

    uint8_t no_overwrite = op == OP_XCHG || op == OP_CMP || op == OP_MUL || op == OP_IMUL || op == OP_DIV || op == OP_IDIV;
    dispatch_table[op](s);
    if (!no_overwrite)
    {
        commit_operand(s, &s->result, s->res_value);
    }
    clean(s);
    return 0;
}

// --------------
// Result setter
// --------------

/**
 * @brief Sets the information about the result based on the operators info.
 * * Leaves the result value non altered to be set by the operation called.
 *
 * @param current_state Pointer to the Info structure holding all operand, instruction result and registers info
 */
static void set_result_info (Info *current_state)
{
    current_state->result.op_type = current_state->op1.op_type;
    current_state->result.size = current_state->op1.size;
    current_state->result.address = current_state->op1.address;
    current_state->result.is_high = current_state->op1.is_high;
    current_state->result.is_signed = current_state->op1.is_signed;
}


//----------------------
// Data Path Functions
//----------------------

/**
 * @brief Universal function to update the flags after an operation based on the result of the operation and the operands info.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @param result The result of the operation of the two operands, used to set the flags
 * @param count The shift/rotate count actually applied (0 for non-shift/rotate opcodes) - needed because CF/OF for these depend on the count itself, not just the before/after values, e.g. CF is "the last bit shifted out" which requires knowing how many bits were shifted.
 */
static void flags_update(Info *s, unsigned long long result, unsigned long long count)
{
    int bit_count = 8 * s->op1.size;
    int msb_shift = bit_count - 1;

    unsigned long long bits_mask = (bit_count >= 64) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1;
    unsigned long long res_msb = result & bits_mask;
    unsigned long long op1_masked = s->op1_value & bits_mask;

    // Arithmetic flags
    uint8_t zero = (uint8_t) (res_msb == 0);
    uint8_t sign = (uint8_t) ((res_msb >> msb_shift) & 1);

    // Parity Flag (Even parity of the lowest 8 bits)
    uint8_t pf = 1;
    uint8_t low_byte = res_msb & 0xFF;
    for (int i = 0; i < 8; i++) {
        pf ^= ((low_byte >> i) & 1);
    }

    // Fetch existing flags to preserve untouched state (IF, DF, TF, etc.)
    uint32_t rflags = read_rflags(s->registers);
    uint8_t carry = rflags & 1U; // Default to keeping old CF
    uint8_t overflow = (rflags >> 11) & 1U;

    switch (s->opcode) {
        case OP_ADD:
            carry = (res_msb < (s->op1_value & bits_mask));
            overflow = (uint8_t) (((s->op1_value ^ res_msb) & (s->op2_value ^ res_msb)) >> msb_shift & 1);
            break;
        case OP_ADC:
            carry = (res_msb < (s->op1_value & bits_mask)) || (res_msb == (s->op1_value & bits_mask) && (rflags & 1U));
            overflow = (uint8_t) (((s->op1_value ^ res_msb) & (s->op2_value ^ res_msb)) >> msb_shift & 1);
            break;
        case OP_SUB:
        case OP_CMP:
            carry = ((s->op1_value & bits_mask) < (s->op2_value & bits_mask));
            overflow = (uint8_t) (((s->op1_value ^ s->op2_value) & (s->op1_value ^ res_msb)) >> msb_shift & 1);
            break;
        case OP_SBB:
            carry = ((s->op1_value & bits_mask) < (s->op2_value & bits_mask)) || ((s->op1_value & bits_mask) == (s->op2_value & bits_mask) && (rflags & 1U));
            overflow = (uint8_t) (((s->op1_value ^ s->op2_value) & (s->op1_value ^ res_msb)) >> msb_shift & 1);
            break;
        case OP_INC:
            // CF is untouched. Overflow occurs if changing from 0x7F to 0x80
            overflow = (res_msb == (1ULL << msb_shift));
            break;
        case OP_DEC:
            // CF is untouched. Overflow occurs if changing from 0x80 to 0x7F
            overflow = ((s->op1_value & bits_mask) == (1ULL << msb_shift));
            break;
        case OP_NEG:
            carry = ((s->op1_value & bits_mask) != 0);
            overflow = ((s->op1_value & bits_mask) == (1ULL << msb_shift));
            break;
        case OP_AND:
        case OP_OR:
        case OP_XOR:
            carry = 0;
            overflow = 0;
            break;

        case OP_SHL:
        case OP_SAL:
            if (count >= 1 && count <= (unsigned long long)bit_count) {
                // CF = last bit shifted out = bit (bit_count - count) of the ORIGINAL value
                carry = (uint8_t) ((op1_masked >> (bit_count - count)) & 1ULL);
            }
            if (count == 1) {
                // OF = XOR of the two most-significant bits of the result
                overflow = (uint8_t) (((res_msb >> msb_shift) ^ (res_msb >> (msb_shift - 1))) & 1ULL);
            }
            break;
        case OP_SHR:
            if (count >= 1 && count <= (unsigned long long)bit_count) {
                // CF = last bit shifted out = bit (count - 1) of the ORIGINAL value
                carry = (uint8_t) ((op1_masked >> (count - 1)) & 1ULL);
            }
            if (count == 1) {
                // OF = original MSB (shr always clears the sign bit, so this reflects whether it changed)
                overflow = (uint8_t) ((op1_masked >> msb_shift) & 1ULL);
            }
            break;
        case OP_SAR:
            if (count >= 1 && count <= (unsigned long long)bit_count) {
                carry = (uint8_t) ((op1_masked >> (count - 1)) & 1ULL);
            }
            if (count == 1) {
                // Arithmetic shift right never changes the sign bit, so OF is always 0 for count == 1
                overflow = 0;
            }
            break;
        case OP_ROL:
            if (count >= 1) {
                // CF = LSB of the result (the bit that wrapped around to the front)
                carry = (uint8_t) (res_msb & 1ULL);
            }
            if (count == 1) {
                overflow = (uint8_t) (carry ^ ((res_msb >> msb_shift) & 1ULL));
            }
            break;
        case OP_ROR:
            if (count >= 1) {
                // CF = MSB of the result (the bit that wrapped around to the back)
                carry = (uint8_t) ((res_msb >> msb_shift) & 1ULL);
            }
            if (count == 1) {
                overflow = (uint8_t) (carry ^ ((res_msb >> (msb_shift - 1)) & 1ULL));
            }
            break;
        default:
            break;
    }

    // Clear CF(0), PF(2), ZF(6), SF(7), OF(11)
    rflags &= ~((1U << 0) | (1U << 2) | (1U << 6) | (1U << 7) | (1U << 11));
    // Apply new values
    rflags |= (carry << 0) | (pf << 2) | (zero << 6) | (sign << 7) | (overflow << 11);

    write_rflags(s->registers, rflags);
}

// -----------------
// Value fetching
// -----------------

/**
 * @brief Automatically fetches and stores the resolved values for both instruction operands.
 *
 * Evaluates s->op1 and s->op2, saving the extracted values directly into
 * s->op1_value and s->op2_value respectively.
 *
 * @param s   Pointer to the current instruction Info execution context.
 */
static void set_operands_values(Info *s)
{
    if (!s) return;

    // Automatically resolve and set both operand values inside the Info struct
    s->op1_value = get_operand_value(s, &s->op1);
    s->op2_value = get_operand_value(s, &s->op2);
}

/**
 * @brief Reads and returns the masked unsigned 64-bit value for a single operand.
 *
 * Determines whether to read from memory or registers based on op->op_type,
 * and masks off unused upper bits according to op->size.
 *
 * @param s   Pointer to the current instruction Info execution context.
 * @param op  Pointer to the Operand struct to evaluate.
 * @return    The resolved 64-bit unsigned integer value.
 */
static unsigned long long get_operand_value(Info *s, Operand *op)
{
    if (!s || !op) return 0ULL;

    unsigned long long value = 0ULL;

    switch (op->op_type)
    {
        case OP_MEMORY:
            // Fetch value from memory table
            read_mem(s->table, op->address, (uint8_t*)&value, op->size);
            break;

        case OP_REGISTER:
            // Fetch value from CPU registers
            switch (op->size)
            {
                case 1:
                    value = (unsigned long long) read_1b_reg(s->registers, op->address, op->is_high);
                    break;
                case 2:
                    value = (unsigned long long)  read_2b_reg(s->registers, op->address);
                    break;
                case 4:
                    value = (unsigned long long)  read_4b_reg(s->registers, op->address);
                    break;
                case 8:
                    value = (unsigned long long)  read_8b_reg(s->registers, op->address);
                    break;
                default:
                    value = 0;
            }
            break;

        default:
            // Immediate
            value = op->address;
    }

    // Zero-extend/mask value to guarantee upper bits above op->size are clean
    if (op->size < 8 && op->size > 0) {
        unsigned long long mask = (1ULL << (op->size * 8)) - 1ULL;
        value &= mask;
    }

    return value;
}


// ----------------------------
// Main Flux Control function
// ----------------------------

/**
 * @brief Executes the compare instruction, which is a subtraction that only updates the flags and does not store the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the subtraction is not stored, only the flags are updated based on the result of the operation
 */
static void exec_cmp(Info *s)
{
    // Need cmp syntax rules check
    unsigned long long result = (unsigned long long) s->op1_value - s->op2_value;
    // Sets flags based on the result
    flags_update(s, result, 0);
}

//----------------------
// ALU Functions
//----------------------

/**
 * @brief Executes non carried addition
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the addition is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_add(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value + s->op2_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes carried addition
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the addition is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_adc(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value + s->op2_value + read_carry_flag(s->registers);
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes non carried subtraction
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the subtraction is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_sub(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value - s->op2_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes carried subtraction
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the subtraction is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_sbb(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value - s->op2_value - read_carry_flag(s->registers);
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the increment instruction, which adds 1 to the operand and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the increment is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_inc(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value + 1;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the decrement instruction, which subtracts 1 from the operand and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the decrement is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_dec(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value - 1;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the bitwise AND instruction, which performs a bitwise AND operation between the two operands and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the AND operation is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_and(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value & s->op2_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the bitwise OR instruction, which performs a bitwise OR operation between the two operands and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the OR operation is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_or(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value | s->op2_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the bitwise XOR instruction, which performs a bitwise XOR operation between the two operands and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the XOR operation is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_xor(Info *s)
{
    unsigned long long result = (unsigned long long) s->op1_value ^ s->op2_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the bitwise NOT instruction, which performs a bitwise NOT operation on the operand and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the NOT operation is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_not(Info *s)
{
    unsigned long long result = (unsigned long long) ~s->op1_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the NEG instruction, which negates the operand and updates the flags based on the result.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the NEG operation is stored in the result field of the Info structure and the flags are updated based on the result of the operation
 */
static void exec_neg(Info *s)
{
    unsigned long long result = (unsigned long long) -s->op1_value;
    flags_update(s, result, 0);
    s->res_value = (long long) result;
}

/**
 * @brief Executes the XCHG instruction, which exchanges the values of the two operands without updating the flags.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning The result of the XCHG operation is stored in the op1 and op2 fields of the Info structure and the flags are not updated based on the result of the operation
 */
static void exec_xchg(Info *s)
{
    // Fetches each value
    long long val1 = s->op1_value;
    long long val2 = s->op2_value;
    // commits each value
    commit_operand(s, &s->op1, val2);
    commit_operand(s, &s->op2, val1);
}


/**
 * @brief Executes unsigned multiplication of AL/AX/EAX/RAX by the first operand.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning Results are written implicitly across RAX and RDX (or AX) based on operand size
 */
static void exec_mul(Info *s)
{
    uint8_t size = s->op1.size;
    unsigned long long rax_val = read_8b_reg(s->registers, 0); // RAX
    unsigned long long src = s->op1_value;
    uint8_t cf_of = 0;

    if (size == 1)
    {
        unsigned short res = (uint8_t)rax_val * (uint8_t)src;
        write_reg(s->registers, 0, res, 2, 0); // AX
        cf_of = ((res & 0xFF00) != 0);
    } else if (size == 2)
    {
        unsigned int res = (uint16_t)rax_val * (uint16_t)src;
        write_reg(s->registers, 0, res & 0xFFFF, 2, 0);         // AX
        write_reg(s->registers, 3, (res >> 16) & 0xFFFF, 2, 0); // DX
        cf_of = ((res & 0xFFFF0000) != 0);
    } else if (size == 4)
    {
        unsigned long long res = (uint32_t)rax_val * (uint64_t)(uint32_t)src;
        write_reg(s->registers, 0, res & 0xFFFFFFFFULL, 4, 0);          // EAX
        write_reg(s->registers, 3, (res >> 32) & 0xFFFFFFFFULL, 4, 0);  // EDX
        cf_of = ((res >> 32) != 0);
    } else
    { // 64-bit
        __uint128_t res = (__uint128_t)rax_val * (__uint128_t)src;
        write_reg(s->registers, 0, (unsigned long long)res, 8, 0);          // RAX
        write_reg(s->registers, 3, (unsigned long long)(res >> 64), 8, 0);  // RDX
        cf_of = ((res >> 64) != 0);
    }

    uint32_t rflags = read_rflags(s->registers);
    rflags &= ~((1U << 0) | (1U << 11));
    rflags |= (cf_of << 0) | (cf_of << 11);
    write_rflags(s->registers, rflags);
}

/**
 * @brief Executes signed multiplication in single-operand form.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning Return value is written implicitly to RAX/RDX
 */
static void exec_imul(Info *s)
{
    uint8_t size = s->op1.size;

    long long rax_val = (long long)read_8b_reg(s->registers, 0); // RAX
    long long src = (long long)s->op1_value;
    uint8_t cf_of = 0;

    if (size == 1) {
        short res = (int8_t)rax_val * (int8_t)src;
        write_reg(s->registers, 0, (unsigned short)res, 2, 0); // AX
        cf_of = (res != (int8_t)res);
    } else if (size == 2) {
        int res = (int16_t)rax_val * (int16_t)src;
        write_reg(s->registers, 0, (unsigned short)(res & 0xFFFF), 2, 0);         // AX
        write_reg(s->registers, 3, (unsigned short)((res >> 16) & 0xFFFF), 2, 0); // DX
        cf_of = (res != (int16_t)res);
    } else if (size == 4) {
        long long res = (int32_t)rax_val * (long long)(int32_t)src;
        write_reg(s->registers, 0, (unsigned int)(res & 0xFFFFFFFFLL), 4, 0);          // EAX
        write_reg(s->registers, 3, (unsigned int)((res >> 32) & 0xFFFFFFFFLL), 4, 0);  // EDX
        cf_of = (res != (int32_t)res);
    } else {
        __int128 res = (__int128)rax_val * (__int128)src;
        write_reg(s->registers, 0, (unsigned long long)res, 8, 0);          // RAX
        write_reg(s->registers, 3, (unsigned long long)(res >> 64), 8, 0);  // RDX
        cf_of = (res != (int64_t)res);
    }

    // Update CF and OF only
    uint32_t rflags = read_rflags(s->registers);
    rflags &= ~((1U << 0) | (1U << 11));
    rflags |= (cf_of << 0) | (cf_of << 11);
    write_rflags(s->registers, rflags);
}

/**
 * @brief Executes unsigned division of RDX : RAX (or AX) by the first operand.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning Quotient is stored in RAX (or AL) and remainder in RDX (or AH)
 */
static void exec_div(Info *s)
{
    uint8_t size = s->op1.size;
    unsigned long long divisor = s->op1_value;
    if (divisor == 0) return; // Prevent divide by zero

    if (size == 1)
    {
        unsigned short dividend = (unsigned short)read_2b_reg(s->registers, 0); // AX
        uint8_t quot = dividend / divisor;
        uint8_t rem = dividend % divisor;
        write_reg(s->registers, 0, quot, 1, 0); // AL
        write_reg(s->registers, 0, rem, 1, 1);  // AH
    } else if (size == 2)
    {
        unsigned int dividend = ((uint32_t)read_2b_reg(s->registers, 3) << 16) | read_2b_reg(s->registers, 0); // DX:AX
        uint16_t quot = dividend / divisor;
        uint16_t rem = dividend % divisor;
        write_reg(s->registers, 0, quot, 2, 0); // AX
        write_reg(s->registers, 3, rem, 2, 0);  // DX
    } else if (size == 4)
    {
        unsigned long long dividend = ((uint64_t)read_4b_reg(s->registers, 3) << 32) | read_4b_reg(s->registers, 0); // EDX:EAX
        uint32_t quot = dividend / divisor;
        uint32_t rem = dividend % divisor;
        write_reg(s->registers, 0, quot, 4, 0); // EAX
        write_reg(s->registers, 3, rem, 4, 0);  // EDX
    } else
    {
        __uint128_t dividend = ((__uint128_t)read_8b_reg(s->registers, 3) << 64) | read_8b_reg(s->registers, 0); // RDX:RAX
        uint64_t quot = dividend / divisor;
        uint64_t rem = dividend % divisor;
        write_reg(s->registers, 0, quot, 8, 0); // RAX
        write_reg(s->registers, 3, rem, 8, 0);  // RDX
    }
}

/**
 * @brief Executes signed division of RDX:RAX (or AX) by the first operand.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 * @warning Quotient is stored in RAX (or AL) and remainder in RDX (or AH)
 */
static void exec_idiv(Info *s)
{
    uint8_t size = s->op1.size;
    long long divisor = (long long)s->op1_value;
    if (size == 1) divisor = (int8_t)divisor;
    else if (size == 2) divisor = (int16_t)divisor;
    else if (size == 4) divisor = (int32_t)divisor;

    if (divisor == 0) return;

    if (size == 1) {
        short dividend = (short)read_2b_reg(s->registers, 0);
        int8_t quot = dividend / divisor;
        int8_t rem = dividend % divisor;
        write_reg(s->registers, 0, (uint8_t)quot, 1, 0);
        write_reg(s->registers, 0, (uint8_t)rem, 1, 1);
    } else if (size == 2) {
        int dividend = ((int)read_2b_reg(s->registers, 3) << 16) | read_2b_reg(s->registers, 0);
        int16_t quot = dividend / divisor;
        int16_t rem = dividend % divisor;
        write_reg(s->registers, 0, (uint16_t)quot, 2, 0);
        write_reg(s->registers, 3, (uint16_t)rem, 2, 0);
    } else if (size == 4) {
        long long dividend = ((long long)read_4b_reg(s->registers, 3) << 32) | read_4b_reg(s->registers, 0);
        int32_t quot = dividend / divisor;
        int32_t rem = dividend % divisor;
        write_reg(s->registers, 0, (uint32_t)quot, 4, 0);
        write_reg(s->registers, 3, (uint32_t)rem, 4, 0);
    } else {
        __int128 dividend = ((__int128)read_8b_reg(s->registers, 3) << 64) | read_8b_reg(s->registers, 0);
        int64_t quot = dividend / divisor;
        int64_t rem = dividend % divisor;
        write_reg(s->registers, 0, (uint64_t)quot, 8, 0);
        write_reg(s->registers, 3, (uint64_t)rem, 8, 0);
    }
}

/**
 * @brief Executes logical shift left on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_shl(Info *s)
{
    uint8_t size = s->op1.size;
    int bit_count = size * 8;
    unsigned long long mask = (size >= 8) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1ULL;
    unsigned long long count = s->op2_value & 0x3F;

    if (count == 0) return;

    unsigned long long result = (s->op1_value << count) & mask;
    flags_update(s, result, count);
    s->res_value = (long long)result;
}

/**
 * @brief Executes arithmetic shift left on the destination operand (identical to SHL).
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_sal(Info *s)
{
    exec_shl(s);
}

/**
 * @brief Executes logical shift right on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_shr(Info *s)
{
    uint8_t size = s->op1.size;
    int bit_count = size * 8;
    unsigned long long mask = (size >= 8) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1ULL;
    unsigned long long count = s->op2_value & 0x3F;

    if (count == 0) return;

    unsigned long long val = s->op1_value & mask;
    unsigned long long result = val >> count;
    flags_update(s, result, count);
    s->res_value = (long long)result;
}

/**
 * @brief Executes arithmetic shift right on the destination operand, preserving the sign bit.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_sar(Info *s)
{
    uint8_t size = s->op1.size;
    int bit_count = size * 8;
    unsigned long long mask = (size >= 8) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1ULL;
    unsigned long long count = s->op2_value & 0x3F;

    if (count == 0) return;

    long long sval = (long long)s->op1_value;
    if (size == 1) sval = (int8_t)sval;
    else if (size == 2) sval = (int16_t)sval;
    else if (size == 4) sval = (int32_t)sval;

    long long sres = sval >> count;
    unsigned long long result = ((unsigned long long)sres) & mask;
    flags_update(s, result, count);
    s->res_value = (long long)result;
}

/**
 * @brief Executes bitwise rotate left on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_rol(Info *s)
{
    uint8_t size = s->op1.size;
    int bit_count = size * 8;
    unsigned long long mask = (size >= 8) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1ULL;
    unsigned long long count = s->op2_value % bit_count;

    if (count == 0) return;

    unsigned long long val = s->op1_value & mask;
    unsigned long long result = ((val << count) | (val >> (bit_count - count))) & mask;
    flags_update(s, result, count);
    s->res_value = (long long)result;
}

/**
 * @brief Executes bitwise rotate right on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_ror(Info *s)
{
    uint8_t size = s->op1.size;
    int bit_count = size * 8;
    unsigned long long mask = (size >= 8) ? 0xFFFFFFFFFFFFFFFFULL : (1ULL << bit_count) - 1ULL;
    unsigned long long count = s->op2_value % bit_count;

    if (count == 0) return;

    unsigned long long val = s->op1_value & mask;
    unsigned long long result = ((val >> count) | (val << (bit_count - count))) & mask;
    flags_update(s, result, count);
    s->res_value = (long long)result;
}

/**
 * @brief Executes rotate left through the carry flag on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_rcl(Info *s)
{
    uint8_t size = s->op1.size;
    uint8_t bits = size * 8;
    uint64_t count = s->op2_value % (bits + 1);

    uint64_t val = s->op1_value;
    uint8_t cf = (read_rflags(s->registers) & 1U);

    for (uint64_t i = 0; i < count; i++) {
        uint8_t next_cf = (val >> (bits - 1)) & 1U;
        val = (val << 1) | cf;
        if (size < 8) {
            val &= (1ULL << bits) - 1ULL;
        }
        cf = next_cf;
    }

    s->res_value = val;

    // Update Carry Flag (bit 0)
    uint32_t rflags = read_rflags(s->registers);
    rflags = (rflags & ~1U) | (cf & 1U);
    write_rflags(s->registers, rflags);
}

/**
 * @brief Executes rotate right through the carry flag on the destination operand by the count in op2.
 *
 * @param s Pointer to the Info structure holding all operand, instruction and results info
 */
static void exec_rcr(Info *s)
{
    uint8_t size = s->op1.size;
    uint8_t bits = size * 8;
    uint64_t count = s->op2_value % (bits + 1);

    uint64_t val = s->op1_value;
    uint8_t cf = (read_rflags(s->registers) & 1U);

    for (uint64_t i = 0; i < count; i++) {
        uint8_t next_cf = val & 1U;
        val >>= 1;
        if (cf) {
            val |= (1ULL << (bits - 1));
        }
        cf = next_cf;
    }

    s->res_value = val;

    // Update Carry Flag (bit 0)
    uint32_t rflags = read_rflags(s->registers);
    rflags = (rflags & ~1U) | (cf & 1U);
    write_rflags(s->registers, rflags);
}
