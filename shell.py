#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import getpass
import os
import shlex
import socket
import sys
import time
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
        rel = rel.replace("\\", "/")
        cwd_display = cwd.replace("\\", "/")

        if rel == ".":
            shown = "~"
        elif rel == ".." or rel.startswith("../"):
            shown = cwd_display
        else:
            shown = "~/" + rel

    except ValueError:
        shown = cwd.replace("\\", "/")

    return f"{username}@{hostname}:{shown}$ "


@dataclass
class VFSNode:
    name: str
    kind: str
    data: bytes = b""
    children: dict[str, "VFSNode"] = field(default_factory=dict)
    owner: str = "root"
    group: str = "root"
    modified_at: float = field(default_factory=time.time)


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

    def touch(self, path: str, *, create: bool = True) -> bool:
        """Update an entry timestamp or create an empty file, entirely in memory."""
        node, _ = self.resolve(path)
        if node is not None:
            node.modified_at = time.time()
            return False
        if not create:
            return False
        parts = self._parts(path, self.cwd)
        if not parts:
            raise IsADirectoryError(f"{path}: is a directory")
        parent = self.root
        for part in parts[:-1]:
            if part not in parent.children:
                raise FileNotFoundError(f"{path}: parent directory does not exist")
            parent = parent.children[part]
            if parent.kind != "dir":
                raise NotADirectoryError(f"{path}: parent component is not a directory")
        name = parts[-1]
        parent.children[name] = VFSNode(name, "file", b"")
        return True

    def change_owner(self, path: str, owner: str | None, group: str | None, *, recursive: bool = False) -> None:
        node, _ = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"{path}: no such file or directory")

        def apply(current: VFSNode) -> None:
            if owner is not None:
                current.owner = owner
            if group is not None:
                current.group = group
            if recursive and current.kind == "dir":
                for child in current.children.values():
                    apply(child)

        apply(node)

    def disk_usage(self, path: str = ".") -> tuple[int, list[tuple[str, int, bool]]]:
        """Return total bytes and post-order entries (path, bytes, is_dir)."""
        node, resolved = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"{path}: no such file or directory")
        if node.kind == "file":
            return len(node.data), [(path, len(node.data), False)]

        entries: list[tuple[str, int, bool]] = []

        def walk(current: VFSNode, current_path: str) -> int:
            total = 0
            for child_name in sorted(current.children):
                child = current.children[child_name]
                child_path = (current_path.rstrip("/") + "/" + child_name) if current_path != "/" else "/" + child_name
                if child.kind == "file":
                    size = len(child.data)
                    total += size
                    entries.append((child_path, size, False))
                else:
                    size = walk(child, child_path)
                    total += size
                    entries.append((child_path, size, True))
            return total

        display_root = path.rstrip("/") or "/"
        total = walk(node, display_root)
        entries.append((path, total, True))
        return total, entries


