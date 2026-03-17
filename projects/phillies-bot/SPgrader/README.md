# ⚾ Phillies Therapy — SP Report Bot

A Discord bot that monitors Phillies starting pitchers in real time, waits for their outing to be fully boxed up, then fires a rich embed with their **Philly Ace Rating (PAR)** — a proprietary 0–100 grade unique to the server.

---

## Features

| Feature | Details |
|---|---|
| 🎯 Smart trigger | Polls every 2 min; waits for SP to leave *and* the inning to end |
| 📋 Box score | IP, H, R, ER, BB, K, Pitches-Strikes, CSW% |
| 🏟️ PAR score | 0–100 proprietary grade with letter (S/A+/A/B/C/D/F) |
| 📊 Breakdown | Per-component scores with visual bars |
| 📡 Statcast | Avg exit velo + launch angle when available |
| 🏆 Leaderboard | `/leaderboard` slash command — season averages or top performances |
| 🔍 Pitcher lookup | `/par <name>` for any pitcher's season profile |

---

## Philly Ace Rating (PAR) Formula

PAR is a weighted composite of 7 components, each scored 0–100:

| Component | Weight | What it measures |
|---|---|---|
| 🛡️ Run Prevention | **24%** | ERA-based; exponential decay from 0 ER |
| ⏱️ Efficiency | **22%** | Outs recorded (depth of start) — CG = 100 |
| 🔥 Strikeouts | **14%** | K/9 normalized; elite = 15+ K/9 |
| 🎯 Walk Control | **14%** | BB/9 inverted; 0 BB = 100 |
| ⚡ Strike/Ball % | **10%** | Overall pitch strike percentage |
| 🌀 CSW% | **8%** | (Called Strikes + Whiffs) / Total Pitches |
| 💥 Batted Ball Quality | **8%** | Avg exit velo + launch angle (lower = better for pitcher) |

**Grade Scale:**
```
S   90–100  🏆  Legendary
A+  80–90   ⭐  Dominant
A   70–80   ✅  Excellent
B   60–70   👍  Solid
C   50–60   🙂  League Average
D   40–50   😬  Rough
F    0–40   💀  Disaster
```

### Scoring Curves (key design decisions)

- **Efficiency**: Non-linear — rewards going deep with an accelerating bonus. 5 IP ≈ 55 pts, 7 IP ≈ 82 pts, 9 IP = 100.
- **Run Prevention**: Exponential decay `100 × e^(-0.22 × ERA)` — so 0 ERA = 100, 3.5 ERA ≈ 46.
- **Walk Control**: Exponential decay `100 × e^(-0.28 × BB/9)` — 0 walks = 100, 3.5 BB/9 ≈ 37.
- **Batted Ball Quality**: EV component (65%) + Launch Angle component (35%). Line drive zone (10–25°) is maximally penalized; grounders and pop-ups reward the pitcher.

---

## Setup

### 1. Create a Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. New Application → Bot → Reset Token → copy it
3. Enable: `Message Content Intent`, `Server Members Intent`
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands`
5. Permissions: `Send Messages`, `Embed Links`, `Read Message History`
6. Invite bot to your server

### 2. Install

```bash
git clone <your-repo>
cd phillies-bot
python -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your DISCORD_TOKEN and CHANNEL_ID
```

Right-click any channel in Discord (Developer Mode must be on in Settings → Advanced) to copy channel IDs.

### 4. Run

```bash
python bot.py
```

For production, run as a systemd service or with `screen`/`tmux`.

---

## Slash Commands

| Command | Description |
|---|---|
| `/leaderboard view:Season Averages` | Top pitchers by avg PAR this season |
| `/leaderboard view:Top Performances` | Best individual starts recorded |
| `/par pitcher:Wheeler` | Season PAR profile for a pitcher |

---

## Data Sources

- **MLB Stats API** (`statsapi.mlb.com`) — live game feed, box scores, play-by-play
- **Baseball Savant** (`baseballsavant.mlb.com`) — Statcast pitch data (exit velo, launch angle, pitch descriptions for CSW)

Both are free, public APIs. No key required.

---

## File Structure

```
phillies-bot/
├── bot.py          # Discord client + polling loop
├── monitor.py      # Game state machine (detect SP exit, wait for inning)
├── mlb_api.py      # MLB Stats API + Savant async client
├── scoring.py      # PAR formula engine
├── formatter.py    # Discord embed builder
├── leaderboard.py  # JSON persistence + leaderboard queries
├── commands.py     # Slash command definitions
├── config.py       # All settings + grade weights
├── tests.py        # Scoring unit tests
├── requirements.txt
└── .env.example
```

---

## Customizing the Formula

All weights live in `config.py → Config.SCORE_WEIGHTS`. They must sum to 100. Adjust to taste — e.g., to make strikeouts worth more, increase `strikeouts` and decrease another weight proportionally.
