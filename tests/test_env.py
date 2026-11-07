def main():
    print("\n ------------------ Initializing tests ------------------ \n")

    print("\n   --- Running byte conversion representation test ---   \n")
    test_byte_Obj_parsing()

    print("Finished")


def test_byte_Obj_parsing():
    """
    Tests how each value is converted to bytes objects
    """
    data: list[str] = ["joao", "ola", "adeus"]
    int_data: list[int] = [100, 254, 2, 112, 64]

    print("Testing String conversion: ")
    for word in reversed(data):
        for char in reversed(word):
            byte_char: bytes = char.encode()
            print(byte_char.hex(" "))

    print("Testing int conversion: ")
    for value in reversed(int_data):
        byte_value: bytes = value.to_bytes(byteorder="little")
        print(byte_value.hex(" "))


if __name__ == "__main__":
    main()
