"""
Text handling for the palace: how words become index terms, and a few safety/size helpers.

Everything retrieval does rests on this module. Two rules shape it:

* **Index and query use the same analyzer.** A term stored under one spelling and searched
  under another is a silent miss, so there is exactly one ``terms()`` function, and the tests
  check the symmetry directly.
* **Code is not prose.** ``load_config``, ``loadConfig`` and ``src/cortex/paths.py`` should be
  findable by any of their parts *and* by the whole name, which a plain word splitter cannot do.
"""

from __future__ import annotations

import hashlib
import re

# Deliberately short. Dropping "use" or "get" would remove real signal in a code project.
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does done for from had has have how i if in
into is it its just may might my of on or our out over per so than that the their them then there
these they this those to too us via was we were what when where which who why will with would you
your about also any all etc not no yes
should instead please want use used uses using
""".split())

#: Bump when ``terms`` / ``stem`` change: stored indexes are then rebuilt (see write.reindex_all).
ANALYZER_VERSION = 3

# Query-time synonym groups. Applied when searching, never when indexing, so editing this list
# (or the per-project `alias` table) never requires rebuilding an index. Kept to general
# developer vocabulary: a project-specific synonym ("profile" = "account") belongs in that
# project's own alias table, because generic guesses there would mislead.
DEFAULT_ALIAS_GROUPS = (
    ("auth", "authentication", "authenticate", "login", "signin", "oauth", "credential"),
    ("db", "database", "sql", "sqlite", "postgres", "datastore"),
    ("config", "configuration", "settings", "setting"),
    ("error", "exception", "failure", "fail", "crash", "bug", "traceback"),
    ("test", "tests", "testing", "pytest", "unittest", "spec"),
    ("doc", "docs", "documentation", "readme", "docstring"),
    ("performance", "perf", "slow", "latency", "speed", "optimize", "optimization"),
    ("deploy", "deployment", "release", "publish", "ship"),
    ("delete", "remove", "drop", "erase"),
    ("install", "setup", "bootstrap"),
    ("cache", "caching", "memoize"),
    ("log", "logging", "logs"),
    ("security", "vulnerability", "vuln", "cve", "exploit"),
    ("dependency", "dependencies", "package", "library"),
)

_RAW = re.compile(r"[^\W_]+(?:_[^\W_]+)*", re.UNICODE)    # words, keeping snake_case together
_CAMEL_1 = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_2 = re.compile(r"([A-Z]{3,})([A-Z][a-z])")      # HTTPServer -> HTTP Server, but SQLite stays whole


def _stem_once(w):
    if len(w) <= 3 or not w.isalpha():
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("ing") and len(w) - 3 >= 4:           # "string" keeps its ing: base "str" is too short
        base = w[:-3]
        if base[-1] == base[-2] and base[-1] not in "aeiouls" and len(base) - 1 >= 4:
            base = base[:-1]            # stopping -> stop; but setting stays "sett", not "set"
        return base
    if w.endswith("ed") and len(w) - 2 >= 3:
        base = w[:-2]
        if len(base) - 1 >= 4 and base[-1] == base[-2] and base[-1] not in "aeiouls":
            base = base[:-1]                            # embedded -> embed
        return base
    if w.endswith("tion") and len(w) - 3 >= 5:           # injection -> inject, creation -> creat
        return w[:-3]
    if w.endswith("es") and len(w) > 4 and w[-3] in "sxz":
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    if w.endswith("e") and len(w) > 4:
        return w[:-1]                                   # cache/caching/cached -> cach
    return w


def stem(word):
    """A small, deterministic suffix stripper, applied until the word stops changing.

    Not linguistically perfect; *consistent* is the point. Applying it to a fixpoint is what
    makes ``settings`` and ``setting`` meet (a single pass left them one step apart, so a query
    for one silently missed the other).
    """
    w = word
    for _ in range(4):
        nxt = _stem_once(w)
        if nxt == w:
            break
        w = nxt
    return w


def _parts(raw):
    """Split one raw word (already free of separators other than ``_``) into lowercase parts."""
    spaced = _CAMEL_2.sub(r"\1 \2", _CAMEL_1.sub(r"\1 \2", raw))
    return [chunk.lower() for chunk in spaced.replace("_", " ").split()]


def terms(text, keep_stopwords=False):
    """The index/query terms of ``text``, in order, with duplicates kept (frequency matters).

    ``load_config`` yields ``load_config``, ``load``, ``config``; ``loadConfig`` yields
    ``loadconfig``, ``load``, ``config``; paths and dotted names split on their separators.
    """
    result = []
    for match in _RAW.finditer(text or ""):
        raw = match.group(0)
        parts = _parts(raw)
        if not parts:
            continue
        if len(parts) > 1:
            joined = "_".join(parts) if "_" in raw else "".join(parts)
            if len(joined) > 3:
                result.append(joined)
        for part in parts:
            if len(part) < 2 and not part.isdigit():
                continue                                # a lone letter is noise; a lone digit is a fact (pool 5 vs 8)
            if not keep_stopwords and part in STOPWORDS:
                continue
            result.append(stem(part))
    return result


def term_set(text):
    return set(terms(text))


def estimate_tokens(text):
    """A cheap token estimate (about four characters per token). It is an estimate, labelled as one."""
    return (len(text or "") + 3) // 4


def normalize_ws(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def content_hash(title, body):
    norm = normalize_ws(title).lower() + "\n" + normalize_ws(body).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


def bigrams(term_list):
    """Adjacent term pairs, in order. Two texts with the same words in a different order share few."""
    return set(zip(term_list, term_list[1:]))


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


# --------------------------------------------------------------------------- resolutions

def _truncate(text, limit):
    text = normalize_ws(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "), cut.rfind(" "))
    if boundary > limit * 0.5:
        cut = cut[:boundary]
    return cut.rstrip(" .,;:") + "..."


def make_headline(title, body=""):
    """The shortest form: enough to recognise the memory."""
    base = normalize_ws(title) or normalize_ws(body)
    return _truncate(base, 90)


def make_gist(body, title=""):
    """The middle form: the first sentence or two, deterministic, no model needed."""
    text = body or title
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)         # skip code blocks in a summary
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    first = paragraphs[0] if paragraphs else text
    sentences = re.split(r"(?<=[.!?])\s+", normalize_ws(first))
    gist = " ".join(sentences[:2])
    return _truncate(gist, 240)


# --------------------------------------------------------------------------- secrets

_SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("bearer", re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]{16,}")),
    ("assignment", re.compile(
        r"(?i)\b((?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\w*\s*[:=]\s*['\"]?)"
        r"([^\s'\"]{6,})")),
)


def scrub_secrets(text):
    """Replace credential-looking strings. Returns ``(clean_text, [kinds found])``.

    Memory persists and is later injected into prompts, so a pasted key must never be stored.
    This is pattern-based: it catches well-known formats, not every possible secret.
    """
    kinds = []
    clean = text or ""
    for kind, pattern in _SECRET_PATTERNS:
        if kind in ("bearer", "assignment"):
            def _sub(match, kind=kind):
                kinds.append(kind)
                return match.group(1) + "[REDACTED:%s]" % kind
            clean = pattern.sub(_sub, clean)
        else:
            clean, count = pattern.subn("[REDACTED:%s]" % kind, clean)
            if count:
                kinds.append(kind)
    return clean, sorted(set(kinds))


# --------------------------------------------------------------------------- paths in text

_PATH_LIKE = re.compile(r"(?<![\w/\\.])((?:[\w.\-]+[/\\])+[\w.\-]+\.[A-Za-z0-9]{1,6})(?![\w])")
_BARE_FILE = re.compile(
    r"(?<![\w/\\.])([\w\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|cs|cpp|c|h|md|json|toml|yaml|yml|sh|ps1|cmd|sql|html|css))\b")


def clean_path(path):
    """Forward slashes, no leading ``./``."""
    p = (path or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def paths_in(text):
    """File paths mentioned in ``text`` (relative or absolute), normalised to forward slashes."""
    found = []
    for pattern in (_PATH_LIKE, _BARE_FILE):
        for match in pattern.finditer(text or ""):
            p = clean_path(match.group(1))
            if p and p not in found:
                found.append(p)
    return found[:20]


# --------------------------------------------------------------------------- identifiers in text

_SYMBOL_TICKS = re.compile(r"`([A-Za-z_][A-Za-z0-9_\.]*)(?:\(\))?`")
_SYMBOL_WORD = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")


def identifier_candidates(body):
    """Things in ``body`` that look like code identifiers: backticked names, snake_case, camelCase.

    Only candidates: the caller checks them against the code graph before trusting any.
    """
    found = []
    for pattern in (_SYMBOL_TICKS, _SYMBOL_WORD):
        for m in pattern.finditer(body or ""):
            name = m.group(1).split(".")[-1]
            if len(name) >= 4 and name not in found:
                found.append(name)
    return found[:25]
