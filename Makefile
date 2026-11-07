CC = gcc
CFLAGS = -O3 -fPIC -I./interpreter/_src/execution/include
LDFLAGS = -shared

# == Directories ====

SRC_DIR = interpreter/_src/execution/src
INC_DIR = interpreter/_src/execution/include
LIB_DIR = interpreter/_src/lib
BUILD_DIR = build

TEST_DIR = tests/execution_tests
TEST_BIN_DIR = tests/bin

# == Targets & Libraries ========

# 1. Define the exact shared libraries you want to build
LIB_OPS  = $(LIB_DIR)/liboperations.so
LIB_MMU  = $(LIB_DIR)/libmmu.so
LIB_REG  = $(LIB_DIR)/libreg.so
LIB_SYS  = $(LIB_DIR)/libscl.so

# FIX 1: Added $(LIB_SYS) here so the library is built as a dependency
SHARED_LIBS = $(LIB_OPS) $(LIB_MMU) $(LIB_REG) $(LIB_SYS)

# 2. Define the linker flags for the tests
# FIX 2: Added -lrscl here so the tests link against librscl.so
TEST_LIBS = -loperations -lmmu -lreg -lscl

# 3. Test files and binaries
TEST_SRCS = $(wildcard $(TEST_DIR)/*.c)
TEST_BINS = $(TEST_SRCS:$(TEST_DIR)/%.c=$(TEST_BIN_DIR)/%)

# == Rules ==========

.PHONY: all directories clean test

all: directories $(SHARED_LIBS) $(TEST_BINS)

directories:
	@mkdir -p $(LIB_DIR)
	@mkdir -p $(BUILD_DIR)
	@mkdir -p $(TEST_BIN_DIR)

# Rule to compile execution .c files to .o files automatically
$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c
	$(CC) $(CFLAGS) -c $< -o $@

# liboperations.so calls into functions that are only declared in headers
# but actually DEFINED in registers.c/libreg.so and memory_eng.c/libmmu.so
# (e.g. read_carry_flag from registers, and presumably memory read/write
# helpers from mmu) - so liboperations.so must link against BOTH at build
# time, and needs both built first (added as prerequisites) plus an rpath
# so the loader can find them next to it at runtime.
$(LIB_OPS): $(BUILD_DIR)/operations.o $(LIB_REG) $(LIB_MMU)
	$(CC) $(LDFLAGS) -o $@ $< -L$(LIB_DIR) -lreg -lmmu -Wl,-rpath,'$$ORIGIN'

$(LIB_MMU): $(BUILD_DIR)/memory_eng.o
	$(CC) $(LDFLAGS) -o $@ $<

$(LIB_REG): $(BUILD_DIR)/registers.o
	$(CC) $(LDFLAGS) -o $@ $<

$(LIB_SYS): $(BUILD_DIR)/syscall.o
	$(CC) $(LDFLAGS) -o $@ $<

# Rule to compile AND link test executables against the custom libraries
$(TEST_BIN_DIR)/%: $(TEST_DIR)/%.c $(SHARED_LIBS)
	$(CC) -O3 -I./interpreter/_src/execution/include $< -o $@ -L$(LIB_DIR) $(TEST_LIBS) -Wl,-rpath=$$(pwd)/$(LIB_DIR)

test: all
	@echo "Running tests..."
	@for test in $(TEST_BINS); do \
		echo "=> Executing $$test"; \
		./$$test || exit 1; \
	done

clean:
	rm -rf $(BUILD_DIR)/* $(LIB_DIR)/*
	@echo "Cleaned execution build and lib folders."
	rm -rf $(TEST_BIN_DIR)/*
	@echo "Cleaned test bin folders."
