"""River-crossing and bridge/torch verification via exhaustive BFS."""
from __future__ import annotations

import heapq
from collections import deque

from .base import VerificationResult


def _wolf_goat_cabbage_min_moves() -> tuple[int, int]:
    """Return (min_moves, number_of_optimal_paths) for the classic puzzle."""
    start = (0, frozenset(["wolf", "goat", "cabbage"]))
    goal = (1, frozenset())
    forbidden = [{"wolf", "goat"}, {"goat", "cabbage"}]
    dist = {start: 0}
    count = {start: 1}
    q = deque([start])
    while q:
        state = q.popleft()
        side, left = state
        left = set(left)
        if state == goal:
            continue
        options = [None] + sorted(left if side == 0 else set(["wolf", "goat", "cabbage"]) - left)
        for item in options:
            new_left = set(left)
            if item is not None:
                if side == 0:
                    new_left.discard(item)
                else:
                    new_left.add(item)
            new_side = 1 - side
            # Only the bank WITHOUT the farmer can be unsafe.
            bank_without_farmer = new_left if new_side == 1 else \
                set(["wolf", "goat", "cabbage"]) - new_left
            if any(pair <= bank_without_farmer for pair in forbidden):
                continue
            nxt = (new_side, frozenset(new_left))
            nd = dist[state] + 1
            if nxt not in dist:
                dist[nxt] = nd
                count[nxt] = count[state]
                q.append(nxt)
            elif dist[nxt] == nd:
                count[nxt] += count[state]
    if goal not in dist:
        return -1, 0
    return dist[goal], count[goal]


def _missionaries_cannibals_min(missionaries: int = 3, cannibals: int = 3,
                                capacity: int = 2) -> int:
    start = (missionaries, cannibals, 0)
    goal = (0, 0, 1)
    dist = {start: 0}
    q = deque([start])

    def valid(m: int, c: int) -> bool:
        if m < 0 or c < 0 or m > missionaries or c > cannibals:
            return False
        if m > 0 and c > m:
            return False
        mr, cr = missionaries - m, cannibals - c
        if mr > 0 and cr > mr:
            return False
        return True

    while q:
        m, c, side = q.popleft()
        if (m, c, side) == goal:
            return dist[(m, c, side)]
        for dm in range(capacity + 1):
            for dc in range(capacity + 1 - dm):
                if dm + dc == 0:
                    continue
                if side == 0:
                    nm, nc = m - dm, c - dc
                else:
                    nm, nc = m + dm, c + dc
                if valid(nm, nc):
                    nxt = (nm, nc, 1 - side)
                    if nxt not in dist:
                        dist[nxt] = dist[(m, c, side)] + 1
                        q.append(nxt)
    return -1


def _bridge_torch_min(times: list[int], capacity: int = 2) -> int:
    """Minimum total crossing time for the bridge-and-torch problem."""
    n = len(times)
    if n == 0:
        return 0
    full = (1 << n) - 1
    start = (full, 1)  # left mask (all on left), torch side 1=left
    best = {start: 0}
    pq = [(0, full, 1)]
    while pq:
        cost, left, side = heapq.heappop(pq)
        if cost > best.get((left, side), 1 << 60):
            continue
        if left == 0 and side == 0:
            return cost
        idxs = [i for i in range(n) if ((left >> i) & 1) == side]
        # choose up to `capacity` people from the torch side
        from itertools import combinations
        for k in range(1, min(capacity, len(idxs)) + 1):
            for group in combinations(idxs, k):
                t = max(times[i] for i in group)
                new_left = left
                for i in group:
                    new_left ^= (1 << i)
                nxt = (new_left, 1 - side)
                nc = cost + t
                if nc < best.get(nxt, 1 << 60):
                    best[nxt] = nc
                    heapq.heappush(pq, (nc, new_left, 1 - side))
    return -1


def verify_crossing(puzzle: dict) -> VerificationResult:
    kind = str(puzzle.get("kind") or puzzle.get("type") or "").lower()
    if kind in ("wolf_goat_cabbage", "wolf-goat-cabbage", "river"):
        moves, paths = _wolf_goat_cabbage_min_moves()
        if moves < 0:
            return VerificationResult.failure("river puzzle has no solution")
        given = puzzle.get("answer_moves", puzzle.get("answer"))
        if given is not None:
            try:
                if int(given) != moves:
                    return VerificationResult.failure(f"wrong answer: minimum is {moves} crossings, got {given}")
            except (TypeError, ValueError):
                return VerificationResult.failure("answer must be a number of crossings")
        return VerificationResult.success(moves, f"BFS: minimum {moves} crossings ({paths} optimal paths)")
    if kind in ("missionaries", "missionaries_cannibals"):
        m = int(puzzle.get("missionaries", 3))
        c = int(puzzle.get("cannibals", 3))
        cap = int(puzzle.get("capacity", 2))
        moves = _missionaries_cannibals_min(m, c, cap)
        if moves < 0:
            return VerificationResult.failure("missionaries puzzle has no solution")
        given = puzzle.get("answer_moves", puzzle.get("answer"))
        if given is not None and int(given) != moves:
            return VerificationResult.failure(f"wrong answer: minimum is {moves} crossings, got {given}")
        return VerificationResult.success(moves, f"BFS: minimum {moves} crossings")
    if kind in ("bridge", "bridge_torch", "torch"):
        times = [int(x) for x in (puzzle.get("times") or [])]
        cap = int(puzzle.get("capacity", 2))
        if not times or any(t <= 0 for t in times):
            return VerificationResult.failure("bridge puzzle needs positive crossing times")
        best = _bridge_torch_min(times, cap)
        if best < 0:
            return VerificationResult.failure("bridge puzzle has no solution")
        given = puzzle.get("answer_time", puzzle.get("answer"))
        if given is not None and int(given) != best:
            return VerificationResult.failure(f"wrong answer: minimum time is {best}, got {given}")
        return VerificationResult.success(best, f"Dijkstra: minimum total time {best}")
    return VerificationResult.failure(f"no crossing verifier for kind {kind!r}", verified=False)
