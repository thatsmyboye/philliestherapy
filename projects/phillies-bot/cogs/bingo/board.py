"""
Board generation and rendering for Phillies and League Bingo.

Phillies: 4×4 layout, 16 pool squares, no free space.
League:   5×5 layout, 24 pool squares, center cell FREE (index -1).
"""
from __future__ import annotations

import random

import discord

from .events import win_type_label_for_grid
from .win_checker import build_marked_grid

# Column width for the board code-block (monospace alignment).
# Each cell: emoji (2 display units) + 3 spaces = 5 display units.
_COL_W = 5

_HEADER_LETTERS = ["B", "I", "N", "G", "O"]


def generate_layout(
    pool_size: int,
    user_seed: str,
    *,
    grid_size: int = 5,
    free_center: bool = True,
) -> list[list[int]]:
    """
    Shuffle pool indices into a grid_size×grid_size grid for a player.

    When free_center is True (League), the center holds -1 (FREE) and
    pool_size must be grid_size² − 1. When False (Phillies 4×4),
    pool_size must equal grid_size².

    user_seed should be f"{user_id}:{game_date}" (or with :reroll) for stable draws.
    """
    if free_center:
        expected = grid_size * grid_size - 1
        if pool_size != expected:
            raise ValueError(f"Pool must have {expected} squares when using a FREE center.")
        rng = random.Random(user_seed)
        indices = list(range(pool_size))
        rng.shuffle(indices)
        mid = (grid_size * grid_size) // 2
        cells: list[int] = indices[:mid] + [-1] + indices[mid:]
        return [cells[r * grid_size:(r + 1) * grid_size] for r in range(grid_size)]

    expected = grid_size * grid_size
    if pool_size != expected:
        raise ValueError(f"Pool must have {expected} squares for a full grid with no FREE cell.")
    rng = random.Random(user_seed)
    indices = list(range(pool_size))
    rng.shuffle(indices)
    return [indices[r * grid_size:(r + 1) * grid_size] for r in range(grid_size)]


def render_board_embed(
    layout: list[list[int]],
    pool_squares: list[dict],
    marked_fingerprints: set[str],
    display_name: str,
    win_type: str,
    bingo_achieved: bool,
    *,
    free_center: bool = True,
) -> discord.Embed:
    """
    Build the ephemeral board embed shown by /bingo check.
    """
    n = len(layout)
    win_label = win_type_label_for_grid(win_type, n)

    if bingo_achieved:
        title = f"🎉 {display_name}'s Bingo Board — BINGO!"
        colour = discord.Colour.gold()
    else:
        title = f"🎱 {display_name}'s Bingo Board"
        colour = discord.Colour.red()

    marked_grid = build_marked_grid(
        layout, pool_squares, marked_fingerprints, free_center=free_center,
    )

    lines: list[str] = []
    header = "".join(c.ljust(_COL_W) for c in _HEADER_LETTERS[:n])
    lines.append(header)
    lines.append("")

    for r in range(n):
        symbol_row: list[str] = []
        label_row: list[str] = []
        for c in range(n):
            idx = layout[r][c]
            is_marked = marked_grid[r][c]

            if idx == -1:
                sym = "⭐"
                lbl = "FREE"
            elif is_marked:
                sym = "✅"
                lbl = pool_squares[idx]["label"]
            else:
                sym = "⬜"
                lbl = pool_squares[idx]["label"]

            symbol_row.append(sym + " " * (_COL_W - 2))
            label_row.append(lbl.ljust(_COL_W))

        lines.append("".join(symbol_row))
        lines.append("".join(label_row))
        lines.append("")

    board_text = "```\n" + "\n".join(lines).rstrip() + "\n```"

    total_cells = n * n
    total_marked = sum(marked_grid[r][c] for r in range(n) for c in range(n))

    embed = discord.Embed(
        title=title,
        description=board_text,
        colour=colour,
    )
    embed.add_field(name="Win Type", value=win_label, inline=True)
    embed.add_field(name="Squares Marked", value=f"{total_marked}/{total_cells}", inline=True)

    return embed
