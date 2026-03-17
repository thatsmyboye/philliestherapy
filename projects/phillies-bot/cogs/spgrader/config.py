"""
Configuration for Phillies Therapy Bot.
Set these via environment variables or a .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Discord
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    CHANNEL_ID: int = int(os.getenv("CHANNEL_ID", "0"))      # #phillies-therapy channel
    LEADERBOARD_CHANNEL_ID: int = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))
    SP_GRADER_CHANNEL_ID: int = int(os.getenv("SP_GRADER_CHANNEL_ID", "0"))

    # MLB
    PHILLIES_TEAM_ID: int = 143

    # Poll interval (minutes) — used in bot.py loop
    POLL_INTERVAL_MINUTES: int = 2

    # Scoring weights (must sum to 100)
    SCORE_WEIGHTS = {
        "efficiency":         22,   # Outs recorded / outs needed
        "run_prevention":     24,   # Runs allowed (ERA-like)
        "strikeouts":         14,   # K rate
        "walk_control":       14,   # BB rate
        "strike_ball_ratio":  10,   # Strike% of all pitches
        "csw":                 8,   # Called + Swinging Strike %
        "batted_ball_quality": 8,   # Exit velo + launch angle
    }

    # Grade thresholds
    GRADE_LABELS = {
        (90, 100): ("S", "🏆"),
        (80,  90): ("A+", "⭐"),
        (70,  80): ("A",  "✅"),
        (60,  70): ("B",  "👍"),
        (50,  60): ("C",  "🙂"),
        (40,  50): ("D",  "😬"),
        (0,   40): ("F",  "💀"),
    }

    # Data file for leaderboard persistence
    DATA_FILE: str = "leaderboard.json"
