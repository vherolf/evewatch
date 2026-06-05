# evewatch

Asyncio-based EVE Online intel monitor. Watches your chat log files in real time and alerts you when hostiles are reported in systems near you. Uses the EVE ESI API to track your live position and automatically build a watch list of surrounding systems.

---

## Features

- **Live position tracking** via ESI — knows where you are without parsing chat logs
- **Auto-updating watch list** — on every jump, builds a map of all systems within `watch_jumps` using the stargate graph; no manual system lists to maintain
- **Intel channel monitoring** — parses all today's chat logs asynchronously; fires an alert the moment a watched system name appears
- **Name mention alert** — notifies you when another pilot mentions your name in chat

---

## Install / Update

```bash
curl -fsSL https://raw.githubusercontent.com/vherolf/evewatch/main/install.sh | bash
```

Run the same command to update — it re-downloads the files and refreshes the venv. Your config at `~/.evewatch.json` is never touched on update.

On first install the script opens `~/.evewatch.json` in your terminal editor with step-by-step instructions for getting the credentials.

**Requirements:** Python 3.10+, curl

---

## Configuration

All configuration lives in `~/.evewatch.json`. On the first run the file is created automatically with defaults — edit it, then run again.

```json
{
  "client_id":    "your_esi_client_id",
  "character_id": 123456789,
  "watch_jumps":  5,
  "usernames":    ["YourCharacterName"],
  "token":        {}
}
```

The `token` field is managed automatically — evewatch writes and refreshes it. Do not edit it manually.

### 1. Create an ESI application

1. Go to [developers.eveonline.com](https://developers.eveonline.com) and log in
2. Click **Create New Application**
3. Set **Connection Type** to `Authentication & API Access`
4. Add the scope: `esi-location.read_location.v1`
5. Set the **Callback URL** to: `http://localhost:8765/callback`
6. Save — copy the **Client ID** into `client_id`

No client secret is needed (the app uses PKCE, a public OAuth2 flow).

### 2. Find your Character ID

In the EVE client: **Esc → About → Character ID**, or look it up on [zkillboard.com](https://zkillboard.com).  
Paste the number into `character_id`.

### 3. Set your jump range

```json
"watch_jumps": 5
```

Systems within this many jumps trigger a `RUN!` alert. Systems further away are shown as `ok (Nj)`.

### 4. Configure your username

```json
"usernames": ["YourCharacterName"]
```

---

## First run

```bash
source venv/bin/activate
python3 evewatch.py
```

On the first run a browser window opens for EVE SSO login. After you authorise, the token is saved to `~/.evewatch_token` and refreshed automatically on subsequent runs — you won't be asked again unless the token expires completely.

---

## How it works

### Position tracking

Every 5 seconds evewatch polls `GET /characters/{id}/location/` from the ESI API. When your solar system changes it triggers a watch list rebuild.

### Watch list (stargate graph BFS)

When you jump to a new system, evewatch does a breadth-first search over the EVE stargate graph up to `watch_jumps` deep:

1. Fetch the new system's stargates from ESI → get all direct neighbours (1 jump)
2. Fetch each neighbour's stargates in parallel → get all systems at 2 jumps
3. Repeat up to `watch_jumps`

Each system is fetched from ESI **once** and cached for the whole session. After a few jumps the cache is warm and watch list rebuilds are nearly instant.

The result is a dict of `{system_name: jump_distance}` that is always centred on your current position.

### Intel channel monitoring

evewatch opens every chat log file from today asynchronously and tails it from the end (skipping history). When a new line arrives:

1. The message is parsed with a regex (credit: [py-eve-chat-mon](https://github.com/andrewpmartinez/py-eve-chat-mon))
2. The text is scanned for any system name in the current watch list
3. If found — the jump distance is printed to the console

Example output when a hostile is spotted:

```
INTEL [D-W7F0 Intel]: MVCJ-E — RUN! (3j)  | SomePilot: MVCJ-E 2 ceptors
```

Systems beyond `watch_jumps` are reported as `ok (Nj)` — useful to see the intel without the alarm.

### Authentication

EVE SSO uses OAuth2 with PKCE (no client secret). On first run a local HTTP server listens on port 8765 to catch the callback. The access token is refreshed automatically using the stored refresh token.

