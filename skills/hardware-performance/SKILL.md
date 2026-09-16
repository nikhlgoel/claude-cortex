---
name: hardware-performance
description: Cache hierarchy, SIMD, branch prediction, CUDA/Triton kernels, roofline analysis. Use for low-level performance work.
---

# Computer Systems, Hardware Architecture & GPU Engineering Protocol

## 1. Prime Directive: Hardware-Conscious, Cache-Optimal Engineering

When writing low-level systems, C++, CUDA, Triton, or high-throughput distributed code:
Structure your implementation to match the underlying physical hardware.

Never treat the hardware as an abstract black box. Every solution MUST respect:
1. **Memory Hierarchy & Latency Horizons** (Registers 0.5ns -> L1 Cache 1ns -> L2 Cache 4ns -> L3 Cache 20-40ns -> DRAM 100ns -> NVMe SSD 10-100μs).
2. **CPU Microarchitecture Invariants** (64-byte cache lines, spatial/temporal locality, branchless execution, SIMD vectorization).
3. **GPU Massively Parallel Execution Models** (SIMT, Streaming Multiprocessors, 32-thread Warps, Memory Coalescing, Bank Conflicts).


## 3. GPU Architecture & Massively Parallel Computing (CUDA & Triton)

### A. SIMT Execution & Warp Efficiency
- **The Warp (32 Threads):** NVIDIA GPUs schedule threads in lockstep groups of 32 threads (a Warp).
- **Warp Divergence:** If threads within the same warp take divergent branches of an `if-else` statement, both branches are serialized and masked. Keep control flow uniform across warp boundaries (`threadIdx.x / 32`).

### B. Memory Coalescing (Global Memory -> Registers)
- Global DRAM access (HBM3 / GDDR6) is high-latency (400-800 cycles).
- Coalescing Rule: Ensure threads in a warp access consecutive memory addresses aligned to 32, 64, or 128 bytes so the hardware fulfills the request in a single memory transaction.

### C. Shared Memory & Bank Conflicts
- Shared memory (on-chip SRAM, ~1-2 cycles latency) is divided into 32 banks (4 bytes per bank).
- Bank Conflict: If two or more threads in a warp access different words in the same bank, accesses are serialized.
- Fix: Apply array padding (e.g. `__shared__ float tile[32][33];` instead of `[32][32]`) to stagger access across banks.

### D. The Roofline Model & Kernel Profiling
- **Arithmetic Intensity:** $\text{FLOPs/Byte} = \frac{\text{Total Floating Point Operations}}{\text{Total Bytes Transferred from Global Memory}}$.
- If below the machine's ridge point: Kernel is **Memory Bandwidth Bound** (optimize memory reuse via shared memory tiling, fusion, or quantization).
- If above the ridge point: Kernel is **Compute Bound** (optimize instruction pipeline, use Tensor Cores via FP16/BF16/FP8 matrix multiply units).

### E. AI Systems & Modern LLM Inference Optimization
- **FlashAttention:** Tile query, key, and value matrices in high-speed on-chip SRAM to avoid writing the $O(N^2)$ attention matrix to high-latency HBM.
- **PagedAttention & KV-Cache:** Allocate key-value caches in virtual memory pages to eliminate memory fragmentation in dynamic generation.
- **Quantization:** FP8 (E4M3, E5M2), INT8 (SmoothQuant), and INT4 (AWQ) to increase effective memory bandwidth by 2x-4x.
