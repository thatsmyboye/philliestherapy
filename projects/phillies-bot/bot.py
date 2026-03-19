"""
Phillies Therapy Discord Bot — entry point.

Loads cogs (velocity, luck, monitor), syncs slash commands to the configured
guild, and starts the bot process.

Required environment variables (.env or export):
  DISCORD_BOT_TOKEN   — bot token from Discord Developer Portal
  DISCORD_GUILD_ID    — server ID for instant guild-scoped command sync
  ALERTS_CHANNEL_ID   — channel ID where live game alerts are posted
"""
from __future__ import annotations

import asyncio
import os

from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise SystemExit(
        "[bot] DISCORD_BOT_TOKEN is not set. "
        "Add it to GitHub Actions secrets and re-run the deploy workflow, "
        "or write it to projects/phillies-bot/.env."
    )
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or "0")

COGS = [
    "cogs.velocity",
    "cogs.luck",
    "cogs.monitor",
    "cogs.standings",
    "cogs.spgrader",
    "cogs.trends",
]


class PhilliesBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        for cog in COGS:
            await self.load_extension(cog)
            print(f"[bot] Loaded cog: {cog}")

        # Sync slash commands to the guild for instant registration.
        # For global sync (all servers, up to 1-hour propagation), call without guild=.
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        print(f"[bot] Synced {len(synced)} slash command(s) to guild {GUILD_ID}.")

    async def on_ready(self) -> None:
        print(f"[bot] Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Phillies games",
            )
        )


def main() -> None:
    bot = PhilliesBot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
