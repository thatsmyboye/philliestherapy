"""
Win condition checkers for all supported Bingo win types.

Each checker uses an n×n boolean grid (list[list[bool]]) where True = marked.
When `free_center` is used in build_marked_grid, the legacy center cell is
always True (5×5 League boards only).
"""
from __future__ import annotations

from .events import WIN_TYPES


def check_win(marked: list[list[bool]], win_type: str) -> bool:
    """
    Return True if the marked grid satisfies the day's win condition.
    Grid must be square (n×n). win_type must be one of WIN_TYPES.
    """
    n = len(marked)
    if n == 0 or any(len(row) != n for row in marked):
        return False

    if win_type == "standard":
        return _check_standard(marked, n)
    if win_type == "four_corners":
        return _check_four_corners(marked, n)
    if win_type == "postage_stamp":
        return _check_postage_stamp(marked, n)
    if win_type == "blackout":
        return _check_blackout(marked, n)
    if win_type == "x_pattern":
        return _check_x_pattern(marked, n)
    if win_type == "outside_edges":
        return _check_outside_edges(marked, n)
    return False


# ---------------------------------------------------------------------------
# Individual win type implementations
# ---------------------------------------------------------------------------


def _check_standard(marked: list[list[bool]], n: int) -> bool:
    """Any complete row, column, or main diagonal (n-in-a-row)."""
    for r in range(n):
        if all(marked[r][c] for c in range(n)):
            return True
    for c in range(n):
        if all(marked[r][c] for r in range(n)):
            return True
    if all(marked[i][i] for i in range(n)):
        return True
    if all(marked[i][n - 1 - i] for i in range(n)):
        return True
    return False


def _check_four_corners(marked: list[list[bool]], n: int) -> bool:
    """All four corner squares marked."""
    last = n - 1
    return (
        marked[0][0] and marked[0][last]
        and marked[last][0] and marked[last][last]
    )


def _check_postage_stamp(marked: list[list[bool]], n: int) -> bool:
    """Any 2×2 contiguous block fully marked."""
    for r in range(n - 1):
        for c in range(n - 1):
            if (
                marked[r][c] and marked[r][c + 1]
                and marked[r + 1][c] and marked[r + 1][c + 1]
            ):
                return True
    return False


def _check_blackout(marked: list[list[bool]], n: int) -> bool:
    """Every square marked."""
    return all(marked[r][c] for r in range(n) for c in range(n))


def _check_x_pattern(marked: list[list[bool]], n: int) -> bool:
    """Both main diagonals fully marked."""
    main = all(marked[i][i] for i in range(n))
    anti = all(marked[i][n - 1 - i] for i in range(n))
    return main and anti


def _check_outside_edges(marked: list[list[bool]], n: int) -> bool:
    """Full top and bottom rows plus left/right columns on inner rows."""
    for c in range(n):
        if not marked[0][c]:
            return False
    for c in range(n):
        if not marked[n - 1][c]:
            return False
    for r in range(1, n - 1):
        if not marked[r][0]:
            return False
    for r in range(1, n - 1):
        if not marked[r][n - 1]:
            return False
    return True


def build_marked_grid(
    layout: list[list[int]],
    pool_squares: list[dict],
    marked_fingerprints: set[str],
    *,
    free_center: bool = True,
) -> list[list[bool]]:
    """
    Build a square boolean marked grid for a player.

    layout: pool indices per cell, or -1 for FREE center when free_center=True
    pool_squares: list of square dicts (indexed by layout values)
    marked_fingerprints: fingerprints triggered today
    """
    from .events import make_fingerprint

    grid: list[list[bool]] = []
    for row in layout:
        grid_row: list[bool] = []
        for idx in row:
            if idx == -1:
                grid_row.append(bool(free_center))
            else:
                sq = pool_squares[idx]
                fp = make_fingerprint(sq)
                grid_row.append(fp in marked_fingerprints)
        grid.append(grid_row)
    return grid
