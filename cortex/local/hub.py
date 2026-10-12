"""Hugging Face access: search, file listing and a resumable, verified download.

Nothing here decides *whether* to download - that is the caller's job, behind
``store.confirm``. This module only knows how, and is careful about three things:

* Only ``.gguf`` files are ever fetched. A model repo can hold pickles and scripts;
  the allowlist is by extension, not by trust in the publisher.
* A token (``HF_TOKEN``) is sent to the HF host only. ``urllib`` forwards the
  Authorization header across redirects, and HF redirects file downloads to a CDN,
  so a naive client leaks the token to a third party. :class:`_StripAuthOnHostChange`
  drops it.
* A finished file is accepted only if its size and sha256 match what the listing
  said. A partial download resumes with a Range request; a mismatch deletes the
  partial and fails loudly rather than leaving a corrupt model that later "loads".

All network access goes through an *opener* argument so tests can inject a fake.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from ..profiles import CortexError

DEFAULT_ENDPOINT = "https://huggingface.co"
USER_AGENT = "claude-cortex-local/1"
CHUNK = 1024 * 1024
_PART = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_QUANT = re.compile(r"((?:UD-)?(?:IQ|Q)\d(?:_[A-Z0-9]+)*|MXFP4(?:_MOE)?|BF16|F16|F32)", re.I)


class HubError(CortexError):
    pass


class _StripAuthOnHostChange(urllib.request.HTTPRedirectHandler):
    """Follow redirects but never carry the Authorization header to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            for name in list(new.headers):
                if name.lower() == "authorization":
                    del new.headers[name]
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def default_opener():
    return urllib.request.build_opener(_StripAuthOnHostChange())


def _headers(extra=None, auth=True):
    """Request headers. ``auth=False`` for any host that is not Hugging Face."""
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token and auth:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return headers


def validate_repo(repo):
    if not isinstance(repo, str) or not _REPO.match(repo) or ".." in repo:
        raise HubError(f"'{repo}' is not a Hugging Face repo id (expected owner/name)")
    return repo


