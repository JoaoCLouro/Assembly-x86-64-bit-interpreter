#ifndef MEMORY_ENG_H
#define MEMORY_ENG_H

#ifdef _WIN32
    #define EXPORT __declspec(dllexport)
#else
    #define EXPORT
#endif

#include <stdint.h>
#include <stddef.h>

// Compilation command: gcc -O3 -shared -o libmmu.so -fPIC memory_eng.c

// --- Structures ---
// Structure definition of the Table of pages of data
typedef struct Table Table;

// Prototypes
/**
 * @brief Initializes the pointer to the first level of the paging structure (PML4)
 * * Allocates memory for a Table structure and initializes it to zero.
 * * Returns a pointer to the initialized Table structure.
 * @return Pointer to the initialized Table structure, or NULL if memory allocation fails
 * @warning This function should be called before any memory access operations to ensure that the paging structure is properly initialized.
 * * If memory allocation fails, the function will return NULL, and subsequent memory access operations will not be possible until the issue is resolved.
 */
EXPORT Table* table_init();

/**
 * @brief Frees the memory allocated for the paging structure.
 * * Recursively frees all allocated pages and tables in the paging structure, starting from the given Table pointer.
 * * After freeing all allocated memory, the function also frees the Table structure itself.
 * @param table Pointer to the Table structure representing the root of the paging structure to be freed
 * @warning This function should be called when the paging structure is no longer needed to prevent memory leaks.
 * * If the provided pointer is NULL, the function will simply return without performing any operations.
 */
EXPORT void free_table(Table* table);

/**
 * @brief Writes bytes in memory.
 * * Uses the decompose method to get the real address and writes the value onto the new address.
 * * If the address returned is not NULL writes value on it, else returns without writing.
 * * Handles page crossing by checking if the write stays within the 4KB boundary.
 * * If the amount of bytes to write is grater than one uses the write_block function to handle the write operation.
 *
 * @param table Pointer to the Table structure representing the root of the paging structure
 * @param v_addr Virtual address given by the caller
 * @param data Pointer to the data to write
 * @param size Size of the data to write in bytes (1,2,4,8)
 * @param create_page Flag to indicate if pages should be created if they don't exist
 * @return 0 on success, 1 if the write operation encounters an unmapped address (Segmentation Fault)
 * @warning This function assumes that the data block does not exceed the maximum size of the virtual address space.
 * @note The create_page flag affects directly the permission to create new pages in the memory.
 * If set to 0, the function will not create new pages and will return without writing if the target page does not exist.
 * If set to 1, the function will create new pages as needed to accommodate the write operation.
 */
EXPORT int write_mem(Table* table, uint64_t v_addr, uint8_t *data, uint8_t size, uint8_t create_page);

/**
 * @brief Reads bytes from virtual memory.
 * * Uses the decompose method to get the real address and reads its value.
 * * If the address returned is NULL returns 1 to signal a Segmentation Fault.
 * * Handles page crossing by checking if the read stays within the 4KB boundary.
 * * If the amount of bytes to read is grater than one uses the read_block function to handle the read operation.
 *
 * @param table Pointer to the Table structure representing the root of the paging structure
 * @param v_addr Virtual address given by the caller
 * @param buffer Pointer to the memory block where the result is expected to be given if it is found
 * @param size Size of the data block to be read in bytes
 * @warning Uses 1 to signal a bad address to read and 0 to signal a success
 * @warning This function assumes that the data block does not exceed the maximum size of the virtual address space.
 */
EXPORT int read_mem(Table* table, uint64_t v_addr, uint8_t *result, uint8_t size);

#endif // MEMORY_ENG_H
