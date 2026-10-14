/*
 * Claude Cortex native launcher for Windows.
 *
 * One source, two programs, picked at compile time (see scripts/build-launchers.py):
 *
 *   -DCORTEX_INSTALLER   install.exe   runs   python install.py <args>
 *   -DCORTEX_SHIM        claude.exe    runs   python -m cortex <args>      (the "cc" entry point)
 *
 * Why a program at all, and why it is not a script that starts another script:
 *
 *   The first version of this file built a PowerShell command line with printf("%s") and a
 *   wide-character path. printf prints one character of a UTF-16 string, so PowerShell was told to
 *   run the program 'C'. Any design that pastes a path into a command line for a shell has that
 *   whole class of bug: spaces, quotes, ' & ( ) % ^ ! and non-ASCII letters are each special to
 *   some shell.
 *
 *   This launcher never involves a shell. It finds Python and starts it with CreateProcessW, building
 *   the command line by the documented Windows quoting rules (the inverse of CommandLineToArgvW), so
 *   every argument arrives byte for byte. It works the same whether it is double-clicked or started
 *   from cmd, PowerShell, Git Bash, WSL interop, a scheduled task or another program.
 *
 * It downloads nothing and installs nothing: if Python is missing it says how to get it.
 * Exit status is the child's exit status; 1 = this launcher could not start the job.
 *
 * Build: scripts/build-launchers.py (MinGW-w64 gcc, static, 64-bit).
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>
#include <wchar.h>

#if defined(CORTEX_INSTALLER) == defined(CORTEX_SHIM)
#error "define exactly one of CORTEX_INSTALLER or CORTEX_SHIM"
#endif

#define CMD_MAX 32767          /* the documented limit of CreateProcess's command line */
#define PATH_MAX_W 4096
#define MAX_CANDIDATES 24

/* ------------------------------------------------------------------ output ---------------- */

static void put(int to_stderr, const wchar_t *text) {
    HANDLE h = GetStdHandle(to_stderr ? STD_ERROR_HANDLE : STD_OUTPUT_HANDLE);
    DWORD mode, written;
    if (h == NULL || h == INVALID_HANDLE_VALUE) return;
    if (GetConsoleMode(h, &mode)) {
        WriteConsoleW(h, text, (DWORD)wcslen(text), &written, NULL);
    } else {                   /* a pipe or file: UTF-8 is what the other tools expect */
        char buf[8192];
        int n = WideCharToMultiByte(CP_UTF8, 0, text, -1, buf, (int)sizeof buf, NULL, NULL);
        if (n > 1) WriteFile(h, buf, (DWORD)(n - 1), &written, NULL);
    }
}

/* Print up to four pieces back to back, then a newline. */
static void say(int to_stderr, const wchar_t *a, const wchar_t *b, const wchar_t *c, const wchar_t *d) {
    if (a) put(to_stderr, a);
    if (b) put(to_stderr, b);
    if (c) put(to_stderr, c);
    if (d) put(to_stderr, d);
    put(to_stderr, L"\r\n");
}

/* ------------------------------------------------------------- command line building ------- */

typedef struct {
    wchar_t text[CMD_MAX + 1];
    size_t len;
    int overflow;
} Cmd;

static void cmd_put(Cmd *c, wchar_t ch) {
    if (c->len >= CMD_MAX) { c->overflow = 1; return; }
    c->text[c->len++] = ch;
    c->text[c->len] = 0;
}

static void cmd_bs(Cmd *c, size_t n) {
    while (n--) cmd_put(c, L'\\');
}