def _get_json(url, opener, timeout=30):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with (opener or default_opener()).open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HubError(f"{url} requires authentication (gated or private repo). Accept its "
                           f"licence on huggingface.co and set HF_TOKEN yourself; Cortex never "
                           f"asks for or stores a token.") from None
        if exc.code == 404:
            raise HubError(f"not found on Hugging Face: {url}") from None
        raise HubError(f"Hugging Face returned HTTP {exc.code} for {url}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HubError(f"could not reach Hugging Face ({exc})") from None


# --------------------------------------------------------------------------- search

def search(query, limit=10, endpoint=DEFAULT_ENDPOINT, opener=None, publishers=()):
    """Search GGUF repos. Returns dicts: id, downloads, likes, gated, trusted.

    ``filter=gguf`` is the working filter; ``library=gguf`` is silently ignored by
    the API (verified) and would return everything.
    """
    params = urllib.parse.urlencode({"search": query, "filter": "gguf", "sort": "downloads",
                                     "direction": "-1", "limit": max(1, min(int(limit), 50))})
    data = _get_json(f"{endpoint}/api/models?{params}", opener)
    trusted = {p.lower() for p in publishers}
    out = []
    for item in data if isinstance(data, list) else []:
        repo = item.get("id") or item.get("modelId") or ""
        if not _REPO.match(repo):
            continue
        out.append({"id": repo, "downloads": item.get("downloads", 0), "likes": item.get("likes", 0),
                    "gated": bool(item.get("gated")),
                    "trusted": repo.split("/")[0].lower() in trusted})
    return out


# ---------------------------------------------------------------------------- files

def quant_of(filename):
    match = _QUANT.search(os.path.basename(filename))
    return match.group(1).upper() if match else None


def list_files(repo, endpoint=DEFAULT_ENDPOINT, opener=None):
    """GGUF files in ``repo`` as dicts: path, size, sha256, quant, part (n, total) or None, kind.

    ``mmproj`` files (vision projectors) get ``kind == "mmproj"`` so a caller never
    mistakes one for the model.
    """
    validate_repo(repo)
    data = _get_json(f"{endpoint}/api/models/{repo}/tree/main?recursive=true", opener)
    files = []
    for item in data if isinstance(data, list) else []:
        path = item.get("path", "")
        if item.get("type") != "file" or not path.lower().endswith(".gguf"):
            continue
        lfs = item.get("lfs") or {}
        part = _PART.search(path)
        files.append({
            "path": path, "size": int(lfs.get("size") or item.get("size") or 0),
            "sha256": (lfs.get("oid") or "").lower() or None, "quant": quant_of(path),
            "part": (int(part.group(1)), int(part.group(2))) if part else None,
            "kind": "mmproj" if "mmproj" in os.path.basename(path).lower() else "model",
        })
    return files


def select(files, quant=None, filename=None):
    """Pick the file set for one model: a single file, or every shard of a split one.

    Returns a list ordered by shard. Raises HubError if the choice is ambiguous or
    incomplete rather than guessing.
    """
    models = [f for f in files if f["kind"] == "model"]
    if filename:
        base = os.path.basename(filename)
        models = [f for f in models if f["path"] == filename or os.path.basename(f["path"]) == base]
        if not models:
            raise HubError(f"'{filename}' is not a .gguf file in this repo")
    elif quant:
        models = [f for f in models if (f["quant"] or "") == quant.upper()]
        if not models:
            raise HubError(f"no {quant} file in this repo")
    if not models:
        raise HubError("this repo has no .gguf model files")

    groups = {}
    for f in models:
        key = _PART.sub(".gguf", f["path"]) if f["part"] else f["path"]
        groups.setdefault(key, []).append(f)
    if len(groups) > 1:
        raise HubError(f"more than one file matches ({', '.join(sorted(groups)[:6])}); "
                       f"pick one with --file or --quant")
    group = sorted(next(iter(groups.values())), key=lambda f: f["part"] or (0, 0))
    total = group[0]["part"][1] if group[0]["part"] else 1
    if len(group) != total:
        raise HubError(f"incomplete split model: found {len(group)} of {total} shards")
    return group


def safe_dest(root, repo, path):
    """Destination path for a file, guaranteed to stay inside the repo's folder under ``root``.

    ``path`` comes from the network, so ``..`` and absolute paths are refused; the
    result is also checked after normalisation, not by string matching alone.
    """
    base = os.path.abspath(os.path.join(root, validate_repo(repo).replace("/", "__")))
    parts = path.replace("\\", "/").split("/")
    # A leading separator is refused too: os.path.isabs("/x") is False on Windows (no
    # drive), and a network-supplied path has no business starting at a root.
    if os.path.isabs(path) or path[:1] in ("/", "\\") or ".." in parts or ":" in parts[0]:
        raise HubError(f"refusing unsafe file path from the network: {path!r}")
    dest = os.path.abspath(os.path.join(base, *parts))
    if os.path.commonpath([base, dest]) != base:
        raise HubError(f"refusing unsafe file path from the network: {path!r}")
    return dest


# -------------------------------------------------------------------------- download

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def download(repo, entry, dest, endpoint=DEFAULT_ENDPOINT, opener=None, progress=None):
    """Fetch one GGUF from a repo to ``dest``. See :func:`fetch` for the guarantees."""
    validate_repo(repo)
    if not entry["path"].lower().endswith(".gguf"):
        raise HubError(f"refusing to download a non-GGUF file: {entry['path']}")
    url = f"{endpoint}/{repo}/resolve/main/{urllib.parse.quote(entry['path'])}"
    return fetch(url, dest, entry["size"], entry.get("sha256"), opener=opener,
                 progress=progress, auth=True, label=entry["path"])


def fetch(url, dest, want, sha256=None, opener=None, progress=None, auth=False, label=None):
    """Fetch ``url`` to ``dest`` (resuming ``dest + '.part'``), verify, and rename.

    ``want`` is the expected byte size (0 = unknown) and ``sha256`` the expected hash
    (None = unknown). Returns the final path. Raises HubError on any size or hash
    mismatch, after deleting a corrupt partial file. ``auth`` sends the HF token and
    must be True only for Hugging Face URLs.
    """
    label = label or url
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if want and have > want:
        os.unlink(part)
        have = 0

    req = urllib.request.Request(url, headers=_headers({"Range": f"bytes={have}-"} if have else None,
                                                       auth=auth))
    try:
        with (opener or default_opener()).open(req, timeout=60) as resp:
            if have and getattr(resp, "status", 200) != 206:
                have = 0                      # server ignored Range: start over, never append
            with open(part, "ab" if have else "wb") as out:
                done = have
                while True:
                    block = resp.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if progress:
                        progress(done, want)
    except urllib.error.HTTPError as exc:
        raise HubError(f"download failed: HTTP {exc.code} for {label}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise HubError(f"download interrupted ({exc}); re-run the same command to resume") from None

    size = os.path.getsize(part)
    if want and size != want:
        if size > want:
            os.unlink(part)
        raise HubError(f"size mismatch for {label}: got {size}, expected {want}"
                       + ("" if size > want else "; re-run to resume"))
    if sha256:
        actual = sha256_file(part)
        if actual != sha256.lower():
            os.unlink(part)
            raise HubError(f"sha256 mismatch for {label} (got {actual[:12]}..., expected "
                           f"{sha256[:12]}...); the partial file was deleted")
    os.replace(part, dest)
    return dest
