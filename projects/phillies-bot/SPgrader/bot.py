"""
Phillies Therapy Discord Bot
Monitors Phillies SP performance and posts graded box scores.
"""

import discord
from discord.ext import tasks
import asyncio
import logging
from config import Config
from monitor import GameMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("PhilliesBot")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
monitor = GameMonitor()


@client.event
async def on_ready():
    log.info(f"Logged in as {client.user} | Server count: {len(client.guilds)}")
    game_check_loop.start()


@tasks.loop(minutes=2)
async def game_check_loop():
    """Poll every 2 minutes during game time, check for SP exits."""
    try:
        results = await monitor.check_games()
        for result in results:
            channel = client.get_channel(Config.CHANNEL_ID)
            if channel:
                embed, file = result
                if file:
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
                log.info(f"Posted SP report for game {result}")
    except Exception as e:
        log.exception(f"Error in game check loop: {e}")


@game_check_loop.before_loop
async def before_game_check():
    await client.wait_until_ready()


if __name__ == "__main__":
    client.run(Config.DISCORD_TOKEN)
