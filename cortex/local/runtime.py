"""Find or install the ``llama-server`` runtime (llama.cpp).

Only the official ``ggml-org/llama.cpp`` GitHub releases are ever used. Prebuilt
binaries linked from model cards are not (one popular card tells you to use a fork),
and the winget package is not (it is the Vulkan build, a poor fit for an NVIDIA GPU).

Installing is a download, so it goes through ``store.confirm`` like a model pull: the
person sees the tag, every file with its size and (when GitHub publishes one) its
sha256, and where it will be unpacked, and says yes. Nothing runs from here
automatically - ``verify`` only runs ``llama-server --version`` after the files are in
place and unpacked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
import zipfile

from .. import proc
from ..profiles import CortexError
from . import hub, store

RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
SOURCE_PAGE = "https://github.com/ggml-org/llama.cpp/releases"
EXE = "llama-server.exe" if os.name == "nt" else "llama-server"

_LLAMA = re.compile(r"^llama-(?P<tag>[^-]+)-bin-win-(?P<backend>cuda-[\d.]+|vulkan|cpu)-x64\.zip$")
_CUDART = re.compile(r"^cudart-llama-bin-win-(?P<backend>cuda-[\d.]+)-x64\.zip$")


class RuntimeInstallError(CortexError):
    pass


def managed_dir():
    return os.path.join(store.home(), "runtime")


def find(cfg=None):
    """Path to a usable ``llama-server`` or None. Order: configured, managed, PATH."""
    cfg = cfg or store.load()[0]
    configured = (cfg.get("runtime") or {}).get("path")
    if configured and os.path.isfile(configured):
        return configured
    root = managed_dir()
    if os.path.isdir(root):
        for tag in sorted(os.listdir(root), reverse=True):
            candidate = os.path.join(root, tag, EXE)
            if os.path.isfile(candidate):
                return candidate
            found = _locate(os.path.join(root, tag))
            if found:
                return found
    found = shutil.which("llama-server")
    return found if found and os.path.isfile(found) else None


def verify(path):
    """``(ok, first_line)`` from ``llama-server --version``; never raises."""
    try:
        result = proc.run([path, "--version"], timeout=30)
    except Exception as exc:                       # missing DLL, bad arch, timeout...
        return False, f"could not run it: {exc}"
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    first = text.splitlines()[0] if text else ""
    return result.returncode == 0, first or f"exit code {result.returncode}"


# ------------------------------------------------------------------------- releases

def _cuda_key(backend):
    return tuple(int(p) for p in backend.split("-", 1)[1].split(".") if p.isdigit())


def releases(opener=None):
    req = urllib.request.Request(RELEASES_URL, headers={"User-Agent": hub.USER_AGENT,
                                                       "Accept": "application/vnd.github+json"})
    try:
        with (opener or hub.default_opener()).open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeInstallError(f"could not read the llama.cpp release list ({exc})") from None
    return [r for r in data if isinstance(r, dict) and not r.get("draft")]


def _is_nvidia(gpu):
    name = gpu["name"].lower()
    return any(word in name for word in ("nvidia", "geforce", "rtx", "gtx", "quadro"))


def choose_assets(release, hw, backend=None):
    """Pick the zip(s) for this machine from one release.

    Returns ``(assets, backend)``. NVIDIA GPU -> newest CUDA build plus its runtime
    DLL zip; otherwise Vulkan if any GPU, else CPU. ``backend`` forces a choice
    (``cuda-12.4`` etc.). Raises RuntimeInstallError when nothing matches.
    """
    by_name = {a.get("name"): a for a in release.get("assets", []) if isinstance(a, dict)}
    llamas = {m.group("backend"): by_name[n] for n in by_name if (m := _LLAMA.match(n or ""))}
    cudarts = {m.group("backend"): by_name[n] for n in by_name if (m := _CUDART.match(n or ""))}
    if not llamas:
        raise RuntimeInstallError(
            f"release {release.get('tag_name')} has no Windows build; install llama.cpp yourself "
            f"and set it with: cc local runtime --path <llama-server>")

    if not backend:
        gpus = hw.get("gpus") or []
        if any(_is_nvidia(g) for g in gpus):
            cuda = sorted((b for b in llamas if b.startswith("cuda-")), key=_cuda_key, reverse=True)
            backend = cuda[0] if cuda else ("vulkan" if "vulkan" in llamas else "cpu")
        else:
            backend = "vulkan" if gpus and "vulkan" in llamas else "cpu"
    if backend not in llamas:
        raise RuntimeInstallError(f"backend '{backend}' is not in release {release.get('tag_name')}; "
                                  f"available: {', '.join(sorted(llamas))}")
    chosen = [llamas[backend]]
    if backend.startswith("cuda-") and backend in cudarts:
        chosen.append(cudarts[backend])
    return chosen, backend


def _digest(asset):
    value = asset.get("digest") or ""
    return value.split(":", 1)[1].lower() if value.startswith("sha256:") else None


def unpack(zip_path, dest_dir):
    """Extract a zip into ``dest_dir`` refusing any member that would escape it."""
    base = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = os.path.abspath(os.path.join(base, member.filename))
            if os.path.commonpath([base, target]) != base:
                raise RuntimeInstallError(f"refusing zip member outside the install folder: "
                                          f"{member.filename!r}")
        zf.extractall(base)


def _locate(root):
    for base, _dirs, files in os.walk(root):
        if EXE in files:
            return os.path.join(base, EXE)
    return None


def install(hw, assume_yes=False, backend=None, opener=None, progress=None, out=None):
    """Download, verify and unpack llama.cpp after consent. Returns the exe path or None."""
    if os.name != "nt":
        raise RuntimeInstallError(
            "automatic runtime install is Windows-only. Install llama.cpp with your package "
            f"manager or from {SOURCE_PAGE} and run: cc local runtime --path <llama-server>")
    release = next((r for r in releases(opener) if r.get("assets")), None)
    if not release:
        raise RuntimeInstallError("no llama.cpp release with downloadable files was found")
    assets, backend = choose_assets(release, hw, backend)
    tag = release.get("tag_name", "unknown")
    dest_dir = os.path.join(managed_dir(), re.sub(r"[^A-Za-z0-9._-]", "_", tag))

    facts = [f"Source:      {SOURCE_PAGE} (official ggml-org/llama.cpp), release {tag}"
             + (" (marked pre-release)" if release.get("prerelease") else ""),
             f"Backend:     {backend}", f"Install to:  {dest_dir}"]
    total = 0
    for asset in assets:
        total += int(asset.get("size") or 0)
        digest = _digest(asset)
        shown = f"sha256 {digest[:16]}..." if digest else "sha256 not published by GitHub (size check only)"
        facts.append(f"File:        {asset['name']}  {int(asset.get('size') or 0) / 1e6:.0f} MB  {shown}")
    facts.append(f"Total:       {total / 1e6:.0f} MB. Nothing is run until it is unpacked and "
                 f"`--version` is checked.")
    if not store.confirm("Download and unpack this runtime?", facts, assume_yes=assume_yes, out=out):
        return None

    os.makedirs(dest_dir, exist_ok=True)
    for asset in assets:
        zpath = os.path.join(dest_dir, asset["name"])
        hub.fetch(asset["browser_download_url"], zpath, int(asset.get("size") or 0), _digest(asset),
                  opener=opener, progress=progress, auth=False, label=asset["name"])
        unpack(zpath, dest_dir)
        os.unlink(zpath)

    exe = _locate(dest_dir)
    if not exe:
        raise RuntimeInstallError(f"{EXE} was not found in the unpacked release; see {dest_dir}")
    store.update(lambda c: c["runtime"].update({"kind": "managed", "tag": tag, "backend": backend,
                                                "path": exe}))
    return exe
