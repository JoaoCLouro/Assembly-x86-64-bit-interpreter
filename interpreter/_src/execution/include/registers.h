#ifndef REGISTERS_H
#define REGISTERS_H

#ifdef _WIN32
    #define EXPORT __declspec(dllexport)
#else
    #define EXPORT
#endif

#include <stdint.h>

// Compilation command: gcc -O3 -shared -o libreg.so -fPIC registers.c

// ----------------------------------------------------------------------------

// General register type
typedef struct CPURegs CPURegs;

// ----------------------------------------------------------------------------

// Prototypes

// Register getters
/**
 * @brief Returns the address to the structure in memory that holds the current state of the registers in the execution.
 *
 * @return Address value of the structure defined in this file in memory
 */
EXPORT CPURegs* CPURegs_create ();
// Register  freeing
/**
 * @brief Frees the memory allocated for the CPURegs structure.
 *
 * @param c Pointer to the CPURegs structure to free
 */
EXPORT void CPURegs_free(CPURegs *c);

//sign setters
/**
 * @brief Sets the sign flag for a register.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register in as defined by the order of initialization in the CPURegs struct
 * @param is_signed 0 = unsigned , 1 = signed
 */
EXPORT void set_reg_sign (CPURegs *current_state, uint8_t reg_id, uint8_t is_signed);

/**
 * @brief Returns the value of the sign status of a given register. If the given index is incorrect returns -1.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register in as defined by the order of initialization in the CPURegs struct
 */
EXPORT int is_signed (CPURegs *current_state, uint8_t reg_id);

// writing
/**
 * @brief Hardware Dispatcher for register values.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register in as defined by the order of initialization in the CPURegs struct
 * @param value  The 64-bit value to write
 * @param size   Number of bytes to write (1, 2, 4, 8)
 * @param is_high: Boolean (1 if accessing AH/BH/CH/DH)
 */
EXPORT void write_reg (CPURegs *current_state, uint8_t reg_id, int64_t value, uint8_t size, uint8_t is_high);
// Read
/**
 * @brief Hardware Dispatcher fo 8 byte registers.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register as defined by the order of initialization in the CPURegs structure
 * @return The 64-bit value of the given register
 * @warning The index must be valid for a correct result
 */
EXPORT uint64_t read_8b_reg (CPURegs *current_state, uint8_t reg_id);
/**
 * @brief Hardware Dispatcher fo 4 byte registers.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register as defined by the order of initialization in the CPURegs structure
 * @return The 32-bit value of the given register
 * @warning The index must be valid for a correct result
 */
EXPORT uint32_t read_4b_reg (CPURegs *current_state, uint8_t reg_id);

/**
 * @brief Hardware Dispatcher fo 2 byte registers.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register as defined by the order of initialization in the CPURegs structure
 * @return The 16-bit value of the given register
 * @warning The index must be valid for a correct result
 */
EXPORT uint16_t read_2b_reg (CPURegs *current_state, uint8_t reg_id);

/**
 * @brief Hardware Dispatcher fo 1 byte registers.
 *
 * @param current_state Holder of the register structures
 * @param reg_id Index of the register as defined by the order of initialization in the CPURegs structure
 * @param is_high Boolean (1 if accessing AH/BH/CH/DH)
 * @return The 8-bit value of the given register
 * @warning The index must be valid for a correct result
 */
EXPORT uint8_t read_1b_reg (CPURegs *current_state, uint8_t reg_id, uint8_t is_high);

// Flags
/**
 * @brief Returns the value of the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return The 32-bit value of the rflags register
 */
EXPORT uint32_t read_rflags (CPURegs *current_state);

/**
 * @brief Returns the value of the trap flag (TF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the trap flag is set, 0 otherwise
 */
EXPORT uint8_t read_trap_flag (CPURegs *current_state);

/**
 * @brief Returns the value of the carry flag (CF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the carry flag is set, 0 otherwise
 */
EXPORT uint8_t read_carry_flag (CPURegs *current_state);

/**
 * @brief Returns the value of the zero flag (ZF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the zero flag is set, 0 otherwise
 */
EXPORT uint8_t read_zero_flag (CPURegs *current_state);

/**
 * @brief Returns the value of the sign flag (SF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the sign flag is set, 0 otherwise
 */
EXPORT uint8_t read_sign_flag (CPURegs *current_state);

/**
 * @brief Returns the value of the overflow flag (OF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the overflow flag is set, 0 otherwise
 */
EXPORT uint8_t read_overflow_flag (CPURegs *current_state);

/**
 * @brief Returns the value of the parity flag (PF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @return 1 if the parity flag is set, 0 otherwise
 */
EXPORT uint8_t read_parity_flag (CPURegs* current_state);

/**
 * @brief Writes a value to the rflags register.
 *
 * @param current_state Holder of the register structures
 * @param value The 32-bit value to write to the rflags register
 */
EXPORT void write_rflags (CPURegs *current_state, uint32_t value);

/**
 * @brief Exchanges the value of a given flag based on its bit number on the flags register.
 *
 * @param current_state Holder of the register structures
 * @param flag_id The bit number of the flag to exchange
 * @warning flag_id must be a valid id else it won't make any alterations to rflags
 */
EXPORT void exch_rflag (CPURegs *current_state, uint8_t flag_id);

/**
 * @brief Toggles the value of the trap flag (TF) in the rflags register.
 *
 * @param current_state Holder of the register structures
 * @warning This function toggles the value of the trap flag, so if it is currently set it will be cleared, and if it is currently cleared it will be set
 */
EXPORT void set_trap_flag (CPURegs *current_state);

#endif // REGISTERS_H
