"""Input helpers for Android RPA."""

from __future__ import annotations


def relative_to_absolute(x: int, y: int, screen_size: list[int] | tuple[int, int]) -> tuple[int, int]:
    width, height = int(screen_size[0]), int(screen_size[1])
    return round(width * int(x) / 1000), round(height * int(y) / 1000)


def center_of_box(box: list[int]) -> tuple[int, int]:
    x1, y1, x2, y2 = [int(v) for v in box]
    return round((x1 + x2) / 2), round((y1 + y2) / 2)
