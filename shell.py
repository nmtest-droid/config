#!/usr/bin/env python3
"""UNIX-like shell emulator with an in-memory CSV-backed VFS."""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import getpass
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TextIO


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]


def parse_command(line: str) -> ParsedCommand | None:
    parts = line.strip().split()
    return ParsedCommand(parts[0], parts[1:]) if parts else None


def make_prompt(username: str | None = None, hostname: str | None = None,
                cwd: str | None = None, home: str | None = None) -> str:
    username = username if username is not None else getpass.getuser()
    hostname = hostname if hostname is not None else socket.gethostname()
    cwd = cwd if cwd is not None else os.getcwd()
    home = home if home is not None else os.path.expanduser("~")
    try:
        rel = os.path.relpath(cwd, home)
        shown = "~" if rel == "." else (cwd if rel == ".." or rel.startswith(".." + os.sep) else os.path.join("~", rel))
    except ValueError:
        shown = cwd
    return f"{username}@{hostname}:{shown}$ "


@dataclass
class VFSNode:
    name: str
    kind: str
    data: bytes = b""
    children: dict[str, "VFSNode"] = field(default_factory=dict)


class VFSLoadError(ValueError):
    pass


class VirtualFileSystem:
    """Read-only CSV-backed tree; all entries and file bytes live in memory."""
    REQUIRED_COLUMNS = {"path", "type", "content_base64"}

    def __init__(self, csv_path: Path | str):
        self.csv_path = Path(csv_path).expanduser().resolve()
        self.root = VFSNode("/", "dir")
        self.cwd = "/"
        self._load()

    def _load(self) -> None:
        if not self.csv_path.exists():
            raise VFSLoadError(f"VFS CSV file not found: {self.csv_path}")
        if not self.csv_path.is_file():
            raise VFSLoadError(f"VFS source is not a file: {self.csv_path}")
        try:
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames is None or not self.REQUIRED_COLUMNS.issubset(reader.fieldnames):
                    raise VFSLoadError("invalid CSV header; expected: path,type,content_base64")
                rows = list(reader)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise VFSLoadError(f"cannot read VFS CSV: {exc}") from exc

        # Create directories first so CSV row order does not constrain nesting.
        parsed: list[tuple[str, str, bytes, int]] = []
        seen: set[str] = set()
        for line_no, row in enumerate(rows, start=2):
            raw_path = (row.get("path") or "").strip()
            kind = (row.get("type") or "").strip().lower()
            encoded = row.get("content_base64") or ""
            p = PurePosixPath(raw_path)
            if not raw_path or p.is_absolute() or any(part in ("", ".", "..") for part in p.parts):
                raise VFSLoadError(f"line {line_no}: invalid relative path '{raw_path}'")
            normalized = p.as_posix()
            if normalized in seen:
                raise VFSLoadError(f"line {line_no}: duplicate path '{normalized}'")
            seen.add(normalized)
            if kind not in ("dir", "file"):
                raise VFSLoadError(f"line {line_no}: type must be 'dir' or 'file'")
            if kind == "dir":
                if encoded.strip():
                    raise VFSLoadError(f"line {line_no}: directory content must be empty")
                data = b""
            else:
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise VFSLoadError(f"line {line_no}: invalid base64 content") from exc
            parsed.append((normalized, kind, data, line_no))

        # Parent directories must be explicitly present in the CSV.
        for normalized, kind, data, line_no in sorted(parsed, key=lambda item: (item[0].count("/"), item[0])):
            parts = normalized.split("/")
            parent = self.root
            for part in parts[:-1]:
                if part not in parent.children or parent.children[part].kind != "dir":
                    raise VFSLoadError(f"line {line_no}: parent directory for '{normalized}' is missing")
                parent = parent.children[part]
            name = parts[-1]
            if name in parent.children:
                raise VFSLoadError(f"line {line_no}: duplicate or conflicting path '{normalized}'")
            parent.children[name] = VFSNode(name, kind, data)

    @staticmethod
    def _parts(path: str, cwd: str) -> list[str]:
        parts = [] if path.startswith("/") else [p for p in cwd.split("/") if p]
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return parts

    def resolve(self, path: str = ".") -> tuple[VFSNode | None, str]:
        parts = self._parts(path, self.cwd)
        node = self.root
        for part in parts:
            if node.kind != "dir" or part not in node.children:
                return None, "/" + "/".join(parts)
            node = node.children[part]
        return node, "/" + "/".join(parts)

    def list_dir(self, path: str = ".") -> list[str]:
        node, resolved = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"{path}: no such file or directory")
        if node.kind != "dir":
            raise NotADirectoryError(f"{path}: not a directory")
        return sorted(node.children)

    def change_dir(self, path: str = "/") -> None:
        node, resolved = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"{path}: no such file or directory")
        if node.kind != "dir":
            raise NotADirectoryError(f"{path}: not a directory")
        self.cwd = resolved

    def read_file(self, path: str) -> bytes:
        node, _ = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"{path}: no such file")
        if node.kind != "file":
            raise IsADirectoryError(f"{path}: is a directory")
        return node.data


