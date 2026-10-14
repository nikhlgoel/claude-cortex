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
    # On Windows `bash` may be the WSL launcher (System32\bash.exe), which cannot open a Windows
    # path such as D:\x\install.sh. "Can it run `exit 0`" does not tell the two apart; running a real
    # script at a real path does.
    probe = tempfile.mkdtemp(prefix="cortex-bash-probe-")
    try:
        script = os.path.join(probe, "probe.sh")
        with open(script, "w", newline="\n") as fh:
            fh.write("echo cortex-ok\n")
        ok = subprocess.run([found, script], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    return found if ok.returncode == 0 and "cortex-ok" in ok.stdout else None


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


# ---- the native launchers (install.exe, bin/claude.exe) and "does a hostile path survive?" ----------

INSTALL_EXE = os.path.join(PROJECT_DIR, "install.exe")
SHIM_EXE = os.path.join(PROJECT_DIR, "bin", "claude.exe")

# A folder name that is special to some shell in every position: spaces, ' & ( ) % ^ ! and accents.
HOSTILE_DIR = "we ird & (name) 'q' 100%x% ^ !g! \u00fcn\u00ef"

# Arguments every script launcher can carry. cmd.exe cannot pass an unquoted & or an empty one,
# so those are in the shell-free set below.
COMMON_ARGS = ["plain", "with space", "two  spaces", "--flag=a b", "ünï-cødé", "trailing\\"]
# What a launcher that never involves a shell can additionally promise. A double quote is here and
# not above on purpose: cmd.exe has no way to escape one and Windows PowerShell 5.1 drops it from
# -File arguments. Those are limits of the shells, and the reason install.exe exists.
SHELL_FREE_ARGS = COMMON_ARGS + ['say "hi"', "", "&", "|", "^", "%PATH%", "!x!", "C:\\dir with space\\",
                                 'a\\\\"b', "(x)"]

FAKE_INSTALL_PY = (
    "import json, os, sys\n"
    "print(json.dumps({'argv': sys.argv[1:], 'here': os.path.dirname(os.path.abspath(__file__))}))\n"
    "sys.exit(7)\n"
)


class HostilePathCase:
    """Mixin: copy one launcher plus a fake install.py into a nasty folder and check that
    (a) it still finds and runs install.py, (b) every argument arrives unchanged, (c) the child's
    exit code comes back unchanged. Subclasses define launcher_files() and command(folder, args)."""

    expected_args = COMMON_ARGS

    def make_folder(self):
        root = tempfile.mkdtemp(prefix="cortex-hostile-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        folder = os.path.join(root, HOSTILE_DIR)
        os.makedirs(folder)
        for name in self.launcher_files():
            shutil.copy(os.path.join(PROJECT_DIR, name), os.path.join(folder, os.path.basename(name)))
        with open(os.path.join(folder, "install.py"), "w", encoding="utf-8") as fh:
            fh.write(FAKE_INSTALL_PY)
        return folder

    def run_in(self, folder, args, env=None):
        base = dict(os.environ, PYTHONUTF8="1", CORTEX_PYTHON=sys.executable)
        base.update(env or {})
        return subprocess.run(self.command_in(folder, list(args)), env=base, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)

    def test_a_hostile_folder_name_and_every_argument_arrive_intact(self):
        import json
        folder = self.make_folder()
        result = self.run_in(folder, self.expected_args)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)   # the child's code, unchanged
        line = next(x for x in result.stdout.splitlines() if x.startswith("{"))   # the launcher may add a note after
        reported = json.loads(line)
        self.assertEqual(reported["argv"], self.expected_args)
        self.assertEqual(os.path.normcase(reported["here"]), os.path.normcase(folder))


@unittest.skipUnless(WINDOWS and os.path.isfile(INSTALL_EXE), "needs Windows and a built install.exe")
class TestNativeInstaller(LauncherCase, HostilePathCase, unittest.TestCase):
    """install.exe is not a script and starts no shell, so it also has to carry the awkward arguments."""

    expected_args = SHELL_FREE_ARGS

    def command(self, args):
        return [INSTALL_EXE, *args]

    def launcher_files(self):
        return ["install.exe"]

    def command_in(self, folder, args):
        return [os.path.join(folder, "install.exe"), *args]

    def test_it_says_what_is_wrong_when_install_py_is_not_beside_it(self):
        folder = self.make_folder()
        os.remove(os.path.join(folder, "install.py"))
        result = self.run_in(folder, [])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("install.py was not found", result.stderr)
        self.assertIn("Extract", result.stderr)

    def test_it_finds_python_on_PATH_and_skips_a_stub_that_is_not_python(self):
        folder = self.make_folder()
        fake = os.path.join(self.root, "fake-bin")
        os.makedirs(fake)
        # A python.exe that is not Python (the Microsoft Store stub looks like this): it must be
        # tried, found wanting, and passed over.
        shutil.copy(INSTALL_EXE, os.path.join(fake, "python.exe"))
        real = os.path.dirname(sys.executable)
        if not os.path.isfile(os.path.join(real, "python.exe")):
            self.skipTest("this interpreter is not called python.exe")
        env = dict(os.environ, PYTHONUTF8="1", PATH=fake + os.pathsep + real)
        env.pop("CORTEX_PYTHON", None)
        result = subprocess.run(self.command_in(folder, ["x"]), env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)

    def test_a_name_given_without_a_path_is_looked_up_on_PATH(self):
        folder = self.make_folder()
        real = os.path.dirname(sys.executable)
        name = os.path.splitext(os.path.basename(sys.executable))[0]
        env = dict(os.environ, PYTHONUTF8="1", CORTEX_PYTHON=name, PATH=real)
        result = subprocess.run(self.command_in(folder, ["x"]), env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)

    def _hidden_console(self, env):
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0                        # SW_HIDE: a real console, but no window flashes up
        return subprocess.Popen([INSTALL_EXE], env=env, startupinfo=info,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)

    def test_when_double_clicked_it_waits_so_the_message_can_be_read(self):
        # Own console, nobody else on it: what Explorer produces. A missing interpreter is the
        # quickest failure that prints a message.
        env = dict(self.env, CORTEX_PYTHON=os.path.join(self.root, "no-such-python"))
        proc = self._hidden_console(env)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        finally:
            proc.kill()
            proc.wait()

    def test_and_the_same_failure_does_not_wait_when_told_not_to(self):
        env = dict(self.env, CORTEX_PYTHON=os.path.join(self.root, "no-such-python"),
                   CORTEX_LAUNCHER_PAUSE="never")
        proc = self._hidden_console(env)
        try:
            self.assertEqual(proc.wait(timeout=30), 1)
        finally:
            proc.kill()
            proc.wait()

    def test_a_real_terminal_style_run_never_waits(self):
        # stdin is an open pipe nobody writes to: a stray read would block until the timeout.
        proc = subprocess.Popen([INSTALL_EXE, "--dry-run"], env=self.env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(proc.stdin.close)
        try:
            self.assertEqual(proc.wait(timeout=60), 0)
        finally:
            proc.kill()
            proc.wait()


@unittest.skipUnless(WINDOWS and os.path.isfile(SHIM_EXE), "needs Windows and a built bin/claude.exe")
class TestNativeShim(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cortex-shim-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.env = dict(os.environ, PYTHONUTF8="1", CORTEX_PYTHON=sys.executable,
                        USERPROFILE=os.path.join(self.root, "home"), HOME=os.path.join(self.root, "home"))
        self.env.pop("CORTEX_HOME", None)

    def run_shim(self, exe, *args):
        # From a neutral folder: `python -m` puts the current directory first on the module path, so
        # running from the repository would always find the repository's own cortex package.
        return subprocess.run([exe, *args], env=self.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, stdin=subprocess.DEVNULL, cwd=self.root)

    def test_it_runs_the_cortex_core_beside_bin(self):
        result = self.run_shim(SHIM_EXE, "--version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Claude Cortex", result.stdout)

    def test_it_runs_from_a_hostile_folder_when_pointed_at_the_core(self):
        folder = os.path.join(self.root, HOSTILE_DIR, "bin")
        os.makedirs(folder)
        exe = os.path.join(folder, "claude.exe")
        shutil.copy(SHIM_EXE, exe)
        self.env["CORTEX_HOME"] = PROJECT_DIR
        result = self.run_shim(exe, "--version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Claude Cortex", result.stdout)

    def test_it_says_so_when_there_is_no_core_to_run(self):
        folder = os.path.join(self.root, "lonely", "bin")
        os.makedirs(folder)
        exe = os.path.join(folder, "claude.exe")
        shutil.copy(SHIM_EXE, exe)
        result = self.run_shim(exe, "--version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("core was not found", result.stderr)

    def test_every_argument_reaches_cortex_unchanged(self):
        # A fake core that only reports its argv. PowerShell used to bind `-p` to a common parameter
        # and lose the prompt; with no shell in between nothing can.
        import json
        core = os.path.join(self.root, "fake core (x)")
        os.makedirs(os.path.join(core, "cortex"))
        with open(os.path.join(core, "cortex", "__init__.py"), "w") as fh:
            fh.write("")
        with open(os.path.join(core, "cortex", "__main__.py"), "w") as fh:
            fh.write("import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(5)\n")
        self.env["CORTEX_HOME"] = core
        result = self.run_shim(SHIM_EXE, *SHELL_FREE_ARGS, "-p", "hello world")
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), SHELL_FREE_ARGS + ["-p", "hello world"])


@unittest.skipUnless(WINDOWS, "a batch file runs only on Windows")
class TestCmdLauncherHostilePath(HostilePathCase, unittest.TestCase):
    def launcher_files(self):
        return ["install.cmd"]

    def command_in(self, folder, args):
        # The form Explorer and `start` use: /s plus an outer pair of quotes. Without them cmd.exe
        # discards the quoting around a path containing & or ^ and splits it there - a property of
        # how cmd is started, not of the batch file.
        line = subprocess.list2cmdline([os.path.join(folder, "install.cmd"), *args])
        return 'cmd.exe /d /s /c "' + line + '"'


@unittest.skipUnless(_powershell(), "needs Windows PowerShell")
class TestPowerShellLauncherHostilePath(HostilePathCase, unittest.TestCase):
    def launcher_files(self):
        return ["install.ps1"]

    def command_in(self, folder, args):
        return [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                os.path.join(folder, "install.ps1"), *args]


@unittest.skipUnless(_bash(), "needs a working bash")
class TestShellLauncherHostilePath(HostilePathCase, unittest.TestCase):
    # Not 'a\\"b': on Windows, bash.exe splits its own command line (MSYS rules, before install.sh
    # ever runs), and reads backslash-then-quote differently from the Microsoft rules.
    expected_args = [a for a in SHELL_FREE_ARGS if a != 'a\\\\"b']

    def launcher_files(self):
        return ["install.sh"]

    def command_in(self, folder, args):
        return [_bash(), os.path.join(folder, "install.sh"), *args]


@unittest.skipUnless(WINDOWS and os.path.isfile(INSTALL_EXE), "needs Windows and the built launchers")
class TestLauncherSourceMatchesBinaries(unittest.TestCase):
    def test_the_committed_exe_files_are_what_native_launcher_c_builds(self):
        # A binary nobody can rebuild is the situation that produced the broken install.exe.
        builder = os.path.join(PROJECT_DIR, "scripts", "build-launchers.py")
        probe = subprocess.run([sys.executable, builder, "--check"], capture_output=True, text=True,
                               timeout=240)
        if "gcc and windres are needed" in probe.stdout:
            self.skipTest("no MinGW-w64 compiler on this machine")
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)


if __name__ == "__main__":
    unittest.main()
