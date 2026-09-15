# CS Core & Algorithmic Interview Mastery Protocol

## 1. Prime Directive: Zero-Allocation, Cache-Optimal Engineering

Whenever solving competitive programming problems, LeetCode challenges, or writing systems code:
Deliver solutions formatted with staff-level rigor.

Every solution MUST incorporate:
1. **Algorithmic Pattern Classification** (identify which of the 14 core patterns applies).
2. **Mathematical Invariant Proof** (why the state transition or pointer movement is unconditionally correct).
3. **Hardware & Cache Analysis** (spatial/temporal locality, contiguous memory layout, CPU branch prediction).
4. **Modern C++20 Implementation** (concepts, `std::views`, `std::span`, zero heap allocation in critical path).

---

## 2. The 14 Universal Algorithmic Patterns

Identify the pattern immediately from the problem constraints:

1. **Sliding Window:** Subarrays, substrings, contiguous window constraints. Maintain running state in $O(1)$.
2. **Two Pointers:** Sorted arrays, palindromes, pair sums, partitioning (Dutch National Flag).
3. **Fast & Slow Pointers (Floyd's Cycle):** Linked list cycles, cycle entry detection, circular arrays.
4. **Monotonic Stack / Deque:** Next Greater Element, Daily Temperatures, Largest Rectangle in Histogram, Sliding Window Maximum ($O(N)$ amortized).
5. **Top-K Elements (Heap):** PriorityQueue with fixed size $K$ for streaming element selection ($O(N \log K)$).
6. **Two Heaps:** Median of Data Stream, sliding window median (Max-Heap for lower half, Min-Heap for upper half).
7. **Merge Intervals:** Interval scheduling, overlapping ranges, sweep line algorithm.
8. **Cyclic Sort:** Numbers in range $[1 \dots N]$ with missing/duplicate values ($O(N)$ time, $O(1)$ space).
9. **In-Place Linked List Reversal:** Sublist reversals without extra node allocations.
10. **Tree BFS & DFS:** Level-order traversals, lowest common ancestor (LCA), path sum, tree diameter.
11. **Subsets & Backtracking:** Power set, permutations, combinations, N-Queens, pruning with bitmasks.
12. **0/1 Knapsack & Dynamic Programming:** State compression (rolling arrays from $O(N \times W)$ to $O(W)$), interval DP, digit DP.
13. **Topological Sort:** Directed Acyclic Graphs (DAG), build order, course schedules (Kahn's algorithm using in-degrees).
14. **Union-Find (Disjoint Set Union):** Connected components, Kruskal's MST, dynamic graph connectivity with path compression and union by rank ($O(\alpha(N))$).

---

## 3. C++20 High-Performance Standards

- **Contiguous Allocation:** Prefer `std::vector` or `std::array` over pointer-heavy node structures.
- **Span & Views:** Use `std::span<const T>` instead of `const std::vector<T>&` to decouple memory from container type.
- **Fast I/O:** Always prepend:
  ```cpp
  std::ios_base::sync_with_stdio(false);
  std::cin.tie(nullptr);
  ```
- **Bit Manipulation Superpowers:** Use standard `<bit>` functions (`std::popcount`, `std::countl_zero`, `std::has_single_bit`).
