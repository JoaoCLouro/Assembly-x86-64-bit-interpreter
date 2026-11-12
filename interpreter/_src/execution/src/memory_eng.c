#include "../include/memory_eng.h"
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// --- Constants ---
#define PAGE_SIZE 4096  // 4kb per page
#define MAX_PAGES 512 // 512 * 8 bytes per entry = 4kb tables

// --- Structures ---
struct Table {
    void *entries[MAX_PAGES];
};

// --- Prototypes ---
static int write_block (Table* table, uint64_t v_addr, uint8_t *data, uint8_t size, uint8_t create_page);
static int read_block (Table* table, uint64_t v_addr, uint8_t *buffer, uint8_t size);
static void free_recursive (Table* table, int level);


Table* table_init()
{
    Table* table = (Table*)calloc(1, sizeof(Table));
    if (!table) {
        fprintf (stderr, "Failed memory allocation for table initializer!\n Major error detected, exiting...\n");
        return NULL;
    }
    return table;
}


void free_table(Table* table)
{
    if (!table) return;
    free_recursive(table, 1);
}

static void free_recursive (Table* table, int level)
{
    if (!table) return;
    for (int i = 0; i < MAX_PAGES; i++)
    {
        if (table->entries[i])
        {
            if (level == 4) // Table to pages
            {
                free(table->entries[i]);
            }
            else
            {
                free_recursive((Table*)table->entries[i], level + 1);
            }
        }
    }
    // Free the current table after freeing all its entries
    free(table);
}

/**
 * @brief Main MMU function.
 * * Should initialize the Table structure if it's not yet created.
 * * Used to handle reads and writes as well as manage page creation if needed.
 *
 * @param CR3 Pointer to the Table structure representing the root of the paging structure
 * @param v_addr Virtual address given by the caller
 * @param create_page Flags for the operation type (0 - for read; 1 - for write)
 * @return Pointer to the physical byte, or NULL if unmapped and create_page is 0
 * @note create_page param affects directly Table structures creation permission.
 */
uint8_t *decompose_address (Table *CR3, uint64_t v_addr, uint8_t create_page)
{
    // The root table must be initialized by the caller via table_init()
    if (!CR3) return NULL;

    uint64_t pml4_idx  = (v_addr >> 39) & 0x1FF;
    uint64_t pdpt_idx  = (v_addr >> 30) & 0x1FF;
    uint64_t pd_idx    = (v_addr >> 21) & 0x1FF;
    uint64_t pt_idx    = (v_addr >> 12) & 0x1FF;
    uint64_t offset    = v_addr & 0xFFF;

    // 1. Level 4 (PML4) -> Level 3 (PDPT)
    if (!CR3->entries[pml4_idx]) {
        if (!create_page) return NULL;
        CR3->entries[pml4_idx] = calloc(1, sizeof(Table));
    }
    Table *pdpt = (Table*)CR3->entries[pml4_idx];

    // 2. Level 3 (PDPT) -> Level 2 (PD)
    if (!pdpt->entries[pdpt_idx]) {
        if (!create_page) return NULL;
        pdpt->entries[pdpt_idx] = calloc(1, sizeof(Table));
    }
    Table *pd = (Table*)pdpt->entries[pdpt_idx];

    // 3. Level 2 (PD) -> Level 1 (PT)
    if (!pd->entries[pd_idx]) {
        if (!create_page) return NULL;
        pd->entries[pd_idx] = calloc(1, sizeof(Table));
    }
    Table *pt = (Table*)pd->entries[pd_idx];

    // 4. Level 1 (PT) -> Actual 4KB Page
    if (!pt->entries[pt_idx]) {
        if (!create_page) return NULL;
        pt->entries[pt_idx] = calloc(1, PAGE_SIZE);
    }
    uint8_t *page_addr = (uint8_t*)pt->entries[pt_idx];

    return page_addr + offset;
}


int write_mem (Table* table, uint64_t v_addr, uint8_t *data, uint8_t size, uint8_t create_page)
{
    if (size == 1)
    {
        uint8_t *physical_addr = decompose_address(table, v_addr, create_page);
        if (!physical_addr) return 1;
        *physical_addr = *data;
        return 0;
    }
    return write_block(table, v_addr, data, size, create_page);
}

/**
 * @brief Writes a block of data to virtual memory.
 * * Handles page crossing by checking if the write stays within the 4KB boundary.
 *
 * @param table Pointer to the Table structure representing the root of the paging structure
 * @param v_addr Virtual address where the block should be written
 * @param data Pointer to the block of data to be written
 * @param size Size of the data block in bytes
 * @param create_page Flag to indicate if pages should be created if they don't exist
 * @return 0 on success, 1 if the write operation encounters an unmapped address (Segmentation Fault)
 * @warning This function assumes that the data block does not exceed the maximum size of the virtual address space.
 * @note The create_page flag affects directly the permission to create new pages in the memory.
 * If set to 0, the function will not create new pages and will return without writing if the target page does not exist.
 * If set to 1, the function will create new pages as needed to accommodate the write operation.
 */
static int write_block (Table* table, uint64_t v_addr, uint8_t *data, uint8_t size, uint8_t create_page)
{
    size_t written = 0;
    while (written < size)
    {
        uint64_t current_addr = v_addr + written;
        uint8_t *physical_addr = decompose_address(table, current_addr, create_page);
        // If the physical address could not be read because of a Segmentation Fault return without writing
        if (!physical_addr) return 1;

        uint64_t offset = current_addr & 0xFFF; // Offset within the page
        size_t space_in_page = PAGE_SIZE - offset; // Space left in the current page
        size_t to_write = (size - written < space_in_page) ? (size - written) : space_in_page; // Amount to write in the current page

        memcpy(physical_addr, data + written, to_write);
        written += to_write;
    }
    return 0;
}

int read_mem (Table* table, uint64_t v_addr, uint8_t *buffer, uint8_t size)
{
    if (size == 1)
    {
        uint8_t *physical_addr = decompose_address(table, v_addr, 0);
        // If the physical address could not be read because of a Segmentation Fault return 1
        if (!physical_addr) return 1;
        *buffer = *physical_addr;
        return 0;
    }
        return read_block(table, v_addr, buffer, size);
}

/**
 * @brief Reads a block of data from virtual memory.
 * * Handles page crossing by checking if the read stays within the 4KB boundary.
 *
 * @param table Pointer to the Table structure representing the root of the paging structure
 * @param v_addr Virtual address where the block should be read from
 * @param buffer Pointer to the buffer where the read data should be stored
 * @param size Size of the data block to be read in bytes
 * @return 0 on success, 1 if any part of the read operation encounters an unmapped address (Segmentation Fault)
 */
static int read_block (Table* table, uint64_t v_addr, uint8_t *buffer, uint8_t size)
{
    size_t read = 0;
    while (read < size)
    {
        uint64_t current_addr = v_addr + read;
        uint8_t *physical_addr = decompose_address(table, current_addr, 0);

        // If the physical address could not be read because of a Segmentation Fault return 1
        if (!physical_addr) return 1;

        uint64_t offset = current_addr & 0xFFF; // Offset within the page
        size_t space_in_page = PAGE_SIZE - offset; // Space left in the current page
        size_t to_read = (size - read < space_in_page) ? (size - read) : space_in_page; // Amount to read in the current page
        memcpy(buffer + read, physical_addr, to_read);
        read += to_read;
    }
    return 0;
}

#ifdef _WIN32
__declspec(dllexport) void* PyInit_libmmu(void) { return 0; }
#endif
