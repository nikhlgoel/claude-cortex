---
name: algorithms
description: Algorithmic patterns, complexity analysis, and competitive programming technique. Use for data structures, LeetCode-style problems, or Big-O reasoning.
---

# CS Core & Algorithmic Interview Mastery Protocol

## 1. Prime Directive: Zero-Allocation, Cache-Optimal Engineering

Whenever solving competitive programming problems, LeetCode challenges, or writing systems code:
Deliver solutions formatted with staff-level rigor.

Every solution MUST incorporate:
1. **Algorithmic Pattern Classification** (identify which of the 14 core patterns applies).
2. **Mathematical Invariant Proof** (why the state transition or pointer movement is unconditionally correct).
3. **Hardware & Cache Analysis** (spatial/temporal locality, contiguous memory layout, CPU branch prediction).
4. **Modern C++20 Implementation** (concepts, `std::views`, `std::span`, zero heap allocation in critical path).


## 3. C++20 High-Performance Standards

- **Contiguous Allocation:** Prefer `std::vector` or `std::array` over pointer-heavy node structures.
- **Span & Views:** Use `std::span<const T>` instead of `const std::vector<T>&` to decouple memory from container type.
- **Fast I/O:** Always prepend:
  ```cpp
  std::ios_base::sync_with_stdio(false);
  std::cin.tie(nullptr);
  ```
- **Bit Manipulation Superpowers:** Use standard `<bit>` functions (`std::popcount`, `std::countl_zero`, `std::has_single_bit`).
