#!/usr/bin/env python3

from __future__ import annotations

import getpass
import os
import socket
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]


def parse_command(line: str) -> ParsedCommand | None:

    parts = line.strip().split()
    if not parts:
        return None
    return ParsedCommand(name=parts[0], args=parts[1:])


def make_prompt(
    username: str | None = None,
    hostname: str | None = None,
    cwd: str | None = None,
    home: str | None = None,
) -> str:
    username = username if username is not None else getpass.getuser()
    hostname = hostname if hostname is not None else socket.gethostname()
    cwd = cwd if cwd is not None else os.getcwd()
    home = home if home is not None else os.path.expanduser("~")

    try:
        display_path = os.path.relpath(cwd, home)
        if display_path == ".":
            display_path = "~"
        elif display_path == ".." or display_path.startswith(".." + os.sep):
            display_path = cwd
        else:
            display_path = os.path.join("~", display_path)
    except ValueError:
        display_path = cwd

    return f"{username}@{hostname}:{display_path}$ "


class Shell:

    def __init__(
        self,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
    ) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.running = True

    def _error(self, message: str) -> None:
        print(f"shell: {message}", file=self.stderr)

    def execute(self, command: ParsedCommand | None) -> None:
        if command is None:
            return

        name, args = command.name, command.args

        if name == "ls":
            print("ls" + (" " + " ".join(args) if args else ""), file=self.stdout)
            return

        if name == "cd":
            if len(args) > 1:
                self._error("cd: too many arguments (expected 0 or 1)")
                return
            print("cd" + (" " + " ".join(args) if args else ""), file=self.stdout)
            return

        if name == "exit":
            if args:
                self._error("exit: too many arguments (expected none)")
                return
            self.running = False
            return

        self._error(f"{name}: command not found")

    def run(self) -> int:
        while self.running:
            try:
                self.stdout.write(make_prompt())
                self.stdout.flush()
                line = self.stdin.readline()
                if line == "":
                    self.stdout.write("\n")
                    break
                self.execute(parse_command(line))
            except KeyboardInterrupt:
                self.stdout.write("\n")
                self.stdout.flush()
            except BrokenPipeError:
                return 1
        return 0


def main() -> int:
    try:
        return Shell().run()
    except OSError as exc:
        print(f"shell: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
