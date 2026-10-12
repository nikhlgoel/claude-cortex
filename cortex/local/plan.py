"""Hardware detection and a memory-fit pre-flight for local models.

This answers one question honestly: *can this model plausibly run here, and what
would the person have to free up if not?* It deliberately does NOT compute GPU/CPU
placement - llama.cpp's own ``--fit`` does that, given an explicit ``-c``. Every
constant below is an estimate and every message built from one says so. Speed is not
estimated at all: tokens/second on a given machine is unmeasured until it is measured
(``cc local doctor --bench``), and guessing it would be exactly the kind of invented
number this project exists to avoid.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .. import proc

GIB = 1024 ** 3

#: Free system RAM to leave for the OS and the person's other programs (GiB).
OS_HEADROOM_GB = 2.0
#: Compute buffers / CUDA context overhead on the GPU (GiB). Estimate.
GPU_OVERHEAD_GB = 0.7
#: KV-cache bytes per token ~ this * parameter count in billions (f16). Estimate for a
#: typical GQA decoder; q8_0 stores about 0.53x of that.
KV_BYTES_PER_TOKEN_PER_B = 14_000
KV_FLOOR_BYTES_PER_TOKEN = 40_000
Q8_KV_RATIO = 0.53


# ------------------------------------------------------------------------ hardware

def _ram_windows():
    import ctypes

    class MemStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                    ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong)]

    status = MemStatus()
    status.length = ctypes.sizeof(MemStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.total / GIB, status.avail / GIB


def _ram_posix():
    try:
        info = {}
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0]) * 1024
        return info["MemTotal"] / GIB, info.get("MemAvailable", info["MemFree"]) / GIB
    except (OSError, KeyError, ValueError, IndexError):
        return None


def ram_gb():
    """``(total, available)`` system RAM in GiB, or None when it cannot be read."""
    try:
        return _ram_windows() if os.name == "nt" else _ram_posix()
    except (OSError, AttributeError, ValueError):
        return None


def gpus(runner=proc.run):
    """NVIDIA GPUs as dicts (name, total_gb, free_gb); empty when none/undetectable.

    Only NVIDIA is probed. Other vendors are reported as "unknown" by the caller,
    never assumed to have or lack a GPU.
    """
    try:
        result = runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                         "--format=csv,noheader,nounits"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    found = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            try:
                found.append({"name": parts[0], "total_gb": float(parts[1]) / 1024,
                              "free_gb": float(parts[2]) / 1024})
            except ValueError:
                continue
    return found


def disks():
    """Free GiB per fixed local drive (Windows) or for ``/`` (elsewhere)."""
    roots = [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(f"{c}:\\")] \
        if os.name == "nt" else ["/"]
    out = {}
    for root in roots:
        try:
            out[root] = shutil.disk_usage(root).free / GIB
        except OSError:
            continue
    return out


def detect(runner=proc.run):
    ram = ram_gb()
    return {"ram_total_gb": ram[0] if ram else None, "ram_free_gb": ram[1] if ram else None,
            "gpus": gpus(runner), "disks": disks()}


# --------------------------------------------------------------------------- sizing

def kv_gb(params_b, ctx, quantised=True):
    per_token = max(KV_FLOOR_BYTES_PER_TOKEN, params_b * KV_BYTES_PER_TOKEN_PER_B)
    if quantised:
        per_token *= Q8_KV_RATIO
    return per_token * ctx / GIB


def fit(entry, weights_gb, hw, ctx=None):
    """Feasibility of one model on ``hw``. Returns a dict with ``verdict`` and reasons.

    verdict: ``"gpu"`` (fits in VRAM), ``"split"`` (needs system RAM too),
    ``"no"`` (does not fit), ``"unknown"`` (hardware could not be read).
    ``entry`` supplies ``params_b``, ``moe`` and ``ctx``; ``weights_gb`` should be the
    real file size when known, else the catalog's approximate size.
    """
    ctx = ctx or entry["ctx"][0]
    # KV-cache size follows layers x KV heads, not total parameters; for a MoE model the
    # active-parameter count is the better proxy (still an estimate).
    kv = kv_gb(entry.get("active_b") or entry["params_b"], ctx)
    notes = []
    free_ram = hw.get("ram_free_gb")
    gpu = max(hw.get("gpus") or [], key=lambda g: g["total_gb"], default=None)

    if free_ram is None:
        return {"verdict": "unknown", "ctx": ctx, "kv_gb": kv, "weights_gb": weights_gb,
                "notes": ["could not read free RAM; nothing assumed"]}

    vram = gpu["total_gb"] if gpu else 0.0
    need_vram_all = weights_gb + kv + GPU_OVERHEAD_GB
    if gpu and need_vram_all <= vram:
        return {"verdict": "gpu", "ctx": ctx, "kv_gb": kv, "weights_gb": weights_gb,
                "vram_gb": need_vram_all, "ram_gb": 0.5,
                "notes": [f"whole model + {ctx}-token cache ~{need_vram_all:.1f} GiB of "
                          f"{vram:.1f} GiB VRAM (estimate)"]}

    # Spill. MoE keeps the always-used layers and the cache on the GPU and the experts
    # in RAM, so only ~15% of the weights need VRAM. Dense layers split by fraction.
    if entry["moe"]:
        gpu_part = weights_gb * 0.15 + kv + GPU_OVERHEAD_GB
        ram_part = weights_gb * 0.85
        notes.append("MoE: expert weights stay in system RAM (--cpu-moe), attention + cache on the GPU")
    else:
        on_gpu = max(0.0, vram - kv - GPU_OVERHEAD_GB) if gpu else 0.0
        gpu_part = on_gpu + kv + GPU_OVERHEAD_GB if gpu else 0.0
        ram_part = max(0.0, weights_gb - on_gpu) + (0 if gpu else kv)
        notes.append("dense model: layers that do not fit in VRAM run on the CPU, which is much slower")

    if gpu and gpu_part > vram:
        notes.append(f"even the minimum GPU share (~{gpu_part:.1f} GiB) exceeds {vram:.1f} GiB VRAM; "
                     f"lower the context")
        return {"verdict": "no", "ctx": ctx, "kv_gb": kv, "weights_gb": weights_gb,
                "vram_gb": gpu_part, "ram_gb": ram_part, "notes": notes}

    usable = free_ram - OS_HEADROOM_GB
    if ram_part > usable:
        notes.append(f"needs ~{ram_part:.1f} GiB free RAM but only ~{max(usable, 0):.1f} GiB is usable "
                     f"({free_ram:.1f} free minus {OS_HEADROOM_GB:.0f} for the system); "
                     f"close programs or pick a smaller model")
        return {"verdict": "no", "ctx": ctx, "kv_gb": kv, "weights_gb": weights_gb,
                "vram_gb": gpu_part, "ram_gb": ram_part, "notes": notes}

    notes.append(f"~{ram_part:.1f} GiB RAM + ~{gpu_part:.1f} GiB VRAM (estimates)")
    return {"verdict": "split", "ctx": ctx, "kv_gb": kv, "weights_gb": weights_gb,
            "vram_gb": gpu_part, "ram_gb": ram_part, "notes": notes}


def choose_data_dir(need_gb, disk_free, preferred=None):
    """Pick a drive root for model files; avoid the system drive when another has room.

    Returns ``(root, reason)`` or ``(None, reason)``. ``preferred`` is honoured when it
    has room. Requires the model plus 5 GiB of slack so a drive is never filled.
    """
    slack = need_gb + 5.0
    if preferred:
        drive = os.path.splitdrive(os.path.abspath(preferred))[0]
        root = (drive + os.sep) if drive else "/"
        free = disk_free.get(root, 0)
        if free >= slack:
            return preferred, f"configured location ({free:.0f} GiB free)"
        return None, f"the configured location has only {free:.0f} GiB free; need ~{slack:.0f}"
    system = (os.environ.get("SystemDrive", "C:") + "\\").upper() if os.name == "nt" else "/"
    roomy = sorted(((free, root) for root, free in disk_free.items() if free >= slack), reverse=True)
    others = [r for r in roomy if r[1].upper() != system]
    pick = (others or roomy or [None])[0]
    if not pick:
        return None, f"no drive has {slack:.0f} GiB free"
    free, root = pick
    why = f"{free:.0f} GiB free" + (" (system drive; no other drive had room)" if root.upper() == system else "")
    return root, why


# ---------------------------------------------------------------------- llama-server

def llama_args(model_path, entry, plan, port, alias, token_file, threads=None, parallel=1):
    """Argument list (after the executable) for ``llama-server``.

    Notes on choices, all from the verified research:
    * ``-c`` is always explicit: ``--fit`` only adjusts *unset* arguments and its
      default context floor is 4096, so leaving -c off silently gives a tiny window.
    * ``--api-key-file`` keeps the token out of the process list (a command-line
      ``--api-key`` is visible to every local process).
    * ``--host 127.0.0.1`` only. Never 0.0.0.0.
    * ``--context-shift`` stays off (the default): shifting would corrupt the prompt.
    * ``-np`` is explicit; the default is "auto".
    """
    args = ["-m", model_path, "--host", "127.0.0.1", "--port", str(port),
            # llama.cpp splits -c ACROSS the -np slots, so each slot would get ctx/np tokens:
            # scale it, or two slots at "16384" silently give each request only 8192.
            "--alias", alias, "-c", str(plan["ctx"] * parallel), "-np", str(parallel),
            "--jinja", "--api-key-file", token_file,
            "--cache-type-k", "q8_0", "--cache-type-v", "q8_0", "-fa", "on",
            "--reasoning-budget", "8192"]
    verdict = plan.get("verdict")
    if verdict == "gpu":
        args += ["-ngl", "all"]
    elif verdict == "split":
        if entry["moe"]:
            args += ["--cpu-moe", "-ngl", "all"]
        else:
            args += ["--fit", "on"]
    else:
        args += ["-ngl", "0"]
    if threads:
        args += ["-t", str(threads)]
    return args
