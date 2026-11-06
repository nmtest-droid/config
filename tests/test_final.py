"""Regression tests for shell.py. Run from project root:
    py -m unittest discover -s tests -p "test_final.py" -v
Standard library only.
"""
import base64, csv, getpass, io, os, socket, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shell


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / "vfs.csv"
        rows = [
            ("docs", "dir", ""),
            ("docs/readme.txt", "file", base64.b64encode(b"Hello\n").decode()),
            ("docs/repeated.txt", "file", base64.b64encode(b"a\na\nb\nc\nc\n").decode()),
            ("docs/nested", "dir", ""),
            ("docs/nested/data.bin", "file", base64.b64encode(b"\x00\x01\xff").decode()),
            ("empty.txt", "file", ""),
        ]
        with self.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["path", "type", "content_base64"]); w.writerows(rows)
        self.vfs = shell.VirtualFileSystem(self.csv)
        self.out, self.err = io.StringIO(), io.StringIO()
        self.app = shell.Shell(stdin=io.StringIO(), stdout=self.out, stderr=self.err,
                               vfs=self.vfs, prompt="test:/$ ")

    def cmd(self, line):
        return self.app.execute(shell.parse_command(line))


class ParserPromptTests(Fixture):
    def test_parser(self):
        p = shell.parse_command("  ls   -l docs ")
        self.assertEqual((p.name, p.args), ("ls", ["-l", "docs"]))

    def test_empty_parse(self):
        self.assertIsNone(shell.parse_command("  \t"))

    def test_prompt_identity(self):
        p = shell.make_prompt(username="alice", hostname="pc",
                              cwd=r"C:\Users\alice", home=r"C:\Users\alice")
        self.assertEqual(p, "alice@pc:~$ ")

    def test_default_prompt_uses_os_identity(self):
        p = shell.make_prompt()
        self.assertIn(getpass.getuser(), p)
        self.assertIn(socket.gethostname(), p)
        self.assertTrue(p.endswith("$ "))


class VfsTests(Fixture):
    def test_nested_directories(self):
        self.assertEqual(self.vfs.list_dir("/"), ["docs", "empty.txt"])
        self.assertEqual(self.vfs.list_dir("/docs/nested"), ["data.bin"])

    def test_text_and_binary_data(self):
        self.assertEqual(self.vfs.read_file("docs/readme.txt"), b"Hello\n")
        self.assertEqual(self.vfs.read_file("docs/nested/data.bin"), b"\x00\x01\xff")

    def test_relative_paths(self):
        self.vfs.change_dir("/docs/nested")
        self.assertEqual(self.vfs.resolve("../readme.txt")[0].data, b"Hello\n")
        self.assertEqual(self.vfs.resolve("../../empty.txt")[1], "/empty.txt")

    def test_cd(self):
        self.vfs.change_dir("docs/nested")
        self.assertEqual(self.vfs.cwd, "/docs/nested")
        self.vfs.change_dir("..")
        self.assertEqual(self.vfs.cwd, "/docs")

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError): self.vfs.read_file("missing")

    def test_read_directory(self):
        with self.assertRaises(IsADirectoryError): self.vfs.read_file("docs")

    def test_list_file(self):
        with self.assertRaises(NotADirectoryError): self.vfs.list_dir("empty.txt")

    def test_missing_csv(self):
        with self.assertRaises(shell.VFSLoadError):
            shell.VirtualFileSystem(self.root / "missing.csv")

    def test_bad_header(self):
        p = self.root / "bad.csv"; p.write_text("name,kind\nx,file\n", encoding="utf-8")
        with self.assertRaises(shell.VFSLoadError): shell.VirtualFileSystem(p)

    def test_bad_base64(self):
        p = self.root / "bad64.csv"
        p.write_text("path,type,content_base64\nx,file,%%%bad%%%\n", encoding="utf-8")
        with self.assertRaises(shell.VFSLoadError): shell.VirtualFileSystem(p)

    def test_missing_parent(self):
        p = self.root / "parent.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["path", "type", "content_base64"])
            w.writerow(["absent/file", "file", ""])
        with self.assertRaises(shell.VFSLoadError): shell.VirtualFileSystem(p)


class BasicCommands(Fixture):
    def test_ls(self):
        self.assertTrue(self.cmd("ls")); self.assertIn("docs", self.out.getvalue())

    def test_ls_long(self):
        self.assertTrue(self.cmd("ls -l docs"))
        self.assertIn("root", self.out.getvalue()); self.assertIn("readme.txt", self.out.getvalue())

    def test_ls_errors(self):
        self.assertFalse(self.cmd("ls missing")); self.assertIn("no such file", self.err.getvalue())

    def test_cd_pwd(self):
        self.assertTrue(self.cmd("cd docs")); self.assertTrue(self.cmd("pwd"))
        self.assertEqual(self.out.getvalue().strip(), "/docs")

    def test_cd_bad_args(self):
        self.assertFalse(self.cmd("cd docs nested"))
        self.assertIn("too many arguments", self.err.getvalue())

    def test_cat_text(self):
        self.assertTrue(self.cmd("cat docs/readme.txt"))
        self.assertEqual(self.out.getvalue(), "Hello\n")

    def test_cat_binary_error(self):
        self.assertFalse(self.cmd("cat docs/nested/data.bin"))
        self.assertIn("binary file", self.err.getvalue())

    def test_unknown_command(self):
        self.assertFalse(self.cmd("nonesuch"))
        self.assertIn("command not found", self.err.getvalue())

    def test_exit(self):
        self.assertTrue(self.cmd("exit")); self.assertFalse(self.app.running)

    def test_exit_arguments(self):
        self.assertFalse(self.cmd("exit now")); self.assertTrue(self.app.running)


