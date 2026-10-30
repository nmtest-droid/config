import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shell import ParsedCommand, Shell, build_parser, main, make_prompt, parse_command


class ParseCommandTests(unittest.TestCase):
    def test_splits_command_and_arguments(self):
        self.assertEqual(
            parse_command("  ls   -la /tmp  "),
            ParsedCommand("ls", ["-la", "/tmp"]),
        )

    def test_empty_input_returns_none(self):
        self.assertIsNone(parse_command("   \t\n"))


class PromptTests(unittest.TestCase):
    def test_prompt_uses_home_marker(self):
        self.assertEqual(
            make_prompt("alice", "workstation", "/home/alice/projects", "/home/alice"),
            "alice@workstation:~/projects$ ",
        )

    def test_prompt_uses_tilde_for_home(self):
        self.assertEqual(
            make_prompt("alice", "workstation", "/home/alice", "/home/alice"),
            "alice@workstation:~$ ",
        )


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.shell = Shell(stdin=io.StringIO(), stdout=self.out, stderr=self.err)

    def test_ls_stub_echoes_command_and_arguments(self):
        self.shell.execute(parse_command("ls -la /tmp"))
        self.assertEqual(self.out.getvalue(), "ls -la /tmp\n")

    def test_cd_stub_echoes_command_and_argument(self):
        self.shell.execute(parse_command("cd /tmp"))
        self.assertEqual(self.out.getvalue(), "cd /tmp\n")

    def test_cd_rejects_more_than_one_argument(self):
        self.shell.execute(parse_command("cd /tmp /var"))
        self.assertEqual(self.err.getvalue(), "shell: cd: too many arguments (expected 0 or 1)\n")

    def test_unknown_command_reports_error(self):
        self.shell.execute(parse_command("not_a_command"))
        self.assertEqual(self.err.getvalue(), "shell: not_a_command: command not found\n")

    def test_exit_without_arguments_stops_loop(self):
        self.shell.execute(parse_command("exit"))
        self.assertFalse(self.shell.running)

    def test_exit_rejects_arguments(self):
        self.shell.execute(parse_command("exit now"))
        self.assertTrue(self.shell.running)
        self.assertEqual(self.err.getvalue(), "shell: exit: too many arguments (expected none)\n")

    def test_empty_command_is_ignored(self):
        self.shell.execute(parse_command("   "))
        self.assertEqual(self.out.getvalue(), "")
        self.assertEqual(self.err.getvalue(), "")


class ReplTests(unittest.TestCase):
    def test_run_processes_commands_until_exit(self):
        out = io.StringIO()
        err = io.StringIO()
        shell = Shell(stdin=io.StringIO("ls -l\nunknown\nexit\n"), stdout=out, stderr=err, prompt="user@host:~$ ")
        with patch("shell.make_prompt", return_value="user@host:~$ "):
            self.assertEqual(shell.run(), 0)
        self.assertEqual(out.getvalue(), "user@host:~$ ls -l\nuser@host:~$ user@host:~$ ")
        self.assertEqual(err.getvalue(), "shell: unknown: command not found\n")


class ConfigurationTests(unittest.TestCase):
    def test_parser_accepts_all_configuration_options(self):
        args = build_parser().parse_args([
            "--vfs", "/tmp", "--prompt", "custom$ ", "--startup-script", "/tmp/init.sh"
        ])
        self.assertEqual(args.vfs_path, "/tmp")
        self.assertEqual(args.prompt, "custom$ ")
        self.assertEqual(args.startup_script, "/tmp/init.sh")

    def test_shell_stores_vfs_and_custom_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            shell = Shell(stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO(),
                          vfs_path=directory, prompt="custom$ ")
            self.assertEqual(shell.vfs_path, Path(directory).resolve())
            self.assertEqual(shell.prompt, "custom$ ")

    def test_startup_script_echoes_commands_and_skips_failed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "init.sh"
            script.write_text("ls -l\nunknown\ncd /tmp /var\nls /after\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            shell = Shell(stdin=io.StringIO(), stdout=out, stderr=err, prompt="test$ ")
            shell.run_script(script)
            self.assertEqual(out.getvalue(),
                "test$ ls -l\nls -l\ntest$ unknown\ntest$ cd /tmp /var\n"
                "test$ ls /after\nls /after\n")
            self.assertIn("unknown: command not found", err.getvalue())
            self.assertIn("startup script", err.getvalue())
            self.assertIn(":2: command failed; line skipped", err.getvalue())
            self.assertIn(":3: command failed; line skipped", err.getvalue())

    def test_main_rejects_nonexistent_vfs(self):
        err = io.StringIO()
        with patch("sys.stderr", err):
            result = main(["--vfs", "/path/that/does/not/exist"])
        self.assertEqual(result, 2)
        self.assertIn("VFS path is not an existing directory", err.getvalue())

    def test_main_prints_all_configuration_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "init.sh"
            script.write_text("ls\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with patch("sys.stdout", out), patch("sys.stderr", err), \
                 patch("sys.stdin", io.StringIO("exit\n")), \
                 patch("shell.make_prompt", return_value="os$ "):
                result = main(["--vfs", directory, "--prompt", "custom$ ",
                               "--startup-script", str(script)])
            self.assertEqual(result, 0)
            self.assertIn(f"VFS path: {Path(directory).resolve()}", err.getvalue())
            self.assertIn("Prompt: 'custom$ '", err.getvalue())
            self.assertIn(f"Startup script: {script.resolve()}", err.getvalue())
            self.assertIn("custom$ ls\nls\n", out.getvalue())


if __name__ == "__main__":
    unittest.main()
