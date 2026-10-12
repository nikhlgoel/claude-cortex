#!/usr/bin/env python3
"""
Tests for the local-model integration (cortex/local, the gateway's local route).

Everything is fake: a fake Hugging Face opener, a fake llama-server (a real HTTP server
speaking enough of the Anthropic API), temp directories. No model, no network and no
download ever happens here - and the consent tests assert exactly that for the
paths that must never download.
"""

import hashlib
import http.client
import importlib.util
import io
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.dont_write_bytecode = True

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from cortex import launcher  # noqa: E402
from cortex import local  # noqa: E402
from cortex.local import (catalog, gateway_local, hub, plan, profile, runtime, serve,  # noqa: E402
                          shaping, store)
from cortex.profiles import CortexError  # noqa: E402


def load_module(relpath):
    path = os.path.join(PROJECT_DIR, relpath)
    spec = importlib.util.spec_from_file_location(
        os.path.basename(relpath).replace("-", "_").replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEVELS = store.DEFAULTS["reasoning"]["levels"]
TOOL_USE = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}


def tool_result(is_error=False, with_reminder=False):
    content = [{"type": "tool_result", "tool_use_id": "t1", "content": "out", "is_error": is_error}]
    if with_reminder:
        content.insert(0, {"type": "text", "text": "<system-reminder>note</system-reminder>"})
    return {"role": "user", "content": content}


class IsolatedHome(unittest.TestCase):
    """Point CORTEX_LOCAL_HOME at a temp dir and make sure we are not 'inside Claude Code'."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cortex-local-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        patcher = mock.patch.dict(os.environ, {"CORTEX_LOCAL_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("CLAUDECODE", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            os.environ.pop(name, None)


# =============================================================================
# shaping: the pure request fixes
# =============================================================================

class TestShaping(unittest.TestCase):
    def test_anthropic_only_fields_and_cache_control_are_removed_without_mutating_input(self):
        req = {"model": "m", "output_config": {"effort": "high"}, "context_management": {"edits": []},
               "system": [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}],
               "tools": [{"name": "Bash", "defer_loading": True, "strict": True, "input_schema": {}}],
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}]}
        before = json.dumps(req, sort_keys=True)
        out = shaping.strip_anthropic_fields(req)
        self.assertNotIn("output_config", out)
        self.assertNotIn("context_management", out)
        for word in ("cache_control", "defer_loading", "strict"):
            self.assertNotIn(word, json.dumps(out))
        self.assertEqual(json.dumps(req, sort_keys=True), before)

    def test_a_mid_conversation_system_message_is_folded_not_hoisted(self):
        """Hoisting changes the prompt prefix, so the server's prompt cache misses every turn."""
        messages = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "a"},
                    {"role": "system", "content": "reminder text"},
                    {"role": "user", "content": "second"}]
        out = shaping.fold_system_messages(messages)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])
        self.assertEqual(out[0], messages[0])                       # prefix untouched, byte for byte
        self.assertIn("reminder text", json.dumps(out[2]))

    def test_the_full_pipeline_leaves_no_system_role_message_for_the_template_to_reject(self):
        """Qwen3.5+ templates assert 'System message must be at the beginning'."""
        req = {"max_tokens": 4096, "messages": [{"role": "user", "content": "a"},
                                                {"role": "assistant", "content": "b"},
                                                {"role": "system", "content": "injected mid-way"},
                                                {"role": "user", "content": "c"}]}
        out, _info = shaping.shape_request(req, {"template": "qwen3"}, LEVELS)
        self.assertNotIn("system", [m["role"] for m in out["messages"]])
        self.assertIn("injected mid-way", json.dumps(out["messages"]))

    def test_trailing_system_text_is_not_lost(self):
        out = shaping.fold_system_messages([{"role": "user", "content": "q"},
                                            {"role": "system", "content": "late"}])
        self.assertIn("late", json.dumps(out))

    def test_tool_results_are_moved_ahead_of_text(self):
        out = shaping.reorder_tool_results([tool_result(with_reminder=True)])
        self.assertEqual([b["type"] for b in out[0]["content"]], ["tool_result", "text"])

    def test_already_ordered_messages_are_left_identical(self):
        msg = tool_result()
        self.assertIs(shaping.reorder_tool_results([msg])[0], msg)

    def test_turn_classification(self):
        self.assertEqual(shaping.classify_turn([{"role": "user", "content": "do it"}]), "start")
        self.assertEqual(shaping.classify_turn([TOOL_USE, tool_result()]), "cont")
        self.assertEqual(shaping.classify_turn([TOOL_USE, tool_result(is_error=True)]), "on_error")
        # a system reminder is not person-authored text
        self.assertEqual(shaping.classify_turn([TOOL_USE, tool_result(with_reminder=True)]), "cont")
        mixed = {"role": "user", "content": [{"type": "text", "text": "and also this"},
                                             tool_result()["content"][0]]}
        self.assertEqual(shaping.classify_turn([TOOL_USE, mixed]), "start")

    def test_effort_levels_map_to_the_budget_table(self):
        self.assertEqual(shaping.thinking_budget("low", "start", LEVELS, 8192), 0)
        self.assertEqual(shaping.thinking_budget("high", "start", LEVELS, 8192), 4096)
        self.assertEqual(shaping.thinking_budget("xhigh", "start", LEVELS, 16384), 8192)
        self.assertEqual(shaping.thinking_budget("max", "start", LEVELS, 32000), 16384)
        self.assertEqual(shaping.thinking_budget("xhigh", "on_error", LEVELS, 16384), 2048)
        self.assertEqual(shaping.thinking_budget("xhigh", "cont", LEVELS, 16384), 0)

    def test_the_budget_always_leaves_room_for_an_answer(self):
        self.assertEqual(shaping.thinking_budget("max", "start", LEVELS, 4096),
                         4096 - shaping.THINKING_HEADROOM)
        self.assertEqual(shaping.thinking_budget("max", "start", LEVELS, 1024), 0)

    def test_an_unknown_effort_means_no_thinking_not_an_upgrade(self):
        self.assertIsNone(shaping.normalise_effort("turbo"))
        self.assertEqual(shaping.thinking_budget(shaping.normalise_effort("turbo"), "start", LEVELS, 8192), 0)

    def test_ultracode_is_treated_as_the_highest_real_level_not_a_level_of_its_own(self):
        self.assertEqual(shaping.normalise_effort("ultracode"), "max")
        self.assertNotIn("ultracode", shaping.EFFORT_ORDER)

    def test_qwen_thinking_flag_is_sent_explicitly_even_when_off(self):
        """The server default is thinking ON, so an omitted flag silently turns it on at 'low'."""
        req = {"max_tokens": 4096, "messages": [{"role": "user", "content": "x"}]}
        low, _ = shaping.apply_reasoning(req, "low", LEVELS, "qwen3")
        self.assertIs(low["chat_template_kwargs"]["enable_thinking"], False)
        self.assertNotIn("thinking", low)
        high, info = shaping.apply_reasoning(req, "high", LEVELS, "qwen3")
        self.assertIs(high["chat_template_kwargs"]["enable_thinking"], True)
        self.assertEqual(high["thinking"], {"type": "enabled", "budget_tokens": info["budget"]})

    def test_a_non_thinking_model_never_gets_thinking_fields(self):
        req = {"max_tokens": 4096, "thinking": {"type": "adaptive"},
               "messages": [{"role": "user", "content": "x"}]}
        out, info = shaping.apply_reasoning(req, "max", LEVELS, "none")
        self.assertNotIn("thinking", out)
        self.assertNotIn("chat_template_kwargs", out)
        self.assertEqual(info["budget"], 0)

    def test_max_tokens_is_raised_so_thinking_cannot_eat_the_answer(self):
        out, info = shaping.apply_reasoning({"max_tokens": 1500, "messages": [{"role": "user", "content": "x"}]},
                                            "max", LEVELS, "always")
        self.assertGreater(info["budget"], 0)
        self.assertGreaterEqual(out["max_tokens"], info["budget"] + shaping.THINKING_HEADROOM)

    def test_client_temperature_is_overridden_by_the_models_set(self):
        entry = {"template": "qwen3", "sampling": {"think": {"temperature": 0.6, "top_k": 20},
                                                   "plain": {"temperature": 0.7}}}
        base = {"temperature": 1, "max_tokens": 8192, "output_config": {"effort": "high"},
                "messages": [{"role": "user", "content": "x"}]}
        thinking, _ = shaping.shape_request(base, entry, LEVELS)
        self.assertEqual(thinking["temperature"], 0.6)
        plain, _ = shaping.shape_request({**base, "output_config": {"effort": "low"}}, entry, LEVELS)
        self.assertEqual(plain["temperature"], 0.7)

    def test_overflow_is_recognised_and_rewritten_into_what_claude_code_compacts_on(self):
        text = '{"error":{"message":"request (9000 tokens) exceeds the available context size (4096 tokens)"}}'
        self.assertTrue(shaping.is_overflow(400, text))
        self.assertFalse(shaping.is_overflow(400, '{"error":{"message":"bad tool schema"}}'))
        self.assertFalse(shaping.is_overflow(200, text))
        err = shaping.overflow_error(16384)
        self.assertEqual(err["error"]["type"], "invalid_request_error")
        self.assertIn("Prompt is too long", err["error"]["message"])

    def test_token_estimate_never_undercounts_a_plain_prompt(self):
        req = {"messages": [{"role": "user", "content": "word " * 1000}]}
        self.assertGreaterEqual(shaping.estimate_tokens(req), 1000)


