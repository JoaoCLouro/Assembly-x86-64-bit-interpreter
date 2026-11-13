import json
import sys

from interpreter import Interpreter


def main() -> None:
    asm_path = sys.argv[1]

    interp = Interpreter(file_name=asm_path, args=["_"])

    exit_code = interp.run()
    state = interp.get_state("all", 10)

    sys.stdout.write("__EXIT_CODE__" + str(int(exit_code)) + "\n")
    sys.stdout.write("__STATE__" + json.dumps(state) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
