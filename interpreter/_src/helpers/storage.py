#!/usr/bin/env python3

import json
import os
import sys

from ...exit_codes import ExitCode

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
SRC_ROOT = os.path.join(PROJECT_ROOT, "interpreter", "_src")
CACHE_DIR = os.path.join(SRC_ROOT, "program_cache")

LIBREG_PATH = os.path.join(SRC_ROOT, "lib", "libreg.so")
LIBMMU_PATH = os.path.join(SRC_ROOT, "lib", "libmmu.so")


class Storage:
    """
    Utility class for file storage operations.
    Takes care of all creation, reading and writing operations to files.
    All file creations are done in the project directory and to a JSON file format.
    Contains static methods only.

    Author: João Carilho Louro
    """

    @staticmethod
    def _get_path(file_name: str, use_cache: bool = True) -> str:
        """
        Internal helper to resolve file paths and ensure directories exist.

        :param file_name: The name of the file with extension.
        :type file_name: str
        :param use_cache: Whether to use the cache directory or project root.
        :type use_cache: bool
        :return str: The resolved file path.
        """
        base_dir = CACHE_DIR if use_cache else PROJECT_ROOT
        if use_cache and not os.path.exists(base_dir):
            os.makedirs(base_dir)
        return os.path.join(base_dir, file_name)

    @staticmethod
    def _validate_json_extension(file_name: str) -> None:
        """
        Internal helper to validate file extensions.

        :param file_name: The name of the file with extension.
        :type file_name: str
        :raises ValueError: If the file does not have a .json extension.
        """
        if not file_name.endswith(".json"):
            raise ValueError(f"File '{file_name}' must have a .json extension.")

    @staticmethod
    def clean_cache() -> None:
        """
        Cleans the cache directory by removing all files in it, except valid_instructions.json.
        """
        if not os.path.exists(CACHE_DIR):
            return

        for name in os.listdir(CACHE_DIR):
            file_path = os.path.join(CACHE_DIR, name)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except OSError as e:
                print(f"Error while deleting file {file_path}: {e}")

    @staticmethod
    def get_raw_file_name(file_name: str) -> str:
        """
        Returns the raw file name with the extension.

        :param file_name: The name of the file with extension.
        :type file_name: str
        :return str: The raw file name with the extension.
        """
        return os.path.basename(file_name)

    @staticmethod
    def convert_to_json(file_name: str) -> str:
        """
        Convert any given file to a JSON file, stripping out comments and layout spacing.

        :param file_name: The name of the file with extension.
        :type file_name: str
        :return str: The name of the new JSON file.
        """
        src_path = Storage._get_path(file_name, use_cache=False)
        if not os.path.exists(src_path):
            print(
                f"Something went wrong! File {file_name} couldn't be opened.\n     Exiting program...\n"
            )
            sys.exit(ExitCode.UNOPENABLE_FILE)

        raw_text = Storage.load_file(file_name).splitlines()
        clean_lines: list[str] = []

        for line in raw_text:
            clean_line = line.split(";")[0].strip()
            if clean_line:  # Only preserve real instructions and labels
                clean_lines.append(clean_line)

        raw_file_name = os.path.splitext(Storage.get_raw_file_name(file_name))[0]
        new_file_name = f"{raw_file_name}.json"

        Storage.save_file(new_file_name, clean_lines)
        return new_file_name

    @staticmethod
    def save_file(file_name: str, data: list[str] | list[list[str]]) -> None:
        """
        Save data to a JSON file in the project cache directory.

        :param file_name: The full name of the file.
        :type file_name: str
        :param data: The data to save (must be serializable to JSON).
        :type data: list
        :raises ValueError: if file_name does not end with '.json'
        """
        Storage._validate_json_extension(file_name)
        file_path = Storage._get_path(file_name)

        with open(file_path, "w") as file:
            json.dump(data, file, indent=4)

    @staticmethod
    def save_file_dictionary(
        file_name: str, data: dict[str, str | dict[str, int]]
    ) -> None:
        """
        Save dictionaries to a JSON file in the project cache directory if it doesn't exist.

        :param file_name: The full name of a new file.
        :type file_name: str
        :param data: The data to save (must be serializable to JSON).
        :type data: dict
        :raises ValueError: if file_name does not end with '.json'
        """
        Storage._validate_json_extension(file_name)
        file_path = Storage._get_path(file_name)

        if not os.path.isfile(file_path):
            with open(file_path, "w") as file:
                json.dump(data, file, indent=4)

    @staticmethod
    def load_file(file_name: str) -> str:
        """
        Load a file from the project root directory and return its contents as a single string.

        :param file_name: Name of the file to load from the project root.
        :type file_name: str
        :return str: The file's contents string.
        """
        file_path = Storage._get_path(file_name, use_cache=False)
        try:
            with open(file_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            print(
                f"Something went wrong! File {file_name} couldn't be opened.\n     Exiting program...\n"
            )
            sys.exit(ExitCode.UNOPENABLE_FILE)

    @staticmethod
    def load_file_lines(file_name: str) -> list[str]:
        """
        Returns the contents of a cached JSON file as a list of lines.

        :param file_name: The name of the file with extension.
        :type file_name: str
        :return list[str]: A list of strings parsed from JSON.
        """
        file_path = Storage._get_path(file_name)
        with open(file_path, "r") as f:
            return json.load(f)
