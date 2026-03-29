"""
Board generation and rendering for Phillies Bingo.

Each player gets a unique 5×5 layout — same 24 pool squares as everyone else
but shuffled into a personal arrangement.  The center cell [2][2] is always
FREE (stored as index -1).
"""
from __future__ import annotations

import random

import discord

from .events import make_fingerprint, WIN_TYPE_LABELS
from .win_checker import build_marked_grid

# Column width for the board code-block (monospace alignment).
# 5 chars × 5 columns = 25 chars total — fits comfortably inside Discord
# mobile's code-block width (~28 display chars on iPhone 15).
# Each cell: emoji (2 display units) + 3 spaces = 5 display units.
_COL_W = 5


def generate_layout(pool_size: int, user_seed: str) -> list[list[int]]:
    """
    Shuffle pool indices 0..(pool_size-1) into a unique 5×5 grid for a player.

    The center position [2][2] is always -1 (FREE).
    user_seed should be f"{user_id}:{game_date}" for per-player reproducibility.

    Returns a 5×5 list of lists of int (pool indices or -1).
    """
    assert pool_size == 24, "Pool must contain exactly 24 squares."
    rng = random.Random(user_seed)
    indices = list(range(pool_size))
    rng.shuffle(indices)

    # Build flat 25-cell list: insert FREE (-1) at center position 12
    cells: list[int] = indices[:12] + [-1] + indices[12:]
    # Reshape into 5×5
    return [cells[r * 5:(r + 1) * 5] for r in range(5)]


def render_board_embed(
    layout: list[list[int]],
    pool_squares: list[dict],
    marked_fingerprints: set[str],
    display_name: str,
    win_type: str,
    bingo_achieved: bool,
) -> discord.Embed:
    """
    Build the ephemeral board embed shown by /bingo check.

    Layout uses a monospace code block with two lines per board row:
      Line 1 — status symbols: ✅  ⬜  ⭐  ⬜  ✅
      Line 2 — cell labels:    TuHR ~BB FREE ~DP ScCS
    """
    win_label = WIN_TYPE_LABELS.get(win_type, win_type)

    if bingo_achieved:
        title = f"🎉 {display_name}'s Bingo Board — BINGO!"
        colour = discord.Colour.gold()
    else:
        title = f"🎱 {display_name}'s Bingo Board"
        colour = discord.Colour.red()

    marked_grid = build_marked_grid(layout, pool_squares, marked_fingerprints)

    lines: list[str] = []
    # Header
    header = "".join(c.ljust(_COL_W) for c in ["B", "I", "N", "G", "O"])
    lines.append(header)
    lines.append("")

    for r in range(5):
        symbol_row: list[str] = []
        label_row: list[str] = []
        for c in range(5):
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

            # Emoji are 2 monospace units wide; pad with _COL_W-2 spaces so
            # the symbol row aligns with the label row below it.
            symbol_row.append(sym + " " * (_COL_W - 2))
            label_row.append(lbl.ljust(_COL_W))

        lines.append("".join(symbol_row))
        lines.append("".join(label_row))
        lines.append("")

    board_text = "```\n" + "\n".join(lines).rstrip() + "\n```"

    # Count marked squares (FREE always counts)
    total_marked = sum(marked_grid[r][c] for r in range(5) for c in range(5))

    embed = discord.Embed(
        title=title,
        description=board_text,
        colour=colour,
    )
    embed.add_field(name="Win Type", value=win_label, inline=True)
    embed.add_field(name="Squares Marked", value=f"{total_marked}/25", inline=True)

    return embed