/* Append one argument, quoted so that CommandLineToArgvW / the C runtime give it back unchanged. */
static void cmd_arg(Cmd *c, const wchar_t *a) {
    const wchar_t *it;
    if (c->len) cmd_put(c, L' ');
    if (*a && !wcspbrk(a, L" \t\n\v\"")) {
        for (; *a; a++) cmd_put(c, *a);
        return;
    }
    cmd_put(c, L'"');
    for (it = a;; it++) {
        size_t backslashes = 0;
        while (*it == L'\\') { it++; backslashes++; }
        if (*it == 0) {                       /* trailing backslashes must not escape our closing quote */
            cmd_bs(c, backslashes * 2);
            break;
        } else if (*it == L'"') {             /* backslashes before a quote are doubled, then the quote escaped */
            cmd_bs(c, backslashes * 2 + 1);
            cmd_put(c, L'"');
        } else {
            cmd_bs(c, backslashes);
            cmd_put(c, *it);
        }
    }
    cmd_put(c, L'"');
}

/* --------------------------------------------------------------------- running ------------- */

/* Ctrl+C reaches the child and this process alike. The child decides what it means; this process
 * keeps waiting so the shell prompt does not come back while the child is still printing. */
static BOOL WINAPI ctrl_handler(DWORD type) {
    return type == CTRL_C_EVENT || type == CTRL_BREAK_EVENT;
}

/* Start `exe` with `cmd`, wait, and store its exit code. quiet = discard its output (used only to
 * test whether a Python works). Returns 1 if it ran to completion, 0 if it could not be started or
 * timed out. */
