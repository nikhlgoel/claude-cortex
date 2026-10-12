"""Curated starting points for local models.

This is a *suggestion list*, not a trust list. Nothing is downloaded because it is
here: ``cc local install <id>`` resolves the real file, size and sha256 from the
Hugging Face listing at that moment and asks the person before fetching anything.
``approx_gb`` is what the Hub listed on 2026-10-11 and is only used to rank what fits
before any network call.

Fields
    repo / quant   where to resolve the file. The filename is NOT stored: it is found
                   from the listing so a renamed upstream file cannot be mis-pinned.
    template       reasoning kind understood by ``shaping.apply_reasoning``
                   (qwen3 | gpt-oss | always | none).
    sampling       vendor-recommended sampling, split into thinking/plain sets.
    ctx            (default, max) context in tokens that is realistic on 6 GB VRAM.
    active_b       parameters used per token for MoE models; sizes the KV-cache estimate.
    moe            mixture-of-experts: expert tensors can live in system RAM
                   (``--n-cpu-moe``) while the always-used layers stay on the GPU.
    tier           recommended | fallback | experimental
    min_free_ram_gb  free system RAM needed on top of VRAM (an estimate, see plan.py).

Nothing here claims a model is *proven* with Claude Code. ``cc local doctor`` measures
that on the person's own machine; a catalog line cannot.
"""

from __future__ import annotations

_QWEN_SAMPLING = {"think": {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
                  "plain": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}}

CATALOG = {
    "qwen3.5-4b": {
        "title": "Qwen3.5 4B (Q4_K_M)", "repo": "unsloth/Qwen3.5-4B-GGUF", "quant": "Q4_K_M",
        "approx_gb": 2.74, "params_b": 4, "moe": False, "template": "qwen3",
        "sampling": _QWEN_SAMPLING, "ctx": (16384, 32768), "tier": "recommended",
        "role": "Fits entirely in 6 GB VRAM. Fast helper / first model to try on a tight machine.",
        "min_free_ram_gb": 2.5,
    },
    "qwen3.5-9b": {
        "title": "Qwen3.5 9B (Q4_K_M)", "repo": "unsloth/Qwen3.5-9B-GGUF", "quant": "Q4_K_M",
        "approx_gb": 5.68, "params_b": 9, "moe": False, "template": "qwen3",
        "sampling": _QWEN_SAMPLING, "ctx": (16384, 32768), "tier": "recommended",
        "role": "Daily driver for short, well-scoped coding tasks once ~4.5 GB RAM is free.",
        "min_free_ram_gb": 4.5,
    },
    "mellum2.1-12b-a2.5b": {
        "title": "JetBrains Mellum 2.1 12B-A2.5B Thinking (MXFP4_MOE)",
        "repo": "JetBrains/Mellum2.1-12B-A2.5B-Thinking-GGUF", "quant": "MXFP4_MOE",
        "approx_gb": 7.03, "params_b": 12, "moe": True, "active_b": 2.5, "template": "always",
        "sampling": {"think": {"temperature": 0.6, "top_p": 0.95},
                     "plain": {"temperature": 0.6, "top_p": 0.95}},
        "ctx": (16384, 32768), "tier": "experimental",
        "role": "Fast MoE agent model. Vendor-reported numbers only; nobody has reported it through Claude Code.",
        "min_free_ram_gb": 5.5,
    },
    "qwen3-coder-30b-a3b": {
        "title": "Qwen3-Coder 30B-A3B Instruct (UD-IQ3_XXS)",
        "repo": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", "quant": "UD-IQ3_XXS",
        "approx_gb": 12.85, "params_b": 30, "moe": True, "active_b": 3.3, "template": "none",
        "sampling": {"plain": {"temperature": 0.7, "top_p": 0.8, "top_k": 20}},
        "ctx": (16384, 32768), "tier": "fallback",
        "role": "Non-thinking, template-friendly coder. Needs ~10-11 GB free RAM; dedicate the machine to it.",
        "min_free_ram_gb": 10.5,
    },
    "qwen3.6-35b-a3b": {
        "title": "Qwen3.6 35B-A3B (UD-IQ3_XXS)", "repo": "unsloth/Qwen3.6-35B-A3B-GGUF",
        "quant": "UD-IQ3_XXS", "approx_gb": 13.21, "params_b": 35, "moe": True, "active_b": 3.0, "template": "qwen3",
        "sampling": _QWEN_SAMPLING, "ctx": (16384, 32768), "tier": "fallback",
        "role": "Strongest option that fits at all here; only with ~11 GB free RAM.",
        "min_free_ram_gb": 11.0,
    },
    "gpt-oss-20b": {
        "title": "gpt-oss 20B (MXFP4)", "repo": "ggml-org/gpt-oss-20b-GGUF", "quant": "MXFP4",
        "approx_gb": 12.11, "params_b": 20, "moe": True, "active_b": 3.6, "template": "gpt-oss",
        "sampling": {"think": {"temperature": 1.0, "top_p": 1.0},
                     "plain": {"temperature": 1.0, "top_p": 1.0}},
        "ctx": (16384, 32768), "tier": "fallback",
        "role": "Mature llama.cpp support; reasoning level is set in the system prefix.",
        "min_free_ram_gb": 10.0,
    },
}

#: Models people ask about that this machine class cannot run usefully. Shown by
#: ``cc local status --all`` so the limit is explained instead of discovered.
NOT_OFFERED = {
    "Qwen3.8-27B (dense)": "dense 27B spills to RAM: about 2-3 tokens/s, unusable interactively on 6 GB VRAM",
    "Qwen3-Coder-Next 80B-A3B": "smallest sane quant is over 40 GB",
}


def get(model_id):
    return CATALOG.get(model_id)


def ids(include_experimental=True):
    return [k for k, v in CATALOG.items() if include_experimental or v["tier"] != "experimental"]