class Shell:
    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None,
                 stderr: TextIO | None = None, *, vfs: VirtualFileSystem,
                 prompt: str | None = None):
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.running = True
        self.vfs = vfs
        self.custom_prompt = prompt

    def _error(self, message: str) -> None:
        print(f"shell: {message}", file=self.stderr)

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "K", "M", "G", "T"):
            if value < 1024 or unit == "T":
                return f"{int(value)}{unit}" if unit == "B" else f"{value:.1f}{unit}"
            value /= 1024
        return f"{value:.1f}T"

    def _run_uniq(self, args: list[str]) -> bool:
        mode = "all"
        filename: str | None = None
        index = 0
        while index < len(args) and args[index].startswith("-"):
            option = args[index]
            if option in ("-c", "--count"):
                if mode != "all":
                    self._error("uniq: options -c, -d and -u are mutually exclusive")
                    return False
                mode = "count"
            elif option in ("-d", "--repeated"):
                if mode != "all":
                    self._error("uniq: options -c, -d and -u are mutually exclusive")
                    return False
                mode = "repeated"
            elif option in ("-u", "--unique"):
                if mode != "all":
                    self._error("uniq: options -c, -d and -u are mutually exclusive")
                    return False
                mode = "unique"
            else:
                self._error(f"uniq: invalid option '{option}'")
                return False
            index += 1
        remaining = args[index:]
        if len(remaining) != 1:
            self._error("uniq: expected one VFS file and optional mode (-c, -d or -u)")
            return False
        filename = remaining[0]
        try:
            content = self.vfs.read_file(filename).decode("utf-8")
        except (FileNotFoundError, IsADirectoryError) as exc:
            self._error(f"uniq: {exc}")
            return False
        except UnicodeDecodeError:
            self._error(f"uniq: {filename}: binary file is not supported")
            return False

        lines = content.splitlines(keepends=True)
        groups: list[tuple[str, int]] = []
        for line in lines:
            key = line.rstrip("\r\n")
            if groups and groups[-1][0].rstrip("\r\n") == key:
                groups[-1] = (groups[-1][0], groups[-1][1] + 1)
            else:
                groups.append((line, 1))
        for line, count in groups:
            if mode == "repeated" and count < 2:
                continue
            if mode == "unique" and count != 1:
                continue
            if mode == "count":
                self.stdout.write(f"{count:7d} {line}")
            else:
                self.stdout.write(line)
        return True

    def _run_du(self, args: list[str]) -> bool:
        show_all = human = summarize = False
        paths: list[str] = []
        for arg in args:
            if arg.startswith("-") and arg != "-":
                if arg in ("-a", "--all"):
                    show_all = True
                elif arg in ("-h", "--human-readable"):
                    human = True
                elif arg in ("-s", "--summarize"):
                    summarize = True
                elif arg.startswith("-") and len(arg) > 2 and not arg.startswith("--"):
                    for flag in arg[1:]:
                        if flag == "a": show_all = True
                        elif flag == "h": human = True
                        elif flag == "s": summarize = True
                        else:
                            self._error(f"du: invalid option '-{flag}'")
                            return False
                else:
                    self._error(f"du: invalid option '{arg}'")
                    return False
            else:
                paths.append(arg)
        if len(paths) > 1:
            self._error("du: expected at most one path")
            return False
        path = paths[0] if paths else "."
        try:
            total, entries = self.vfs.disk_usage(path)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._error(f"du: {exc}")
            return False

        if summarize or not entries[-1][2]:
            entries_to_print = [(path, total, entries[-1][2])]
        elif show_all:
            entries_to_print = entries
        else:
            entries_to_print = [entry for entry in entries if entry[2]]
        for entry_path, size, _is_dir in entries_to_print:
            displayed = self._human_size(size) if human else str(size)
            print(f"{displayed}\t{entry_path}", file=self.stdout)
        return True

    def _run_touch(self, args: list[str]) -> bool:
        no_create = False
        paths: list[str] = []
        for arg in args:
            if arg in ("-c", "--no-create"):
                no_create = True
            elif arg.startswith("-") and arg != "-":
                self._error(f"touch: invalid option '{arg}'")
                return False
            else:
                paths.append(arg)
        if not paths:
            self._error("touch: expected at least one path")
            return False
        for path in paths:
            try:
                self.vfs.touch(path, create=not no_create)
            except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
                self._error(f"touch: {exc}")
                return False
        return True

    def _run_chown(self, args: list[str]) -> bool:
        recursive = False
        remaining: list[str] = []
        for arg in args:
            if arg in ("-R", "--recursive"):
                recursive = True
            elif arg.startswith("-") and arg != "-":
                self._error(f"chown: invalid option '{arg}'")
                return False
            else:
                remaining.append(arg)
        if len(remaining) < 2:
            self._error("chown: expected OWNER[:GROUP] and at least one path")
            return False
        spec, *paths = remaining
        if spec.count(":") > 1:
            self._error(f"chown: invalid owner/group '{spec}'")
            return False
        if ":" in spec:
            owner_text, group_text = spec.split(":", 1)
            owner = owner_text or None
            group = group_text or None
            if owner is None and group is None:
                self._error("chown: owner or group must be specified")
                return False
        else:
            owner, group = spec, None
        for path in paths:
            try:
                self.vfs.change_owner(path, owner, group, recursive=recursive)
            except FileNotFoundError as exc:
                self._error(f"chown: {exc}")
                return False
        return True

    def execute(self, command: ParsedCommand | None) -> bool:
        if command is None:
            return True
        name, args = command.name, command.args
        if name == "ls":
            long_format = False
            paths = []
            for arg in args:
                if arg in ("-l", "--long"):
                    long_format = True
                elif arg.startswith("-") and arg != "-":
                    self._error(f"ls: invalid option '{arg}'")
                    return False
                else:
                    paths.append(arg)
            if len(paths) > 1:
                self._error("ls: too many arguments (expected at most one path)")
                return False
            target = paths[0] if paths else "."
            try:
                node, resolved = self.vfs.resolve(target)
                if node is None:
                    raise FileNotFoundError(f"{target}: no such file or directory")
                if node.kind == "file":
                    entries = [(node.name, node)]
                else:
                    entries = [(name, node.children[name]) for name in sorted(node.children)]
                if long_format:
                    for entry_name, entry in entries:
                        kind = "d" if entry.kind == "dir" else "-"
                        print(f"{kind}\t{entry.owner}\t{entry.group}\t{entry_name}", file=self.stdout)
                else:
                    print("  ".join(entry_name for entry_name, _entry in entries), file=self.stdout)
            except (FileNotFoundError, NotADirectoryError) as exc:
                self._error(f"ls: {exc}")
                return False
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
        if name == "uniq":
            return self._run_uniq(args)
        if name == "du":
            return self._run_du(args)
        if name == "touch":
            return self._run_touch(args)
        if name == "chown":
            return self._run_chown(args)
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
                    self.stdout.write(self._get_prompt() + text + "\n")
                    self.stdout.flush()
                    if not self.execute(parse_command(text)):
                        self._error(f"startup script {path}:{line_number}: command failed; line skipped")
        except OSError as exc:
            self._error(f"cannot execute startup script '{path}': {exc}")

    def run(self) -> int:
        while self.running:
            self.stdout.write(self._get_prompt())
            self.stdout.flush()
            line = self.stdin.readline()
            if line == "":
                self.stdout.write("\n")
                break
            self.execute(parse_command(line))
        return 0

    def _get_prompt(self) -> str:
        if self.custom_prompt is not None:
            return self.custom_prompt

        username = getpass.getuser()
        hostname = socket.gethostname()
        return f"{username}@{hostname}:{self.vfs.cwd}$ "


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
    prompt = args.prompt
    startup_script = Path(args.startup_script).expanduser().resolve() if args.startup_script else None
    print("[configuration]", file=sys.stderr)
    print(f"VFS CSV: {Path(args.vfs_path).expanduser().resolve()}", file=sys.stderr)
    print(f"Prompt: {prompt if prompt is not None else '(dynamic VFS path)'}", file=sys.stderr)
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