# =============================================================================
# store: config, token, and the consent gate
# =============================================================================

class TestStore(IsolatedHome):
    def test_defaults_are_valid(self):
        self.assertEqual(store.validate(store.DEFAULTS), [])

    def test_an_alias_that_looks_like_a_claude_model_is_rejected(self):
        for bad in ("claude-local", "Claude-x", "local[1m]", ""):
            cfg = json.loads(json.dumps(store.DEFAULTS))
            cfg["claude"]["alias"] = bad
            self.assertTrue(store.validate(cfg), bad)

    def test_ports_must_differ_and_be_unprivileged(self):
        cfg = json.loads(json.dumps(store.DEFAULTS))
        cfg["ports"] = {"server": 8180, "gateway": 8180}
        self.assertTrue(store.validate(cfg))
        cfg["ports"] = {"server": 80, "gateway": 8189}
        self.assertTrue(store.validate(cfg))

    def test_a_corrupt_config_is_left_untouched_and_the_writer_refuses(self):
        os.makedirs(self.home, exist_ok=True)
        with open(store.config_path(), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        with self.assertRaises(CortexError):
            store.update(lambda c: c.update({"active_model": "x"}))
        with open(store.config_path(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ not json")

    def test_a_newer_schema_is_not_overwritten(self):
        os.makedirs(self.home, exist_ok=True)
        with open(store.config_path(), "w", encoding="utf-8") as fh:
            json.dump({"schema": 99, "future": True}, fh)
        with self.assertRaises(CortexError):
            store.update(lambda c: c.update({"active_model": "x"}))
        with open(store.config_path(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"schema": 99, "future": True})

    def test_update_merges_into_defaults_and_persists(self):
        store.update(lambda c: c.update({"active_model": "m1"}))
        cfg, status = store.load()
        self.assertEqual(status, "parsed")
        self.assertEqual(cfg["active_model"], "m1")
        self.assertEqual(cfg["ports"]["server"], 8180)          # defaults still present

    def test_an_invalid_change_is_refused_and_not_written(self):
        with self.assertRaises(CortexError):
            store.update(lambda c: c["claude"].update({"alias": "claude-evil"}))
        self.assertFalse(os.path.exists(store.config_path()))

    def test_token_is_created_once_and_stable_until_rotated(self):
        first = store.token()
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(store.token(), first)
        self.assertNotEqual(store.token(rotate=True), first)

    def test_token_is_not_created_when_asked_not_to(self):
        self.assertEqual(store.token(create=False), "")
        self.assertFalse(os.path.exists(store.token_path()))


class TestConsentGate(IsolatedHome):
    def test_inside_a_claude_code_session_even_yes_is_refused(self):
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
            self.assertFalse(store.confirm("go?", ["fact"], assume_yes=True, out=io.StringIO()))

    def test_no_terminal_and_no_yes_is_refused(self):
        # input() is rigged to say "yes": only the terminal check can be what refuses. A bare
        # EOFError from input() under the test runner would otherwise pass this by accident.
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                mock.patch("builtins.input", return_value="y"):
            self.assertFalse(store.confirm("go?", ["fact"], out=io.StringIO()))

    def test_yes_is_honoured_outside_a_session_and_the_facts_are_still_shown(self):
        out = io.StringIO()
        self.assertTrue(store.confirm("go?", ["Source: example"], assume_yes=True, out=out))
        self.assertIn("Source: example", out.getvalue())

    def test_the_default_answer_is_no(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value=""):
            self.assertFalse(store.confirm("go?", [], out=io.StringIO()))

    def test_only_an_explicit_yes_counts(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            for answer, expected in (("y", True), ("YES", True), ("sure", False), ("n", False)):
                with mock.patch("builtins.input", return_value=answer):
                    self.assertEqual(store.confirm("go?", [], out=io.StringIO()), expected, answer)

    def test_eof_on_the_prompt_is_a_no(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(store.confirm("go?", [], out=io.StringIO()))


# =============================================================================
# hub: Hugging Face access with a fake opener
# =============================================================================

class FakeResp:
    def __init__(self, body, status=200, headers=None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Serves a body for any URL, honours Range, records every request."""

    def __init__(self, body=b"", honour_range=True, json_body=None, error=None):
        self.body, self.honour_range, self.json_body, self.error = body, honour_range, json_body, error
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self.error:
            raise self.error
        if self.json_body is not None:
            return FakeResp(json.dumps(self.json_body).encode("utf-8"))
        rng = req.get_header("Range")
        if rng and self.honour_range:
            start = int(rng.split("=")[1].split("-")[0])
            return FakeResp(self.body[start:], status=206)
        return FakeResp(self.body, status=200)


def tree_item(path, size=1000, sha="a" * 64):
    return {"type": "file", "path": path, "size": size, "lfs": {"oid": sha, "size": size}}


class TestHub(IsolatedHome):
    def test_search_uses_the_working_filter_and_flags_untrusted_publishers(self):
        opener = FakeOpener(json_body=[{"id": "unsloth/Qwen3.5-4B-GGUF", "downloads": 5, "likes": 1},
                                       {"id": "random/thing-GGUF", "downloads": 9, "gated": "manual"}])
        found = hub.search("qwen", opener=opener, publishers=("unsloth",))
        url = opener.requests[0].full_url
        self.assertIn("filter=gguf", url)
        self.assertNotIn("library=gguf", url)       # silently ignored by the API
        self.assertTrue(found[0]["trusted"])
        self.assertFalse(found[1]["trusted"])
        self.assertTrue(found[1]["gated"])

    def test_malformed_repo_ids_from_the_network_are_dropped(self):
        found = hub.search("x", opener=FakeOpener(json_body=[{"id": "../../etc/passwd"}, {"id": "a/b"}]))
        self.assertEqual([f["id"] for f in found], ["a/b"])

    def test_only_gguf_files_are_listed_and_mmproj_is_not_mistaken_for_the_model(self):
        opener = FakeOpener(json_body=[tree_item("m-Q4_K_M.gguf"), tree_item("model.safetensors"),
                                       tree_item("pickle.bin"), tree_item("mmproj-F16.gguf"),
                                       {"type": "directory", "path": "sub"}])
        files = hub.list_files("o/r", opener=opener)
        self.assertEqual(sorted(f["path"] for f in files), ["m-Q4_K_M.gguf", "mmproj-F16.gguf"])
        self.assertEqual([f["path"] for f in files if f["kind"] == "model"], ["m-Q4_K_M.gguf"])
        self.assertEqual(hub.select(files, quant="Q4_K_M")[0]["path"], "m-Q4_K_M.gguf")

    def test_a_split_model_selects_every_shard_in_order(self):
        opener = FakeOpener(json_body=[tree_item("big-Q4_K_M-00002-of-00002.gguf"),
                                       tree_item("big-Q4_K_M-00001-of-00002.gguf")])
        group = hub.select(hub.list_files("o/r", opener=opener), quant="Q4_K_M")
        self.assertEqual([f["part"] for f in group], [(1, 2), (2, 2)])

    def test_an_incomplete_split_is_refused(self):
        opener = FakeOpener(json_body=[tree_item("big-Q4_K_M-00001-of-00003.gguf")])
        with self.assertRaises(hub.HubError):
            hub.select(hub.list_files("o/r", opener=opener), quant="Q4_K_M")

    def test_an_ambiguous_choice_is_refused_rather_than_guessed(self):
        opener = FakeOpener(json_body=[tree_item("a-Q4_K_M.gguf"), tree_item("b-Q4_K_M.gguf")])
        with self.assertRaises(hub.HubError):
            hub.select(hub.list_files("o/r", opener=opener), quant="Q4_K_M")

    def test_repo_ids_are_validated(self):
        for bad in ("noslash", "../x/y", "a/b/c", "a b/c", ""):
            with self.assertRaises(hub.HubError, msg=bad):
                hub.validate_repo(bad)

    def test_a_path_from_the_network_cannot_escape_the_models_folder(self):
        root = os.path.join(self.home, "models")
        for bad in ("../evil.gguf", "a/../../evil.gguf", "/abs/evil.gguf", "C:/evil.gguf"):
            with self.assertRaises(hub.HubError, msg=bad):
                hub.safe_dest(root, "o/r", bad)
        self.assertTrue(hub.safe_dest(root, "o/r", "sub/ok.gguf").startswith(os.path.abspath(root)))

    def test_download_verifies_size_and_sha256_and_renames(self):
        body = b"model-bytes" * 300
        entry = {"path": "m.gguf", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        dest = os.path.join(self.home, "m.gguf")
        hub.download("o/r", entry, dest, opener=FakeOpener(body))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), body)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_a_wrong_hash_deletes_the_partial_and_installs_nothing(self):
        body = b"x" * 500
        entry = {"path": "m.gguf", "size": len(body), "sha256": "0" * 64}
        dest = os.path.join(self.home, "m.gguf")
        with self.assertRaises(hub.HubError):
            hub.download("o/r", entry, dest, opener=FakeOpener(body))
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_a_short_file_is_an_error_and_keeps_the_partial_for_resume(self):
        entry = {"path": "m.gguf", "size": 1000, "sha256": None}
        dest = os.path.join(self.home, "m.gguf")
        with self.assertRaises(hub.HubError):
            hub.download("o/r", entry, dest, opener=FakeOpener(b"y" * 400))
        self.assertTrue(os.path.exists(dest + ".part"))
        self.assertFalse(os.path.exists(dest))

    def test_a_partial_file_is_resumed_with_a_range_request(self):
        body = bytes(range(256)) * 20
        entry = {"path": "m.gguf", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        dest = os.path.join(self.home, "m.gguf")
        with open(dest + ".part", "wb") as fh:
            fh.write(body[:1000])
        opener = FakeOpener(body)
        hub.download("o/r", entry, dest, opener=opener)
        self.assertEqual(opener.requests[0].get_header("Range"), "bytes=1000-")
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), body)

    def test_a_server_that_ignores_range_restarts_instead_of_appending(self):
        body = b"abcdefghij" * 100
        entry = {"path": "m.gguf", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        dest = os.path.join(self.home, "m.gguf")
        with open(dest + ".part", "wb") as fh:
            fh.write(body[:300])
        hub.download("o/r", entry, dest, opener=FakeOpener(body, honour_range=False))
        with open(dest, "rb") as fh:
            self.assertEqual(fh.read(), body, "the resumed file was corrupted by appending a full body")

    def test_non_gguf_files_are_never_downloaded(self):
        opener = FakeOpener(b"x")
        with self.assertRaises(hub.HubError):
            hub.download("o/r", {"path": "evil.pkl", "size": 1, "sha256": None},
                         os.path.join(self.home, "evil.pkl"), opener=opener)
        self.assertEqual(opener.requests, [])

    def test_the_hf_token_goes_to_huggingface_requests_only(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "hf_secret"}):
            self.assertEqual(hub._headers()["Authorization"], "Bearer hf_secret")
            self.assertNotIn("Authorization", hub._headers(auth=False))
            body = b"z" * 10
            opener = FakeOpener(body)
            hub.fetch("https://github.com/x/y.zip", os.path.join(self.home, "y.zip"), len(body),
                      opener=opener, auth=False)
            self.assertIsNone(opener.requests[0].get_header("Authorization"))

    def test_the_token_is_dropped_when_a_redirect_leaves_the_host(self):
        handler = hub._StripAuthOnHostChange()
        req = urllib.request.Request("https://huggingface.co/o/r/resolve/main/m.gguf",
                                     headers={"Authorization": "Bearer hf_secret"})
        redirected = handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.net/blob")
        self.assertIsNotNone(redirected)
        self.assertNotIn("authorization", {k.lower() for k in redirected.headers})
        same_host = handler.redirect_request(req, None, 302, "Found", {}, "https://huggingface.co/other")
        self.assertIn("authorization", {k.lower() for k in same_host.headers})

    def test_gated_repos_get_a_clear_message_and_no_token_is_requested(self):
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))
        with self.assertRaises(hub.HubError) as ctx:
            hub.list_files("o/r", opener=FakeOpener(error=err))
        self.assertIn("never asks for or stores a token", str(ctx.exception))


# =============================================================================
# plan: fit estimates, disk choice, llama-server flags
# =============================================================================

def hardware(free_ram=8.0, vram=6.0):
    gpus = [{"name": "NVIDIA GeForce RTX 3050 Laptop GPU", "total_gb": vram,
             "free_gb": vram - 0.5}] if vram else []
    return {"ram_total_gb": 16.0, "ram_free_gb": free_ram, "gpus": gpus, "disks": {}}


class TestPlan(unittest.TestCase):
    def test_a_small_model_fits_entirely_in_vram(self):
        entry = catalog.get("qwen3.5-4b")
        self.assertEqual(plan.fit(entry, entry["approx_gb"], hardware())["verdict"], "gpu")

    def test_a_model_larger_than_vram_splits_into_ram_when_ram_allows(self):
        entry = catalog.get("qwen3.5-9b")
        self.assertEqual(plan.fit(entry, entry["approx_gb"], hardware(free_ram=8))["verdict"], "split")

    def test_a_model_that_needs_more_ram_than_is_free_is_refused_with_the_numbers(self):
        entry = catalog.get("qwen3.6-35b-a3b")
        result = plan.fit(entry, entry["approx_gb"], hardware(free_ram=3.2))
        self.assertEqual(result["verdict"], "no")
        self.assertIn("free RAM", " ".join(result["notes"]))

    def test_unreadable_ram_is_unknown_never_assumed_fine(self):
        hw = hardware()
        hw["ram_free_gb"] = None
        self.assertEqual(plan.fit(catalog.get("qwen3.5-9b"), 5.7, hw)["verdict"], "unknown")

    def test_moe_kv_cache_is_sized_from_active_parameters(self):
        moe = catalog.get("qwen3.6-35b-a3b")
        self.assertLess(plan.kv_gb(moe["active_b"], 16384), plan.kv_gb(moe["params_b"], 16384))

    def test_no_gpu_means_everything_comes_from_ram(self):
        entry = catalog.get("qwen3.5-4b")
        self.assertEqual(plan.fit(entry, entry["approx_gb"], hardware(free_ram=8, vram=0))["verdict"], "split")

    @unittest.skipUnless(os.name == "nt", "drive letters")
    def test_the_system_drive_is_avoided_when_another_has_room(self):
        with mock.patch.dict(os.environ, {"SystemDrive": "C:"}):
            root, _why = plan.choose_data_dir(3.0, {"C:\\": 500.0, "D:\\": 200.0})
            self.assertEqual(root, "D:\\")
            root, why = plan.choose_data_dir(3.0, {"C:\\": 500.0, "D:\\": 4.0})
            self.assertEqual(root, "C:\\")
            self.assertIn("system drive", why)

    def test_no_drive_with_room_is_a_refusal_not_a_guess(self):
        root, why = plan.choose_data_dir(50.0, {"/": 10.0, "C:\\": 10.0, "D:\\": 10.0})
        self.assertIsNone(root)
        self.assertIn("free", why)

    def test_llama_server_is_loopback_only_with_the_token_in_a_file(self):
        entry = catalog.get("qwen3.5-9b")
        args = plan.llama_args("m.gguf", entry, {"verdict": "split", "ctx": 16384}, 8180, "local-coder",
                               "tokenfile")
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertIn("--api-key-file", args)
        self.assertNotIn("--api-key", args)
        self.assertNotIn("0.0.0.0", args)
        self.assertEqual(args[args.index("-c") + 1], "16384")          # explicit: --fit would shrink it
        self.assertNotIn("--context-shift", args)

    def test_extra_slots_do_not_shrink_each_requests_context(self):
        """llama.cpp splits -c across -np slots; two slots at 16384 would leave 8192 each."""
        entry = catalog.get("qwen3.5-4b")
        one = plan.llama_args("m.gguf", entry, {"verdict": "gpu", "ctx": 16384}, 8180, "a", "t", parallel=1)
        two = plan.llama_args("m.gguf", entry, {"verdict": "gpu", "ctx": 16384}, 8180, "a", "t", parallel=2)
        self.assertEqual(one[one.index("-c") + 1], "16384")
        self.assertEqual(two[two.index("-c") + 1], str(16384 * 2))
        self.assertEqual(two[two.index("-np") + 1], "2")

    def test_the_default_is_one_slot_so_the_full_context_is_available(self):
        self.assertEqual(store.DEFAULTS["gateway"]["max_concurrent"], 1)

    def test_moe_spill_keeps_experts_on_the_cpu(self):
        entry = catalog.get("qwen3.6-35b-a3b")
        args = plan.llama_args("m.gguf", entry, {"verdict": "split", "ctx": 16384}, 8180, "a", "t")
        self.assertIn("--cpu-moe", args)


# =============================================================================
# runtime: asset choice and safe unpacking
# =============================================================================

def release(*names, tag="b9999"):
    return {"tag_name": tag, "assets": [{"name": n, "size": 1, "browser_download_url": f"https://x/{n}"}
                                        for n in names]}


ASSETS = ("llama-b9999-bin-win-cuda-12.4-x64.zip", "llama-b9999-bin-win-cuda-13.4-x64.zip",
          "cudart-llama-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip",
          "llama-b9999-bin-win-vulkan-x64.zip", "llama-b9999-bin-win-cpu-x64.zip")


class TestRuntime(IsolatedHome):
    def test_an_nvidia_gpu_gets_the_newest_cuda_build_and_its_runtime_dlls(self):
        assets, backend = runtime.choose_assets(release(*ASSETS), hardware())
        self.assertEqual(backend, "cuda-13.4")
        self.assertEqual(sorted(a["name"] for a in assets),
                         ["cudart-llama-bin-win-cuda-13.4-x64.zip", "llama-b9999-bin-win-cuda-13.4-x64.zip"])

    def test_a_forced_backend_is_respected(self):
        _assets, backend = runtime.choose_assets(release(*ASSETS), hardware(), backend="cuda-12.4")
        self.assertEqual(backend, "cuda-12.4")

    def test_no_nvidia_gpu_does_not_pick_cuda(self):
        hw = hardware(vram=0)
        self.assertEqual(runtime.choose_assets(release(*ASSETS), hw)[1], "cpu")
        hw["gpus"] = [{"name": "AMD Radeon", "total_gb": 8.0, "free_gb": 7.0}]
        self.assertEqual(runtime.choose_assets(release(*ASSETS), hw)[1], "vulkan")

    def test_an_unavailable_backend_is_an_error_naming_what_exists(self):
        with self.assertRaises(runtime.RuntimeInstallError) as ctx:
            runtime.choose_assets(release(*ASSETS), hardware(), backend="rocm")
        self.assertIn("cpu", str(ctx.exception))

    def test_a_release_without_windows_builds_is_explained(self):
        with self.assertRaises(runtime.RuntimeInstallError):
            runtime.choose_assets(release("llama-b9999-bin-ubuntu-x64.zip"), hardware())

    def test_a_zip_that_tries_to_escape_the_install_folder_is_refused(self):
        archive = os.path.join(self.home, "evil.zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.txt", "x")
        with self.assertRaises(runtime.RuntimeInstallError):
            runtime.unpack(archive, os.path.join(self.home, "out"))
        self.assertFalse(os.path.exists(os.path.join(self.home, "escaped.txt")))

    def test_a_normal_zip_unpacks(self):
        archive = os.path.join(self.home, "ok.zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("llama-server.exe", "x")
        runtime.unpack(archive, os.path.join(self.home, "out"))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "out", "llama-server.exe")))

    @unittest.skipUnless(os.name == "nt", "automatic runtime install is Windows-only")
    def test_the_runtime_install_is_refused_inside_a_claude_code_session(self):
        opener = FakeOpener(json_body=[{**release(*ASSETS), "draft": False}])
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}), \
                mock.patch.object(runtime.hub, "fetch") as fetch:
            result = runtime.install(hardware(), assume_yes=True, opener=opener, out=io.StringIO())
        self.assertIsNone(result)
        fetch.assert_not_called()


# =============================================================================
# serve: process safety
# =============================================================================

class TestServe(IsolatedHome):
    def test_a_recycled_pid_that_is_not_our_program_is_never_killed(self):
        serve._write_state("server", 4242, 8180, "m")
        with mock.patch.object(serve, "_image_name", return_value="notepad.exe"), \
                mock.patch.object(serve.proc, "kill_tree") as kill:
            self.assertFalse(serve.stop("server"))
        kill.assert_not_called()
        self.assertEqual(serve.read_state("server"), {})           # stale record is cleared

    def test_our_own_process_is_stopped(self):
        serve._write_state("server", 4242, 8180, "m")
        with mock.patch.object(serve, "_image_name", return_value="llama-server.exe"), \
                mock.patch.object(serve.proc, "kill_tree") as kill:
            self.assertTrue(serve.stop("server"))
        kill.assert_called_once()

    def test_starting_an_uninstalled_model_is_refused(self):
        cfg, _ = store.load()
        with self.assertRaises(serve.ServeError):
            serve.start_server(cfg, "nope")

    def _installed(self, model_id, size_bytes=1):
        cfg, _ = store.load()
        model = os.path.join(self.home, "m.gguf")
        with open(model, "wb") as fh:
            fh.write(b"x")
        cfg["models"][model_id] = {"files": [model], "size_bytes": size_bytes}
        return cfg

    def test_a_port_taken_by_another_program_is_not_clobbered(self):
        cfg = self._installed("m")
        with mock.patch.object(serve, "port_in_use", return_value=True), \
                mock.patch.object(serve.subprocess, "Popen") as popen:
            with self.assertRaises(serve.ServeError) as ctx:
                serve.start_server(cfg, "m")
        self.assertIn("already in use", str(ctx.exception))
        popen.assert_not_called()

    def test_a_model_that_does_not_fit_is_refused_before_anything_is_spawned(self):
        cfg = self._installed("qwen3.6-35b-a3b", int(13.2 * plan.GIB))
        with mock.patch.object(serve, "port_in_use", return_value=False), \
                mock.patch.object(serve.runtime, "find", return_value="llama-server"), \
                mock.patch.object(serve.subprocess, "Popen") as popen:
            with self.assertRaises(serve.ServeError) as ctx:
                serve.start_server(cfg, "qwen3.6-35b-a3b", hw=hardware(free_ram=3.2))
        self.assertIn("does not fit", str(ctx.exception))
        popen.assert_not_called()

    def test_an_unknown_gguf_is_treated_as_a_plain_non_thinking_model(self):
        cfg, _ = store.load()
        cfg["models"]["custom"] = {"size_bytes": 4 * plan.GIB}
        entry = serve.entry_for("custom", cfg)
        self.assertEqual(entry["template"], "none")
        self.assertEqual(entry["tier"], "custom")


# =============================================================================
# the gateway's local route, against a fake llama-server
# =============================================================================

class FakeLlama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "ok"
    seen = []
    disconnected = False

    def log_message(self, *args):
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLlama.seen.append((self.path, body, dict(self.headers)))
        mode = FakeLlama.mode
        if self.path.endswith("/count_tokens"):
            if mode == "no_count":
                return self._send_json(404, {"error": "nope"})
            return self._send_json(200, {"input_tokens": 42})
        if mode == "overflow":
            return self._send_json(400, {"error": {"message": "request exceeds the available context size"}})
        if mode == "slow_prefill":
            time.sleep(1.6)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b'event: message_start\ndata: {"type":"message_start"}\n\n')
        self.wfile.flush()
        if mode == "gap":
            time.sleep(1.5)
        if mode == "endless":
            try:
                for _ in range(400):
                    self.wfile.write(b'event: content_block_delta\ndata: {"type":"content_block_delta"}\n\n')
                    self.wfile.flush()
                    time.sleep(0.05)
            except OSError:
                FakeLlama.disconnected = True
                return
        self.wfile.write(b'event: message_stop\ndata: {"type":"message_stop"}\n\n')
        self.wfile.flush()


class TestLocalGateway(IsolatedHome):
    TOKEN = "tok-123"
    BODY = {"model": "local-coder", "max_tokens": 4096, "stream": True, "temperature": 1,
            "output_config": {"effort": "high"},
            "messages": [{"role": "user", "content": "hi"}]}

    @classmethod
    def setUpClass(cls):
        cls.gw = load_module("scripts/cortex-gateway.py")

    def setUp(self):
        super().setUp()
        FakeLlama.seen, FakeLlama.mode, FakeLlama.disconnected = [], "ok", False
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)

        cfg = json.loads(json.dumps(store.DEFAULTS))
        cfg["gateway"].update({"ping_after_s": 0.4, "ping_every_s": 0.4, "log_requests": False})
        route = gateway_local.LocalRoute(cfg, dict(catalog.get("qwen3.5-4b")), self.TOKEN,
                                         upstream_base=f"http://127.0.0.1:{self.upstream.server_address[1]}")
        route.n_ctx = 16384
        self.route = route
        self.gw.LOCAL = (route, "qwen3.5-4b")
        self.addCleanup(setattr, self.gw, "LOCAL", None)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.gw.CortexGatewayHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def post(self, path, payload, token="__default__", timeout=15):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        headers = {"Content-Type": "application/json"}
        token = self.TOKEN if token == "__default__" else token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", path, json.dumps(payload), headers)
        return conn, conn.getresponse()

    def test_requests_without_the_token_are_refused_before_the_body_is_read(self):
        for token in (None, "wrong", ""):
            conn, resp = self.post("/v1/messages", self.BODY, token=token)
            self.assertEqual(resp.status, 401, token)
            self.assertIn("authentication_error", resp.read().decode())
            conn.close()
        self.assertEqual(FakeLlama.seen, [], "an unauthenticated request reached the model")

    def test_the_token_is_accepted_as_a_bearer_or_an_api_key_header(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/v1/messages/count_tokens", json.dumps(self.BODY),
                     {"Content-Type": "application/json", "x-api-key": self.TOKEN})
        self.assertEqual(conn.getresponse().status, 200)

    def test_health_leaks_nothing_sensitive(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/health")
        text = conn.getresponse().read().decode()
        self.assertNotIn(self.TOKEN, text)
        self.assertNotIn(self.home, text)
        self.assertEqual(json.loads(text)["mode"], "local")

    def test_the_request_is_shaped_before_it_reaches_the_model(self):
        _conn, resp = self.post("/v1/messages", self.BODY)
        resp.read()
        _path, seen, headers = FakeLlama.seen[-1]
        self.assertNotIn("output_config", seen)
        self.assertEqual(seen["temperature"], 0.6)                 # the model's thinking set, not 1
        self.assertEqual(seen["thinking"]["type"], "enabled")
        self.assertEqual(headers.get("Authorization"), f"Bearer {self.TOKEN}")

    def test_the_stream_is_relayed_complete_and_in_order(self):
        _conn, resp = self.post("/v1/messages", self.BODY)
        text = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertLess(text.index("message_start"), text.index("message_stop"))

    def test_small_events_are_not_held_back_by_a_buffer(self):
        """read(4096) buffering delayed the first event by seconds."""
        FakeLlama.mode = "gap"
        _conn, resp = self.post("/v1/messages", self.BODY)
        started = time.monotonic()
        first = resp.fp.readline()
        self.assertIn(b"message_start", first)
        self.assertLess(time.monotonic() - started, 1.0, "the first event waited for the whole stream")
        resp.read()

    def test_pings_keep_the_stream_alive_during_a_silent_prefill(self):
        FakeLlama.mode = "slow_prefill"
        _conn, resp = self.post("/v1/messages", self.BODY)
        text = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("event: ping", text)
        self.assertLess(text.index("event: ping"), text.index("message_start"))

    def test_a_context_overflow_becomes_the_error_claude_code_compacts_on(self):
        FakeLlama.mode = "overflow"
        _conn, resp = self.post("/v1/messages", self.BODY)
        data = json.loads(resp.read())
        self.assertEqual(resp.status, 400)
        self.assertEqual(data["error"]["type"], "invalid_request_error")
        self.assertIn("Prompt is too long", data["error"]["message"])

    def test_a_dead_model_server_is_a_clear_error_not_a_hang(self):
        self.route.upstream = "http://127.0.0.1:9"
        self.route.ping_after = 60          # Windows takes ~2s to refuse; do not start the stream first
        _conn, resp = self.post("/v1/messages", self.BODY)
        data = json.loads(resp.read())
        self.assertEqual(resp.status, 502)
        self.assertIn("cc local serve", data["error"]["message"])

    def test_a_failure_after_the_stream_has_started_is_an_sse_error_not_a_second_response(self):
        """Once pings have gone out the 200 is committed; the error must ride inside the stream."""
        written, errors = io.BytesIO(), []
        handler = mock.Mock()
        handler.wfile = written
        handler.send_anthropic_error.side_effect = lambda *a, **k: errors.append(k)
        out = queue.Queue()
        self.route.ping_after = 0.05
        self.route.ping_every = 0.05
        threading.Timer(0.4, lambda: out.put(("error", "the model server died"))).start()
        self.route._pump(handler, out, stream=True)
        self.assertIn(b"event: ping", written.getvalue())
        handler.send_response.assert_called_once()                  # the one 200, never a second status
        self.assertTrue(errors[0]["headers_sent"])

    def test_count_tokens_uses_the_servers_answer_and_never_runs_a_generation(self):
        _conn, resp = self.post("/v1/messages/count_tokens", self.BODY)
        self.assertEqual(json.loads(resp.read()), {"input_tokens": 42})
        self.assertEqual(resp.getheader("X-Cortex-Count"), "exact")
        self.assertTrue(all(p.endswith("/count_tokens") for p, _b, _h in FakeLlama.seen))

    def test_count_tokens_falls_back_to_an_estimate_when_the_server_cannot_count(self):
        FakeLlama.mode = "no_count"
        _conn, resp = self.post("/v1/messages/count_tokens", self.BODY)
        data = json.loads(resp.read())
        self.assertGreater(data["input_tokens"], 0)
        self.assertEqual(resp.getheader("X-Cortex-Count"), "estimate")

    def test_a_client_that_disconnects_stops_the_generation(self):
        FakeLlama.mode = "endless"
        conn, resp = self.post("/v1/messages", self.BODY)
        resp.fp.readline()
        # http.client keeps the socket alive through the response's file object, so closing
        # only the connection never really disconnects.
        resp.close()
        conn.close()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not FakeLlama.disconnected:
            time.sleep(0.1)
        self.assertTrue(FakeLlama.disconnected, "the model kept generating for a client that was gone")

    def test_activity_is_tracked_for_the_idle_watchdog(self):
        self.assertEqual(self.route.active, 0)
        _conn, resp = self.post("/v1/messages", self.BODY)
        resp.read()
        time.sleep(0.3)
        self.assertEqual(self.route.active, 0)
        self.assertGreaterEqual(self.route.idle_seconds(), 0.0)

    def test_local_mode_ignores_providers_json_entirely(self):
        with mock.patch.object(self.gw, "get_active_provider_config",
                               side_effect=AssertionError("providers.json must not be read in local mode")):
            _conn, resp = self.post("/v1/messages", self.BODY)
            self.assertEqual(resp.status, 200)
            resp.read()


class TestCloudGatewayCountTokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = load_module("scripts/cortex-gateway.py")

    def test_counting_tokens_never_runs_a_billed_generation_on_other_routes(self):
        handler = object.__new__(self.gw.CortexGatewayHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        with mock.patch.object(handler, "relay") as relay:
            handler.handle_count_tokens({"messages": [{"role": "user", "content": "hello " * 50}]},
                                        {"key_name": "openrouter"}, "openrouter")
        relay.assert_not_called()
        self.assertGreater(json.loads(handler.wfile.getvalue())["input_tokens"], 0)

    def test_a_count_tokens_request_over_http_never_reaches_the_inference_route(self):
        """Through do_POST, so a dispatcher that stops special-casing the path is caught."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.gw.CortexGatewayHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hello " * 40}]})
        with mock.patch.object(self.gw, "get_active_provider_config",
                               return_value={"key_name": "openrouter", "type": "openrouter"}), \
                mock.patch.object(self.gw.CortexGatewayHandler, "handle_openrouter_dispatch",
                                  side_effect=AssertionError("count_tokens ran an inference")) as inference:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            conn.request("POST", "/v1/messages/count_tokens", body, {"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = json.loads(resp.read())
        inference.assert_not_called()
        self.assertEqual(resp.status, 200)
        self.assertGreater(data["input_tokens"], 0)

    def test_selecting_local_on_the_shared_gateway_explains_instead_of_crashing(self):
        handler = object.__new__(self.gw.CortexGatewayHandler)
        handler.send_anthropic_error = mock.Mock()
        handler.handle_local_dispatch({}, {})
        self.assertIn("cc offline", handler.send_anthropic_error.call_args[0][2])

    def test_local_mode_refuses_a_non_loopback_bind(self):
        with mock.patch.dict(os.environ, {"CORTEX_GATEWAY_ROUTE": "local"}), \
                mock.patch.object(sys, "argv", ["gw", "--host", "0.0.0.0"]):
            self.assertEqual(self.gw.main(), 2)


# =============================================================================
# commands and the session environment
# =============================================================================

def fake_hw(root):
    drive = os.path.splitdrive(root)[0]
    key = (drive + os.sep) if drive else "/"
    return {"ram_total_gb": 16.0, "ram_free_gb": 10.0, "disks": {key: 500.0},
            "gpus": [{"name": "NVIDIA GeForce RTX 3050", "total_gb": 6.0, "free_gb": 5.5}]}


class TestCommands(IsolatedHome):
    CONTENT = b"fake-model" * 100

    def _patch_hub(self):
        sha = hashlib.sha256(self.CONTENT).hexdigest()
        files = [{"path": "Qwen3.5-4B-Q4_K_M.gguf", "size": len(self.CONTENT), "sha256": sha,
                  "quant": "Q4_K_M", "part": None, "kind": "model"}]
        written = []

        def fake_download(repo, entry, dest, endpoint=None, opener=None, progress=None):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(self.CONTENT)
            written.append(dest)
            return dest

        for patcher in (mock.patch.object(local.hub, "list_files", return_value=files),
                        mock.patch.object(local.hub, "download", side_effect=fake_download),
                        mock.patch.object(local.plan, "detect", return_value=fake_hw(self.home))):
            patcher.start()
            self.addCleanup(patcher.stop)
        return written

    def _install(self, *extra):
        return local.main(["install", "qwen3.5-4b", "--dir", os.path.join(self.home, "models"), *extra])

    def test_an_agent_session_can_never_trigger_a_download_even_with_yes(self):
        written = self._patch_hub()
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
            rc = self._install("--yes")
        self.assertEqual(rc, 1)
        self.assertEqual(written, [])
        self.assertEqual(store.load()[0]["models"], {})
        local.hub.download.assert_not_called()

    def test_without_a_terminal_and_without_yes_nothing_is_downloaded(self):
        written = self._patch_hub()
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(self._install(), 1)
        self.assertEqual(written, [])

    def test_declining_the_prompt_downloads_nothing(self):
        written = self._patch_hub()
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="n"):
            self.assertEqual(self._install(), 1)
        self.assertEqual(written, [])

    def test_the_prompt_shows_source_size_hash_and_destination(self):
        self._patch_hub()
        out = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="n"), mock.patch("sys.stdout", out):
            self._install()
        shown = out.getvalue()
        for needle in ("huggingface.co/unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf", "sha256",
                       "Install to:", "Fit here:"):
            self.assertIn(needle, shown)

    def test_a_real_yes_downloads_verifies_and_registers_the_model(self):
        written = self._patch_hub()
        self.assertEqual(self._install("--yes"), 0)
        cfg, _ = store.load()
        info = cfg["models"]["qwen3.5-4b"]
        self.assertEqual(written, info["files"])
        self.assertEqual(info["size_bytes"], len(self.CONTENT))
        self.assertEqual(cfg["active_model"], "qwen3.5-4b")
        self.assertTrue(os.path.isfile(info["files"][0]))

    def test_installing_twice_does_not_download_again(self):
        self._patch_hub()
        self._install("--yes")
        local.hub.download.reset_mock()
        self.assertEqual(self._install("--yes"), 0)
        local.hub.download.assert_not_called()

    def test_an_unknown_name_lists_the_valid_ids_and_downloads_nothing(self):
        self._patch_hub()
        self.assertEqual(local.main(["install", "qwen3.5-99b", "--yes"]), 2)
        local.hub.download.assert_not_called()

    def test_an_arbitrary_repo_needs_a_file_choice(self):
        self._patch_hub()
        self.assertEqual(local.main(["install", "someone/Some-Model-GGUF", "--yes"]), 2)
        local.hub.download.assert_not_called()

    def test_removing_a_model_asks_and_only_deletes_inside_the_models_folder(self):
        self._patch_hub()
        self._install("--yes")
        path = store.load()[0]["models"]["qwen3.5-4b"]["files"][0]
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
            self.assertEqual(local.main(["rm", "qwen3.5-4b", "--yes"]), 1)
        self.assertTrue(os.path.isfile(path), "an agent deleted a model file")
        self.assertEqual(local.main(["rm", "qwen3.5-4b", "--yes"]), 0)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn("qwen3.5-4b", store.load()[0]["models"])

    def test_a_registered_file_outside_the_models_folder_is_never_deleted(self):
        outside = os.path.join(self.home, "precious.txt")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("keep")

        def register(c):
            c["data_dir"] = os.path.join(self.home, "models")
            c["models"]["x"] = {"files": [outside], "size_bytes": 4}
        store.update(register)
        self.assertEqual(local.main(["rm", "x", "--yes"]), 1)
        self.assertTrue(os.path.isfile(outside))

    def test_search_downloads_nothing(self):
        opener = FakeOpener(json_body=[{"id": "unsloth/Qwen3.5-4B-GGUF", "downloads": 1}])
        with mock.patch.object(local.hub, "default_opener", return_value=opener), \
                mock.patch.object(local.hub, "download") as download:
            self.assertEqual(local.main(["search", "qwen"]), 0)
        download.assert_not_called()

    def test_offline_without_a_model_explains_the_next_step_and_starts_nothing(self):
        with mock.patch.object(local.serve, "ensure") as ensure:
            self.assertEqual(local.cmd_offline([]), 1)
        ensure.assert_not_called()

    def test_use_requires_an_installed_model(self):
        self.assertEqual(local.main(["use", "ghost"]), 2)

    def test_help_and_unknown_subcommands(self):
        self.assertEqual(local.main([]), 0)
        self.assertEqual(local.main(["frobnicate"]), 2)

    def test_env_never_prints_the_token(self):
        self._patch_hub()
        self._install("--yes")
        token = store.token()
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(local.main(["env"]), 0)
        self.assertNotIn(token, out.getvalue())


class TestSessionEnvironment(IsolatedHome):
    def setUp(self):
        super().setUp()
        self.cfg = json.loads(json.dumps(store.DEFAULTS))
        self.cfg["models"]["qwen3.5-9b"] = {"ctx": 16384, "size_bytes": 1}
        self.env = profile.env_for(self.cfg, "http://127.0.0.1:8189", "tok", "qwen3.5-9b")

    def test_every_model_slot_uses_a_local_alias_that_does_not_look_like_a_claude_model(self):
        alias = self.cfg["claude"]["alias"]
        for key in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            self.assertEqual(self.env[key], alias, key)
        self.assertFalse(alias.lower().startswith("claude"))
        self.assertNotIn("[1m]", alias)

    def test_claude_code_is_told_the_real_context_so_it_compacts_in_time(self):
        self.assertEqual(int(self.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"]),
                         16384 - self.cfg["claude"]["max_output"])

    def test_the_session_talks_to_loopback_with_the_token_and_no_cloud_key(self):
        self.assertTrue(self.env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:"))
        self.assertEqual(self.env["ANTHROPIC_AUTH_TOKEN"], "tok")
        self.assertEqual(self.env["ANTHROPIC_API_KEY"], "")
        self.assertIn("127.0.0.1", self.env["NO_PROXY"])

    def test_inherited_cloud_credentials_are_dropped(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-real", "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
                                          "ANTHROPIC_BASE_URL": "https://api.anthropic.com"}):
            env = launcher.session_env("cfgdir", self.env, drop=profile.DROP)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8189")

    def test_the_lean_tool_list_is_added_once_and_never_over_the_users_choice(self):
        self.assertIn("--tools", profile.session_args(self.cfg, ["-p", "hi"]))
        mine = profile.session_args(self.cfg, ["--tools", "Read"])
        self.assertEqual(mine.count("--tools"), 1)
        self.assertEqual(mine[mine.index("--tools") + 1], "Read")

    def test_the_offline_profile_is_outside_the_cloud_profile_namespace(self):
        from cortex.paths import profiles_dir
        self.assertFalse(profile.config_dir().startswith(os.path.abspath(profiles_dir())))

    def test_ultracode_is_a_valid_effort_flag_and_passes_through_unchanged(self):
        args, error = launcher.translate_args(["--effort", "ultracode"])
        self.assertIsNone(error)
        self.assertEqual(args, ["--effort", "ultracode"])
        _args, error = launcher.translate_args(["--effort", "turbo"])
        self.assertIsNotNone(error)


class TestCommandWiring(unittest.TestCase):
    def test_local_and_offline_are_reserved_command_names(self):
        from cortex import __main__ as main
        self.assertIn("local", main.TOP_LEVEL_COMMANDS)
        self.assertIn("offline", main.TOP_LEVEL_COMMANDS)

    def test_the_dispatcher_reaches_the_local_package(self):
        from cortex import __main__ as main
        with mock.patch.object(local, "main", return_value=7) as handler:
            self.assertEqual(main.main(["local", "status"]), 7)
        handler.assert_called_once_with(["status"])


if __name__ == "__main__":
    unittest.main()