static int run(const wchar_t *exe, Cmd *cmd, int quiet, DWORD timeout_ms, DWORD *code) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    HANDLE nul = INVALID_HANDLE_VALUE;
    DWORD flags = 0, wait;
    int ok;

    if (cmd->overflow) return 0;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;

    if (quiet) {
        SECURITY_ATTRIBUTES sa;
        sa.nLength = sizeof sa;
        sa.lpSecurityDescriptor = NULL;
        sa.bInheritHandle = TRUE;
        nul = CreateFileW(L"NUL", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                          &sa, OPEN_EXISTING, 0, NULL);
        si.hStdInput = si.hStdOutput = si.hStdError = nul;
        flags = CREATE_NO_WINDOW;
    } else {
        /* Hand the real standard handles over explicitly. Without this a redirected stdin/stdout
         * (a pipe, a file) would be replaced by the console in the child. */
        si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
        si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
        if (si.hStdInput) SetHandleInformation(si.hStdInput, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        if (si.hStdOutput) SetHandleInformation(si.hStdOutput, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        if (si.hStdError) SetHandleInformation(si.hStdError, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    }

    ok = CreateProcessW(exe, cmd->text, NULL, NULL, TRUE, flags, NULL, NULL, &si, &pi);
    if (nul != INVALID_HANDLE_VALUE) CloseHandle(nul);
    if (!ok) return 0;

    wait = WaitForSingleObject(pi.hProcess, timeout_ms);
    if (wait != WAIT_OBJECT_0) {
        TerminateProcess(pi.hProcess, 1);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        return 0;
    }
    GetExitCodeProcess(pi.hProcess, code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 1;
}

/* ------------------------------------------------------------------ file helpers ----------- */

static int is_file(const wchar_t *path) {
    DWORD a = GetFileAttributesW(path);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

#ifdef CORTEX_SHIM
static int is_dir(const wchar_t *path) {
    DWORD a = GetFileAttributesW(path);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
#endif

/* dir + "\" + name into out; 0 if it does not fit. */
static int join(wchar_t *out, size_t cap, const wchar_t *dir, const wchar_t *name) {
    size_t d = wcslen(dir), n = wcslen(name);
    if (d + n + 2 > cap) return 0;
    wcscpy(out, dir);
    if (d && out[d - 1] != L'\\' && out[d - 1] != L'/') out[d++] = L'\\';
    wcscpy(out + d, name);
    return 1;
}

static int getenv_w(const wchar_t *name, wchar_t *out, DWORD cap) {
    DWORD n = GetEnvironmentVariableW(name, out, cap);
    return n > 0 && n < cap;
}

/* Directory holding this executable, without a trailing backslash. */
static int own_dir(wchar_t *dir, DWORD cap) {
    DWORD n = GetModuleFileNameW(NULL, dir, cap);
    wchar_t *slash;
    if (n == 0 || n >= cap) return 0;
    slash = wcsrchr(dir, L'\\');
    if (!slash) return 0;
    *slash = 0;
    return 1;
}

/* ------------------------------------------------------------------ finding Python --------- */

typedef struct {
    wchar_t exe[PATH_MAX_W];
    const wchar_t *pre;        /* L"-3" for the "py" launcher, else NULL */
} Python;

static int python_works(const wchar_t *exe, const wchar_t *pre) {
    /* A real one-liner, not just "does the file exist": the Microsoft Store "python.exe" on PATH
     * is a stub that only prints an advert. */
    Cmd c;
    DWORD code = 1;
    c.len = 0; c.overflow = 0; c.text[0] = 0;
    cmd_arg(&c, exe);
    if (pre) cmd_arg(&c, pre);
    cmd_arg(&c, L"-c");
    cmd_arg(&c, L"import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)");
    return run(exe, &c, 1, 30000, &code) && code == 0;
}

/* Look for name on PATH ourselves. SearchPathW would also look in the current directory, which
 * would let a python.exe dropped in a download folder run instead of the real one. */
static int on_path(const wchar_t *name, wchar_t *out, size_t cap) {
    static wchar_t path[32768];
    wchar_t *p, *next, dir[PATH_MAX_W];
    DWORD n = GetEnvironmentVariableW(L"PATH", path, 32768);
    if (n == 0 || n >= 32768) return 0;
    for (p = path; p && *p; p = next) {
        size_t len;
        next = wcschr(p, L';');
        len = next ? (size_t)(next - p) : wcslen(p);
        if (next) next++;
        if (len >= 2 && p[0] == L'"') { p++; len -= 2; }      /* PATH entries may be quoted */
        if (len == 0 || len >= PATH_MAX_W) continue;
        wcsncpy(dir, p, len);
        dir[len] = 0;
        if (join(out, cap, dir, name) && is_file(out)) return 1;
    }
    return 0;
}

typedef struct {
    wchar_t exe[PATH_MAX_W];
    int version;               /* 312 for Python312, so the newest sorts first */
} Found;

static void scan_for_pythons(const wchar_t *root, Found *list, int *count) {
    wchar_t pattern[PATH_MAX_W], exe[PATH_MAX_W], leaf[64];
    WIN32_FIND_DATAW fd;
    HANDLE h;
    if (!join(pattern, PATH_MAX_W, root, L"Python3*")) return;
    h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (*count >= MAX_CANDIDATES) break;
        if (!join(leaf, 64, fd.cFileName, L"python.exe")) continue;
        if (!join(exe, PATH_MAX_W, root, leaf) || !is_file(exe)) continue;
        wcscpy(list[*count].exe, exe);
        list[*count].version = _wtoi(fd.cFileName + 6);        /* after "Python" */
        (*count)++;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

static int by_version_desc(const void *a, const void *b) {
    return ((const Found *)b)->version - ((const Found *)a)->version;
}

/* Returns 1 and fills `py`, or 0 when nothing usable exists. A bad CORTEX_PYTHON is reported and
 * returns -1: the person named an interpreter on purpose, so quietly using another one would be
 * wrong. */
static int find_python(Python *py) {
    wchar_t buf[PATH_MAX_W];
    static Found found[MAX_CANDIDATES];
    int i, count = 0;
    const wchar_t *roots[4];
    wchar_t local[PATH_MAX_W], pf[PATH_MAX_W], pf86[PATH_MAX_W], drive[PATH_MAX_W];
    wchar_t programs[PATH_MAX_W];

    if (getenv_w(L"CORTEX_PYTHON", buf, PATH_MAX_W)) {
        wchar_t resolved[PATH_MAX_W];
        const wchar_t *use = buf;
        if (!wcschr(buf, L'\\') && !wcschr(buf, L'/') && !wcschr(buf, L':')) {
            wchar_t named[PATH_MAX_W];
            wcscpy(named, buf);
            if (!wcschr(named, L'.')) wcscat(named, L".exe");
            if (on_path(named, resolved, PATH_MAX_W)) use = resolved;     /* a bare name like "python3.12" */
        }
        if (is_file(use) && python_works(use, NULL)) {
            wcscpy(py->exe, use);
            py->pre = NULL;
            return 1;
        }
        return -1;
    }

    /* The "py" launcher is the supported way to ask Windows for "a Python 3". */
    if (on_path(L"py.exe", buf, PATH_MAX_W) && python_works(buf, L"-3")) {
        wcscpy(py->exe, buf);
        py->pre = L"-3";
        return 1;
    }
    if (on_path(L"python.exe", buf, PATH_MAX_W) && python_works(buf, NULL)) {
        wcscpy(py->exe, buf);
        py->pre = NULL;
        return 1;
    }
    if (on_path(L"python3.exe", buf, PATH_MAX_W) && python_works(buf, NULL)) {
        wcscpy(py->exe, buf);
        py->pre = NULL;
        return 1;
    }

    /* Installed but never added to PATH (a very common state). Ask the usual install folders. */
    i = 0;
    if (getenv_w(L"LOCALAPPDATA", local, PATH_MAX_W) && join(programs, PATH_MAX_W, local, L"Programs\\Python"))
        roots[i++] = programs;
    if (getenv_w(L"ProgramFiles", pf, PATH_MAX_W)) roots[i++] = pf;
    if (getenv_w(L"ProgramFiles(x86)", pf86, PATH_MAX_W)) roots[i++] = pf86;
    if (getenv_w(L"SystemDrive", drive, PATH_MAX_W)) { wcscat(drive, L"\\"); roots[i++] = drive; }
    {
        int r;
        for (r = 0; r < i; r++) scan_for_pythons(roots[r], found, &count);
    }
    qsort(found, (size_t)count, sizeof(Found), by_version_desc);
    for (i = 0; i < count; i++) {
        if (python_works(found[i].exe, NULL)) {
            wcscpy(py->exe, found[i].exe);
            py->pre = NULL;
            return 1;
        }
    }
    return 0;
}

#ifdef CORTEX_INSTALLER
/* ------------------------------------------------------------- double-click behaviour ----- */

/* True when this process owns the console alone, which is what happens when Explorer starts it.
 * Then the window would vanish with the message in it, so we wait for Enter. From a terminal,
 * a script, a scheduled task or another program there are other processes on the console (or no
 * console at all) and we never wait. */
static int started_by_double_click(void) {
    DWORD pids[4], mode;
    wchar_t forced[8];
    if (getenv_w(L"CORTEX_LAUNCHER_PAUSE", forced, 8)) {       /* for tests and unusual hosts */
        if (!wcscmp(forced, L"always")) return 1;
        if (!wcscmp(forced, L"never")) return 0;
    }
    if (!GetConsoleMode(GetStdHandle(STD_INPUT_HANDLE), &mode)) return 0;
    return GetConsoleProcessList(pids, 4) == 1;
}

static int finish(int code) {
    if (started_by_double_click()) {
        wchar_t line[16];
        DWORD got;
        put(0, L"\r\nPress Enter to close this window...");
        ReadConsoleW(GetStdHandle(STD_INPUT_HANDLE), line, 15, &got, NULL);
    }
    return code;
}
#else
static int finish(int code) { return code; }
#endif

/* ------------------------------------------------------------------------ main ----------- */

int wmain(int argc, wchar_t **argv) {
    Python py;
    Cmd cmd;
    wchar_t dir[PATH_MAX_W];
#ifdef CORTEX_INSTALLER
    wchar_t target[PATH_MAX_W];
#endif
    DWORD code = 1;
    int i, found;

    SetConsoleCtrlHandler(ctrl_handler, TRUE);

    if (!own_dir(dir, PATH_MAX_W)) {
        say(1, L"error: cannot work out where this program is.", NULL, NULL, NULL);
        return finish(1);
    }

#ifdef CORTEX_INSTALLER
    if (!join(target, PATH_MAX_W, dir, L"install.py") || !is_file(target)) {
        say(1, L"error: install.py was not found next to install.exe.", NULL, NULL, NULL);
        say(1, L"       Looked in: ", dir, NULL, NULL);
        say(1, L"       Extract the whole download first (right-click the .zip > Extract All),", NULL, NULL, NULL);
        say(1, L"       then run install.exe from the extracted folder.", NULL, NULL, NULL);
        return finish(1);
    }
#else
    {
        /* Where the Cortex code is: CORTEX_HOME, the installed copy, then next to bin\. Same order
         * as claude.ps1 and the shell wrapper. */
        wchar_t home[PATH_MAX_W], probe[PATH_MAX_W];
        int have = 0;
        if (getenv_w(L"CORTEX_HOME", home, PATH_MAX_W) && join(probe, PATH_MAX_W, home, L"cortex") && is_dir(probe))
            have = 1;
        if (!have && getenv_w(L"USERPROFILE", home, PATH_MAX_W)) {
            wchar_t core[PATH_MAX_W];
            if (join(core, PATH_MAX_W, home, L".claude\\cortex-core") && join(probe, PATH_MAX_W, core, L"cortex")
                && is_dir(probe)) {
                wcscpy(home, core);
                have = 1;
            }
        }
        if (!have) {
            wchar_t parent[PATH_MAX_W];
            if (join(parent, PATH_MAX_W, dir, L"..") && join(probe, PATH_MAX_W, parent, L"cortex") && is_dir(probe)) {
                wcscpy(home, parent);
                have = 1;
            }
        }
        if (!have) {
            say(1, L"cc: the Cortex core was not found.", NULL, NULL, NULL);
            say(1, L"    Reinstall with install.exe (or install.cmd / install.ps1 / install.sh).", NULL, NULL, NULL);
            return 1;
        }
        SetEnvironmentVariableW(L"PYTHONPATH", home);
    }
#endif

    found = find_python(&py);
    if (found < 0) {
        wchar_t named[PATH_MAX_W];
        getenv_w(L"CORTEX_PYTHON", named, PATH_MAX_W);
        say(1, L"error: CORTEX_PYTHON='", named, L"' is not a working Python 3.8+.", NULL);
        return finish(1);
    }
    if (!found) {
        say(1, L"error: Python 3.8 or newer is required and was not found.", NULL, NULL, NULL);
        say(1, L"       Install it from https://www.python.org/downloads/ (tick 'Add to PATH'),", NULL, NULL, NULL);
        say(1, L"       or set CORTEX_PYTHON to the interpreter you want.", NULL, NULL, NULL);
        return finish(1);
    }

    cmd.len = 0; cmd.overflow = 0; cmd.text[0] = 0;
    cmd_arg(&cmd, py.exe);
    if (py.pre) cmd_arg(&cmd, py.pre);
#ifdef CORTEX_INSTALLER
    cmd_arg(&cmd, target);
#else
    cmd_arg(&cmd, L"-m");
    cmd_arg(&cmd, L"cortex");
#endif
    for (i = 1; i < argc; i++) cmd_arg(&cmd, argv[i]);

    if (cmd.overflow) {
        say(1, L"error: the arguments are too long to pass on.", NULL, NULL, NULL);
        return finish(1);
    }
    if (!run(py.exe, &cmd, 0, INFINITE, &code)) {
        say(1, L"error: could not start ", py.exe, NULL, NULL);
        return finish(1);
    }
#ifdef CORTEX_INSTALLER
    if (code == 3) {
        say(0, L"", NULL, NULL, NULL);
        say(0, L"Stopped at the safety prompt. Nothing was changed.", NULL, NULL, NULL);
    } else if (code != 0) {
        say(0, L"", NULL, NULL, NULL);
        say(0, L"The installer did not finish. See the messages above.", NULL, NULL, NULL);
    }
#endif
    return finish((int)code);
}
