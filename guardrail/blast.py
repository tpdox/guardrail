"""Blast radius computation via BFS over the manifest child_map."""

from __future__ import annotations

from collections import deque


def compute_blast_radius(
    child_map: dict[str, list[str]],
    model_ids: list[str],
    max_depth: int = 10,
) -> list[str]:
    """BFS over child_map to find all downstream models affected by changes.

    Returns unique_ids of downstream models (excluding the input models themselves).
    Only includes model.* nodes, not tests or other node types.
    """
    visited: set[str] = set(model_ids)
    queue: deque[tuple[str, int]] = deque()

    for mid in model_ids:
        for child in child_map.get(mid, []):
            if child.startswith("model.") and child not in visited:
                queue.append((child, 1))
                visited.add(child)

    downstream: list[str] = []

    while queue:
        uid, depth = queue.popleft()
        downstream.append(uid)

        if depth >= max_depth:
            continue

        for child in child_map.get(uid, []):
            if child.startswith("model.") and child not in visited:
                queue.append((child, depth + 1))
                visited.add(child)

    return sorted(downstream)
