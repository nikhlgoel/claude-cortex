#!/usr/bin/env python3
"""
install.sh / install.ps1 / install.cmd are thin launchers around install.py.

What matters is that they hand over faithfully: arguments arrive intact, the exit code comes
back unchanged (2 = bad option, 3 = the safety prompt stopped it), a missing or fake Python is
reported instead of crashing, and nothing is installed unless the person opted in.
Each launcher is run for real, in a throwaway home, on the platforms where it can run.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"


def _bash():
    found = shutil.which("bash")
    if not found:
        return None
    # On Windows `bash` may be the WSL stub, which cannot see these paths; only trust one
    # that can run a trivial command.
    try:
        ok = subprocess.run([found, "-c", "exit 0"], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return found if ok.returncode == 0 else None


def _powershell():
    if not WINDOWS:
        return None
    return shutil.which("powershell") or shutil.which("pwsh")


class LauncherCase:
    """Mixin: subclasses define `command(args)` returning an argv list."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cortex-launch-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.env = dict(os.environ, HOME=self.home, USERPROFILE=self.home,
                        APPDATA=os.path.join(self.root, "roaming"),
                        LOCALAPPDATA=os.path.join(self.root, "local"),
                        PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        for name in ("CLAUDECODE", "CLAUDE_CONFIG_DIR", "CLAUDE_PROFILE", "CORTEX_SANDBOX",
                     "CORTEX_PYTHON", "CORTEX_PROFILES_DIR"):
            self.env.pop(name, None)

    def cortex_entries(self):
        """What Cortex created in the home (PowerShell makes its own AppData; that is not ours)."""
        return [n for n in os.listdir(self.home) if n.startswith(".claude")]

    def run_launcher(self, *args, env=None):
        return subprocess.run(self.command(list(args)), env=env or self.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=240,
                              stdin=subprocess.DEVNULL)

    def test_a_dry_run_shows_the_plan_and_changes_nothing(self):
        result = self.run_launcher("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        self.assertEqual(self.cortex_entries(), [])

    def test_an_unknown_option_comes_back_as_exit_code_2(self):
        result = self.run_launcher("--yes", "--profiles=work")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Unknown option", result.stdout)
        self.assertEqual(self.cortex_entries(), [])

    def test_without_an_operator_or_opt_in_the_guard_stops_it_with_code_3(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(self.cortex_entries(), [])

    def test_a_real_install_in_a_throwaway_home_works_and_honours_surfaces(self):
        env = dict(self.env, CORTEX_SANDBOX="1")
        result = self.run_launcher("--yes", "--surfaces", "terminal", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude")))
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude-profiles")))
        # Only what was chosen: no Desktop or IDE folders were invented.
        self.assertFalse(os.path.exists(os.path.join(self.root, "roaming", "Claude")))

    def test_a_broken_python_override_is_reported_not_crashed_on(self):
        env = dict(self.env, CORTEX_PYTHON=os.path.join(self.root, "no-such-python"))
        result = self.run_launcher("--dry-run", env=env)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CORTEX_PYTHON", result.stdout + result.stderr)
        self.assertEqual(self.cortex_entries(), [])


@unittest.skipUnless(_bash(), "needs a working bash")
class TestShellLauncher(LauncherCase, unittest.TestCase):
    def command(self, args):
        return [_bash(), os.path.join(PROJECT_DIR, "install.sh"), *args]

    def test_the_shell_launcher_has_unix_line_endings(self):
        with open(os.path.join(PROJECT_DIR, "install.sh"), "rb") as fh:
            self.assertNotIn(b"\r", fh.read())


@unittest.skipUnless(_powershell(), "needs Windows PowerShell")
class TestPowerShellLauncher(LauncherCase, unittest.TestCase):
    def command(self, args):
        return [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(PROJECT_DIR, "install.ps1"), *args]

    def test_the_powershell_spellings_are_translated(self):
        env = dict(self.env, CORTEX_SANDBOX="1")
        result = self.run_launcher("-DryRun", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        result = self.run_launcher("-Yes", "-Surfaces", "terminal", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude")))


@unittest.skipUnless(WINDOWS, "a batch file runs only on Windows")
class TestCmdLauncher(LauncherCase, unittest.TestCase):
    def command(self, args):
        return ["cmd.exe", "/d", "/c", os.path.join(PROJECT_DIR, "install.cmd"), *args]

    def test_it_never_waits_for_a_key_when_not_double_clicked(self):
        # stdin is an open pipe nobody writes to, so a stray `pause` blocks (and times out)
        # instead of seeing end-of-file and returning.
        argv = self.command(["--dry-run"])
        proc = subprocess.Popen(argv, env=self.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(proc.stdin.close)
        try:
            self.assertEqual(proc.wait(timeout=20), 0)
        except subprocess.TimeoutExpired:
            self.fail("the launcher is waiting for a key press when run from a terminal")
        finally:
            proc.kill()
            proc.wait()

    def test_a_double_click_does_wait_for_a_key_so_the_window_stays_readable(self):
        # Explorer starts a script as: cmd.exe /c ""C:\path\install.cmd" "  (doubled quote).
        # stdin is an open pipe nobody writes to, so a `pause` blocks instead of seeing EOF.
        script = os.path.join(PROJECT_DIR, "install.cmd")
        raw = 'cmd.exe /c ""' + script + '" --dry-run"'
        proc = subprocess.Popen(raw, env=self.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(proc.stdin.close)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.wait(timeout=6)
        finally:
            proc.kill()
            proc.wait()

    def test_the_batch_file_has_windows_line_endings(self):
        with open(os.path.join(PROJECT_DIR, "install.cmd"), "rb") as fh:
            data = fh.read()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))


if __name__ == "__main__":
    unittest.main()
