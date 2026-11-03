from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection


@dataclass(frozen=True)
class Block:
    x0: int
    y0: int
    w: int
    h: int
    col: int
    row: int


def detect_block(
    start: tuple[int, int],
    rows: int,
    cols: int,
    is_member: Callable[[int, int], bool],
    valid_shapes: Collection[tuple[int, int]],
) -> Block | None:
    seen = {start}
    stack = [start]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in seen:
                continue
            if not (0 <= nx < cols and 0 <= ny < rows):
                continue
            if is_member(nx, ny):
                seen.add((nx, ny))
                stack.append((nx, ny))

    x0 = min(x for x, _ in seen)
    y0 = min(y for _, y in seen)
    w = max(x for x, _ in seen) - x0 + 1
    h = max(y for _, y in seen) - y0 + 1

    if w * h != len(seen):
        return None
    if (w, h) not in valid_shapes:
        return None
    return Block(x0=x0, y0=y0, w=w, h=h, col=start[0] - x0, row=start[1] - y0)
