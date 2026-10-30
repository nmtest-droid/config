import base64
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shell import (ParsedCommand, Shell, VFSLoadError, VirtualFileSystem,
                   build_parser, main, make_prompt, parse_command)


def write_vfs(path: Path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['path', 'type', 'content_base64'])
        for name, kind, content in rows:
            writer.writerow([name, kind, base64.b64encode(content).decode() if kind == 'file' else ''])


class ParseCommandTests(unittest.TestCase):
    def test_splits_command_and_arguments(self):
        self.assertEqual(parse_command('  ls   -la /tmp  '), ParsedCommand('ls', ['-la', '/tmp']))

    def test_empty_input_returns_none(self):
        self.assertIsNone(parse_command('   \t\n'))


class PromptTests(unittest.TestCase):
    def test_prompt_uses_home_marker(self):
        self.assertEqual(make_prompt('alice', 'workstation', '/home/alice/projects', '/home/alice'),
                         'alice@workstation:~/projects$ ')

    def test_prompt_uses_tilde_for_home(self):
        self.assertEqual(make_prompt('alice', 'workstation', '/home/alice', '/home/alice'),
                         'alice@workstation:~$ ')


class VFSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv_path = Path(self.temp.name) / 'vfs.csv'
        write_vfs(self.csv_path, [
            ('docs', 'dir', b''), ('docs/sub', 'dir', b''),
            ('docs/sub/readme.txt', 'file', b'hello\n'), ('root.txt', 'file', b'root'),
            ('binary.bin', 'file', b'\x00\xff\x10')])

    def test_loads_nested_tree_and_base64_bytes(self):
        vfs = VirtualFileSystem(self.csv_path)
        self.assertEqual(vfs.list_dir('/'), ['binary.bin', 'docs', 'root.txt'])
        self.assertEqual(vfs.list_dir('/docs/sub'), ['readme.txt'])
        self.assertEqual(vfs.read_file('/binary.bin'), b'\x00\xff\x10')

    def test_cd_and_relative_path_resolution(self):
        vfs = VirtualFileSystem(self.csv_path)
        vfs.change_dir('docs/sub')
        self.assertEqual(vfs.cwd, '/docs/sub')
        self.assertEqual(vfs.read_file('../sub/readme.txt'), b'hello\n')
        vfs.change_dir('../../')
        self.assertEqual(vfs.cwd, '/')

    def test_missing_vfs_file(self):
        with self.assertRaisesRegex(VFSLoadError, 'not found'):
            VirtualFileSystem(Path(self.temp.name) / 'missing.csv')

    def test_invalid_header(self):
        self.csv_path.write_text('wrong,header\na,b\n', encoding='utf-8')
        with self.assertRaisesRegex(VFSLoadError, 'invalid CSV header'):
            VirtualFileSystem(self.csv_path)

    def test_invalid_base64(self):
        self.csv_path.write_text('path,type,content_base64\na.txt,file,%%%\n', encoding='utf-8')
        with self.assertRaisesRegex(VFSLoadError, 'invalid base64'):
            VirtualFileSystem(self.csv_path)

    def test_missing_parent_directory(self):
        write_vfs(self.csv_path, [('a/b.txt', 'file', b'x')])
        with self.assertRaisesRegex(VFSLoadError, 'parent directory'):
            VirtualFileSystem(self.csv_path)


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv_path = Path(self.temp.name) / 'vfs.csv'
        write_vfs(self.csv_path, [('dir', 'dir', b''), ('dir/file.txt', 'file', b'content\n'),
                                  ('plain.txt', 'file', b'plain')])
        self.out, self.err = io.StringIO(), io.StringIO()
        self.vfs = VirtualFileSystem(self.csv_path)
        self.shell = Shell(stdin=io.StringIO(), stdout=self.out, stderr=self.err,
                           vfs=self.vfs, prompt='test$ ')

    def test_ls_lists_vfs_entries(self):
        self.assertTrue(self.shell.execute(parse_command('ls')))
        self.assertEqual(self.out.getvalue(), 'dir  plain.txt\n')

    def test_cd_and_pwd(self):
        self.shell.execute(parse_command('cd dir'))
        self.shell.execute(parse_command('pwd'))
        self.assertEqual(self.out.getvalue(), '/dir\n')

    def test_cat_reads_utf8_file(self):
        self.shell.execute(parse_command('cat dir/file.txt'))
        self.assertEqual(self.out.getvalue(), 'content\n')

    def test_cat_reports_binary_file_without_corrupting_it(self):
        write_vfs(self.csv_path, [('binary', 'file', b'\x00\xff')])
        self.shell.vfs = VirtualFileSystem(self.csv_path)
        self.assertFalse(self.shell.execute(parse_command('cat binary')))
        self.assertIn('binary file', self.err.getvalue())
        self.assertEqual(self.shell.vfs.read_file('binary'), b'\x00\xff')

    def test_ls_missing_path_and_cd_to_file_report_errors(self):
        self.assertFalse(self.shell.execute(parse_command('ls absent')))
        self.assertFalse(self.shell.execute(parse_command('cd plain.txt')))
        self.assertIn('no such file or directory', self.err.getvalue())
        self.assertIn('not a directory', self.err.getvalue())

    def test_argument_validation_and_unknown_command(self):
        self.assertFalse(self.shell.execute(parse_command('ls a b')))
        self.assertFalse(self.shell.execute(parse_command('cd a b')))
        self.assertFalse(self.shell.execute(parse_command('cat')))
        self.assertFalse(self.shell.execute(parse_command('unknown')))
        self.assertIn('command not found', self.err.getvalue())

    def test_exit(self):
        self.shell.execute(parse_command('exit'))
        self.assertFalse(self.shell.running)

    def test_script_continues_after_errors(self):
        script = Path(self.temp.name) / 'start.sh'
        script.write_text('pwd\nmissing-command\nls\nexit\n', encoding='utf-8')
        self.shell.run_script(script)
        self.assertIn('test$ pwd\n/\n', self.out.getvalue())
        self.assertIn('test$ ls\ndir  plain.txt\n', self.out.getvalue())
        self.assertIn('command failed; line skipped', self.err.getvalue())
        self.assertFalse(self.shell.running)