class UniqDuTests(Fixture):
    def test_uniq_default(self):
        self.assertTrue(self.cmd("uniq docs/repeated.txt"))
        self.assertEqual(self.out.getvalue(), "a\nb\nc\n")

    def test_uniq_count(self):
        self.assertTrue(self.cmd("uniq -c docs/repeated.txt"))
        self.assertIn("2 a\n", self.out.getvalue()); self.assertIn("1 b\n", self.out.getvalue())

    def test_uniq_repeated(self):
        self.assertTrue(self.cmd("uniq -d docs/repeated.txt"))
        self.assertEqual(self.out.getvalue(), "a\nc\n")

    def test_uniq_unique(self):
        self.assertTrue(self.cmd("uniq -u docs/repeated.txt"))
        self.assertEqual(self.out.getvalue(), "b\n")

    def test_uniq_conflicting_modes(self):
        self.assertFalse(self.cmd("uniq -c -d docs/repeated.txt"))
        self.assertIn("mutually exclusive", self.err.getvalue())

    def test_uniq_binary(self):
        self.assertFalse(self.cmd("uniq docs/nested/data.bin"))
        self.assertIn("binary file", self.err.getvalue())

    def test_du_summary(self):
        self.assertTrue(self.cmd("du -s docs"))
        self.assertEqual(len(self.out.getvalue().strip().splitlines()), 1)

    def test_du_all(self):
        self.assertTrue(self.cmd("du -a docs"))
        self.assertIn("readme.txt", self.out.getvalue())
        self.assertIn("data.bin", self.out.getvalue())

    def test_du_human(self):
        self.assertTrue(self.cmd("du -h -s docs"))
        self.assertIn("B\tdocs", self.out.getvalue())

    def test_du_multiple_paths_error(self):
        self.assertFalse(self.cmd("du docs empty.txt"))


class MutationTests(Fixture):
    def test_touch_create(self):
        self.assertTrue(self.cmd("touch docs/new.txt"))
        self.assertEqual(self.vfs.read_file("docs/new.txt"), b"")

    def test_touch_no_create(self):
        self.assertTrue(self.cmd("touch -c docs/not-created"))
        self.assertIsNone(self.vfs.resolve("docs/not-created")[0])

    def test_touch_missing_parent(self):
        self.assertFalse(self.cmd("touch missing/new"))
        self.assertIn("parent directory", self.err.getvalue())

    def test_chown_owner_group(self):
        self.assertTrue(self.cmd("chown alice:staff docs/readme.txt"))
        n, _ = self.vfs.resolve("docs/readme.txt")
        self.assertEqual((n.owner, n.group), ("alice", "staff"))

    def test_chown_group_only(self):
        self.assertTrue(self.cmd("chown :editors docs/readme.txt"))
        n, _ = self.vfs.resolve("docs/readme.txt")
        self.assertEqual((n.owner, n.group), ("root", "editors"))

    def test_chown_recursive(self):
        self.assertTrue(self.cmd("chown -R alice:staff docs"))
        for p in ("docs", "docs/readme.txt", "docs/nested", "docs/nested/data.bin"):
            n, _ = self.vfs.resolve(p)
            self.assertEqual((n.owner, n.group), ("alice", "staff"))

    def test_chown_empty_spec_error(self):
        self.assertFalse(self.cmd("chown : docs"))
        self.assertIn("must be specified", self.err.getvalue())


class ScriptCliTests(Fixture):
    def test_script_skips_bad_line_and_continues(self):
        p = self.root / "startup.txt"
        p.write_text("# comment\npwd\nunknown-command\nls\n", encoding="utf-8")
        self.app.run_script(p)
        self.assertIn("test:/$ pwd", self.out.getvalue())
        self.assertIn("test:/$ ls", self.out.getvalue())
        self.assertIn("line skipped", self.err.getvalue())

    def test_script_stops_at_exit(self):
        p = self.root / "exit.txt"; p.write_text("exit\npwd\n", encoding="utf-8")
        self.app.run_script(p)
        self.assertFalse(self.app.running)
        self.assertNotIn("test:/$ pwd", self.out.getvalue())

    def test_repl_reads_until_exit(self):
        app = shell.Shell(stdin=io.StringIO("pwd\nexit\n"), stdout=self.out,
                          stderr=self.err, vfs=self.vfs, prompt="win:/$ ")
        self.assertEqual(app.run(), 0)
        self.assertIn("/\n", self.out.getvalue())

    def test_cli_help(self):
        result = subprocess.run([sys.executable, str(ROOT / "shell.py"), "--help"],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--vfs", result.stdout)
        self.assertIn("--prompt", result.stdout)
        self.assertIn("--startup-script", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
