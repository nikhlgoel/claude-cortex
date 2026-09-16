---
name: cpp-systems
description: Modern C++20 systems engineering: RAII, move semantics, const correctness, zero-allocation hot paths. Use when writing, reviewing, or debugging C++.
---

﻿# C++ Systems Engineering & Competitive Programming Standards

This rule applies automatically whenever writing, analyzing, or reviewing C++ code, data structures, algorithms, or LeetCode problems.


## 2. LeetCode & Competitive Programming Problem Structure

Whenever presenting a solution to an algorithmic or LeetCode problem, format the response with:

### A. Intuition & Pattern Identification (2-3 sentences)
State which algorithmic pattern solves this optimally (e.g., Two Pointers, Monotonic Stack, Sliding Window, Topo-Sort, BFS/DFS, Binary Search on Answer, DP with Space Optimization) and *why* naive brute force is suboptimal.

### B. Optimal C++ Implementation
- Clean, idiomatic, typed code within the LeetCode solution class.
- Fast I/O snippet if competitive programming context:
  ```cpp
  static const auto _ = []() {
      std::ios_base::sync_with_stdio(false);
      std::cin.tie(nullptr);
      return nullptr;
  }();
  ```
- Use descriptive variable names while maintaining concise competitive speed.
- Prevent integer overflow (use `long long` where `int` can overflow in sum/multiplication).

### C. Complexity & Invariant Analysis
- **Time Complexity:** Explicit $O(f(N))$ with step-by-step justification.
- **Auxiliary Space Complexity:** Explicit $O(g(N))$ distinguishing between return space and extra algorithm space.
- **Cache Locality:** Highlight memory layout advantages (e.g., array vs linked list pointer-chasing).

### D. Critical Edge Cases Handled
List 3 specific edge cases verified:
1. Boundary conditions (e.g., $N=0, 1$, empty array/string).
2. Extreme values (e.g., `INT_MIN`, `INT_MAX`, duplicate elements).
3. Structural quirks (e.g., cycles in graphs, unbalanced trees).
