"""
Win condition checkers for all supported Bingo win types.

All functions accept a 5×5 boolean grid (list[list[bool]]) where
True = square is marked. The FREE center at [2][2] is always True.
"""
from __future__ import annotations

from .events import WIN_TYPES


def check_win(marked: list[list[bool]], win_type: str) -> bool:
    """
    Return True if the given 5×5 marked grid satisfies the day's win condition.
    win_type must be one of the values in WIN_TYPES.
    """
    if win_type == "standard":
        return _check_standard(marked)
    if win_type == "four_corners":
        return _check_four_corners(marked)
    if win_type == "postage_stamp":
        return _check_postage_stamp(marked)
    if win_type == "blackout":
        return _check_blackout(marked)
    if win_type == "x_pattern":
        return _check_x_pattern(marked)
    if win_type == "outside_edges":
        return _check_outside_edges(marked)
    return False


# ---------------------------------------------------------------------------
# Individual win type implementations
# ---------------------------------------------------------------------------

def _check_standard(marked: list[list[bool]]) -> bool:
    """Any complete row, column, or main diagonal (5-in-a-row)."""
    # Rows
    for r in range(5):
        if all(marked[r][c] for c in range(5)):
            return True
    # Columns
    for c in range(5):
        if all(marked[r][c] for r in range(5)):
            return True
    # Main diagonal (top-left → bottom-right)
    if all(marked[i][i] for i in range(5)):
        return True
    # Anti-diagonal (top-right → bottom-left)
    if all(marked[i][4 - i] for i in range(5)):
        return True
    return False


def _check_four_corners(marked: list[list[bool]]) -> bool:
    """All 4 corner squares marked."""
    return (
        marked[0][0] and marked[0][4]
        and marked[4][0] and marked[4][4]
    )


def _check_postage_stamp(marked: list[list[bool]]) -> bool:
    """Any 2×2 contiguous block fully marked (16 possible origins in a 5×5)."""
    for r in range(4):
        for c in range(4):
            if (
                marked[r][c] and marked[r][c + 1]
                and marked[r + 1][c] and marked[r + 1][c + 1]
            ):
                return True
    return False


def _check_blackout(marked: list[list[bool]]) -> bool:
    """All 25 squares marked."""
    return all(marked[r][c] for r in range(5) for c in range(5))


def _check_x_pattern(marked: list[list[bool]]) -> bool:
    """Both main diagonals fully marked (9 unique squares, center shared)."""
    main = all(marked[i][i] for i in range(5))
    anti = all(marked[i][4 - i] for i in range(5))
    return main and anti


def _check_outside_edges(marked: list[list[bool]]) -> bool:
    """All 16 perimeter squares marked (top row, bottom row, left/right cols)."""
    # Top row
    for c in range(5):
        if not marked[0][c]:
            return False
    # Bottom row
    for c in range(5):
        if not marked[4][c]:
            return False
    # Left column (inner rows 1-3)
    for r in range(1, 4):
        if not marked[r][0]:
            return False
    # Right column (inner rows 1-3)
    for r in range(1, 4):
        if not marked[r][4]:
            return False
    return True


def build_marked_grid(
    layout: list[list[int]],
    pool_squares: list[dict],
    marked_fingerprints: set[str],
) -> list[list[bool]]:
    """
    Build a 5×5 boolean marked grid for a player.

    layout:             5×5 array of pool indices (-1 = FREE center)
    pool_squares:       list of square dicts (indexed by layout values)
    marked_fingerprints: set of fingerprints that have been triggered today

    FREE center is always True.
    """
    from .events import make_fingerprint

    grid: list[list[bool]] = []
    for row in layout:
        grid_row: list[bool] = []
        for idx in row:
            if idx == -1:
                grid_row.append(True)  # FREE is always marked
            else:
                sq = pool_squares[idx]
                fp = make_fingerprint(sq)
                grid_row.append(fp in marked_fingerprints)
        grid.append(grid_row)
    return grid