class ConfigurationTests(unittest.TestCase):
    def test_parser_accepts_short_and_long_options(self):
        args = build_parser().parse_args(['-v', 'vfs.csv', '-p', 'custom$ ', '-s', 'init.sh'])
        self.assertEqual((args.vfs_path, args.prompt, args.startup_script), ('vfs.csv', 'custom$ ', 'init.sh'))
        args = build_parser().parse_args(['--vfs-path', 'x.csv', '--prompt', 'x', '--script', 's'])
        self.assertEqual((args.vfs_path, args.prompt, args.startup_script), ('x.csv', 'x', 's'))

    def test_main_reports_vfs_load_error(self):
        err = io.StringIO()
        with patch('sys.stderr', err):
            result = main(['-v', '/definitely/missing/vfs.csv'])
        self.assertEqual(result, 2)
        self.assertIn('VFS load error', err.getvalue())

    def test_main_prints_configuration_and_runs_script(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / 'vfs.csv'
            write_vfs(csv_path, [('hello.txt', 'file', b'hello\n')])
            script = Path(directory) / 'init.sh'
            script.write_text('ls\ncat hello.txt\nexit\n', encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with patch('sys.stdout', out), patch('sys.stderr', err), patch('sys.stdin', io.StringIO('')):
                result = main(['-v', str(csv_path), '-p', 'custom$ ', '-s', str(script)])
            self.assertEqual(result, 0)
            self.assertIn('VFS CSV:', err.getvalue())
            self.assertIn("Prompt: 'custom$ '", err.getvalue())
            self.assertIn('Startup script:', err.getvalue())
            self.assertIn('custom$ ls\nhello.txt\ncustom$ cat hello.txt\nhello\n', out.getvalue())


if __name__ == '__main__':
    unittest.main()