class Shell:
    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None,
                 stderr: TextIO | None = None, *, vfs: VirtualFileSystem,
                 prompt: str | None = None):
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.running = True
        self.vfs = vfs
        self.prompt = prompt if prompt is not None else make_prompt()

    def _error(self, message: str) -> None:
        print(f"shell: {message}", file=self.stderr)

    def execute(self, command: ParsedCommand | None) -> bool:
        if command is None:
            return True
        name, args = command.name, command.args
        if name == "ls":
            if len(args) > 1:
                self._error("ls: too many arguments (expected 0 or 1)")
                return False
            try:
                entries = self.vfs.list_dir(args[0] if args else ".")
            except (FileNotFoundError, NotADirectoryError) as exc:
                self._error(f"ls: {exc}")
                return False
            print("  ".join(entries), file=self.stdout)
            return True
        if name == "cd":
            if len(args) > 1:
                self._error("cd: too many arguments (expected 0 or 1)")
                return False
            try:
                self.vfs.change_dir(args[0] if args else "/")
            except (FileNotFoundError, NotADirectoryError) as exc:
                self._error(f"cd: {exc}")
                return False
            return True
        if name == "pwd":
            if args:
                self._error("pwd: too many arguments (expected none)")
                return False
            print(self.vfs.cwd, file=self.stdout)
            return True
        if name == "cat":
            if len(args) != 1:
                self._error("cat: expected exactly one file argument")
                return False
            try:
                data = self.vfs.read_file(args[0])
                print(data.decode("utf-8"), end="", file=self.stdout)
                if not data.endswith(b"\n"):
                    print(file=self.stdout)
            except (FileNotFoundError, IsADirectoryError) as exc:
                self._error(f"cat: {exc}")
                return False
            except UnicodeDecodeError:
                self._error(f"cat: {args[0]}: binary file (stored safely as base64 in CSV)")
                return False
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
        path = Path(script_path).expanduser().resolve()
        try:
            with path.open("r", encoding="utf-8") as script:
                for line_number, raw_line in enumerate(script, 1):
                    if not self.running:
                        break
                    text = raw_line.rstrip("\r\n")
                    if not text.strip() or text.lstrip().startswith("#"):
                        continue
                    self.stdout.write(self.prompt + text + "\n")
                    self.stdout.flush()
                    if not self.execute(parse_command(text)):
                        self._error(f"startup script {path}:{line_number}: command failed; line skipped")
        except OSError as exc:
            self._error(f"cannot execute startup script '{path}': {exc}")

    def run(self) -> int:
        while self.running:
            self.stdout.write(self.prompt)
            self.stdout.flush()
            line = self.stdin.readline()
            if line == "":
                self.stdout.write("\n")
                break
            self.execute(parse_command(line))
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UNIX-like shell emulator with CSV-backed in-memory VFS")
    parser.add_argument("-v", "--vfs", "--vfs-path", dest="vfs_path", default="examples/vfs/multi.csv",
                        metavar="CSV", help="CSV file describing VFS (default: examples/vfs/multi.csv)")
    parser.add_argument("-p", "--prompt", default=None, metavar="TEXT", help="custom REPL prompt")
    parser.add_argument("-s", "--startup-script", "--script", dest="startup_script", default=None,
                        metavar="PATH", help="startup script containing emulator commands")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prompt = args.prompt if args.prompt is not None else make_prompt()
    startup_script = Path(args.startup_script).expanduser().resolve() if args.startup_script else None
    print("[configuration]", file=sys.stderr)
    print(f"VFS CSV: {Path(args.vfs_path).expanduser().resolve()}", file=sys.stderr)
    print(f"Prompt: {prompt!r}", file=sys.stderr)
    print(f"Startup script: {startup_script if startup_script else '(not set)'}", file=sys.stderr)
    try:
        vfs = VirtualFileSystem(args.vfs_path)
    except VFSLoadError as exc:
        print(f"shell: VFS load error: {exc}", file=sys.stderr)
        return 2
    if startup_script is not None and (not startup_script.is_file() or not os.access(startup_script, os.R_OK)):
        print(f"shell: startup script is not a readable file: {startup_script}", file=sys.stderr)
        return 2
    shell = Shell(vfs=vfs, prompt=prompt)
    if startup_script is not None:
        shell.run_script(startup_script)
    return shell.run() if shell.running else 0


if __name__ == "__main__":
    raise SystemExit(main())
