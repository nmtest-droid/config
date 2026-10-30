#!/usr/bin/env python3
"""A small UNIX-like command shell emulator (Stage 2: configuration)."""

from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]


def parse_command(line: str) -> ParsedCommand | None:
    """Split a command line on whitespace; empty input returns None."""
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
    """Build a UNIX-style prompt from the host OS information."""
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
    """Configurable command loop with optional startup-script execution."""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        vfs_path: Path | str | None = None,
        prompt: str | None = None,
    ) -> None:
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.running = True
        self.vfs_path = Path(vfs_path or Path.cwd()).expanduser().resolve()
        self.prompt = prompt if prompt is not None else make_prompt()

    def _error(self, message: str) -> None:
        print(f"shell: {message}", file=self.stderr)

    def execute(self, command: ParsedCommand | None) -> bool:
        """Execute a command; return False when it fails, True otherwise."""
        if command is None:
            return True
        name, args = command.name, command.args
        if name == "ls":
            print("ls" + (" " + " ".join(args) if args else ""), file=self.stdout)
            return True
        if name == "cd":
            if len(args) > 1:
                self._error("cd: too many arguments (expected 0 or 1)")
                return False
            print("cd" + (" " + " ".join(args) if args else ""), file=self.stdout)
            return True
        if name == "exit":
            if args:
                self._error("exit: too many arguments (expected none)")
                return False
            self.running = False
            return True
        self._error(f"{name}: command not found")
        return False

    def run_script(self, script_path: Path | str) -> None:
        """Run script commands in order, displaying prompt and entered line.

        Failed commands are reported with their source line and skipped.
        """
        path = Path(script_path).expanduser().resolve()
        try:
            with path.open("r", encoding="utf-8") as script:
                for line_number, raw_line in enumerate(script, start=1):
                    if not self.running:
                        break
                    command_text = raw_line.rstrip("\r\n")
                    if not command_text.strip() or command_text.lstrip().startswith("#"):
                        continue
                    self.stdout.write(self.prompt + command_text + "\n")
                    self.stdout.flush()
                    succeeded = self.execute(parse_command(command_text))
                    if not succeeded:
                        self._error(f"startup script {path}:{line_number}: command failed; line skipped")
        except OSError as exc:
            self._error(f"cannot execute startup script '{path}': {exc}")

    def run(self) -> int:
        while self.running:
            try:
                self.stdout.write(self.prompt)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configurable UNIX-like shell emulator (stage 2)."
    )
    parser.add_argument(
        "--vfs", "--vfs-path", dest="vfs_path", default=".", metavar="PATH",
        help="physical directory used as the virtual filesystem root (default: current directory)",
    )
    parser.add_argument(
        "--prompt", default=None, metavar="TEXT",
        help="custom REPL prompt (default: username@hostname:cwd$)",
    )
    parser.add_argument(
        "--startup-script", "--script", dest="startup_script", default=None,
        metavar="PATH", help="path to a startup script containing emulator commands",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vfs_path = Path(args.vfs_path).expanduser().resolve()
    if not vfs_path.exists() or not vfs_path.is_dir():
        print(f"shell: VFS path is not an existing directory: {vfs_path}", file=sys.stderr)
        return 2

    startup_script: Path | None = None
    if args.startup_script is not None:
        startup_script = Path(args.startup_script).expanduser().resolve()
        if not startup_script.exists() or not startup_script.is_file():
            print(f"shell: startup script is not a readable file: {startup_script}", file=sys.stderr)
            return 2
        if not os.access(startup_script, os.R_OK):
            print(f"shell: startup script is not readable: {startup_script}", file=sys.stderr)
            return 2

    prompt = args.prompt if args.prompt is not None else make_prompt()
    print("[configuration]", file=sys.stderr)
    print(f"VFS path: {vfs_path}", file=sys.stderr)
    print(f"Prompt: {prompt!r}", file=sys.stderr)
    print(f"Startup script: {startup_script if startup_script else '(not set)'}", file=sys.stderr)

    shell = Shell(vfs_path=vfs_path, prompt=prompt)
    if startup_script is not None:
        shell.run_script(startup_script)
    return shell.run() if shell.running else 0


if __name__ == "__main__":
    raise SystemExit(main())
