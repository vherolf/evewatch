from datetime import datetime
from pathlib import Path
import asyncio, aiofiles
import re
import json
import secrets
import hashlib
import base64
import webbrowser
from dataclasses import dataclass
from urllib.parse import urlencode, parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import aiohttp

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------
CLIENT_ID    = ""    # create a public app at https://developers.eveonline.com
CHARACTER_ID = 0     # your EVE character ID (Settings > About in the EVE client)
watch_jumps  = 5     # alert if hostile is within this many jumps
# ---------------------------------------------------------------------------

TOKEN_FILE   = Path.home() / '.evewatch_token'
ESI_BASE     = "https://esi.evetech.net/latest"
ESI_AUTH     = "https://login.eveonline.com"
REDIRECT_URI = "http://localhost:8765/callback"
SCOPES       = "esi-location.read_location.v1"

today      = datetime.now()
chatlogdir = list(Path.home().rglob('EVE/logs/Chatlogs')).pop()

# check for mentions of these usernames in chat
usernames = ['Vherolf']

# runtime state
current_solarsystem_id: int = 0
current_solarsystem: str    = ''

# stargate graph cache: system_id -> frozenset of neighbour system IDs
# populated lazily as we explore — each system is fetched at most once
adjacency_cache: dict[int, frozenset[int]] = {}

# name caches populated alongside the adjacency cache
id_to_name: dict[int, str] = {}
name_to_id: dict[str, int] = {}

# active watch list: system_name -> jump_distance from current position
# rebuilt every time you jump to a new system
watched_systems: dict[str, int] = {}

esi_session: aiohttp.ClientSession | None = None
esi_token: dict = {}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Channel:
    channel: str
    path: Path


@dataclass(frozen=True, slots=True)
class Message:
    timestamp: datetime
    username: str
    message: str
    channel: Channel


# ---------------------------------------------------------------------------
# ESI OAuth2 PKCE
# ---------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge


async def _catch_callback(expected_state: str) -> str:
    """Start a one-shot local HTTP server and wait for the OAuth redirect."""
    loop = asyncio.get_event_loop()
    code_future: asyncio.Future[str] = loop.create_future()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            if qs.get('state', [''])[0] == expected_state:
                loop.call_soon_threadsafe(code_future.set_result, qs['code'][0])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"EVE login successful! You can close this tab.")

        def log_message(self, *_):
            pass

    server = HTTPServer(('localhost', 8765), _Handler)
    await loop.run_in_executor(None, server.handle_request)
    server.server_close()
    return await code_future


async def _exchange_code(code: str, verifier: str) -> dict:
    async with esi_session.post(f"{ESI_AUTH}/v2/oauth/token", data={
        'grant_type':    'authorization_code',
        'code':          code,
        'client_id':     CLIENT_ID,
        'code_verifier': verifier,
    }) as resp:
        token = await resp.json()
    TOKEN_FILE.write_text(json.dumps(token))
    return token


async def _refresh(refresh_tok: str) -> dict | None:
    async with esi_session.post(f"{ESI_AUTH}/v2/oauth/token", data={
        'grant_type':    'refresh_token',
        'refresh_token': refresh_tok,
        'client_id':     CLIENT_ID,
    }) as resp:
        if resp.status == 200:
            token = await resp.json()
            TOKEN_FILE.write_text(json.dumps(token))
            return token
    return None


async def authenticate():
    global esi_token
    if TOKEN_FILE.exists():
        saved     = json.loads(TOKEN_FILE.read_text())
        refreshed = await _refresh(saved.get('refresh_token', ''))
        if refreshed:
            esi_token = refreshed
            print("ESI: token refreshed from saved file")
            return

    verifier, challenge = _pkce_pair()
    state  = secrets.token_hex(16)
    params = {
        'response_type':         'code',
        'redirect_uri':          REDIRECT_URI,
        'client_id':             CLIENT_ID,
        'scope':                 SCOPES,
        'state':                 state,
        'code_challenge':        challenge,
        'code_challenge_method': 'S256',
    }
    url = f"{ESI_AUTH}/v2/oauth/authorize?{urlencode(params)}"
    print(f"\nOpening browser for EVE SSO login...\n{url}\n")
    webbrowser.open(url)

    code      = await _catch_callback(state)
    esi_token = await _exchange_code(code, verifier)
    print("ESI: authenticated successfully")


# ---------------------------------------------------------------------------
# ESI helpers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    return {'Authorization': f"Bearer {esi_token.get('access_token', '')}"}


async def _fetch_neighbors(system_id: int) -> frozenset[int]:
    """Fetch the direct neighbours of a system and populate name caches."""
    async with esi_session.get(f"{ESI_BASE}/v4/universe/systems/{system_id}/") as resp:
        data = await resp.json()

    name = data.get('name', str(system_id))
    id_to_name[system_id] = name
    name_to_id[name]      = system_id

    # resolve each stargate to its destination system ID in parallel
    stargate_ids = data.get('stargates', [])

    async def _dest(sg_id: int) -> int:
        async with esi_session.get(f"{ESI_BASE}/v1/universe/stargates/{sg_id}/") as r:
            sg = await r.json()
            return sg['destination']['system_id']

    neighbours = await asyncio.gather(*[_dest(sg) for sg in stargate_ids])
    result = frozenset(neighbours)
    adjacency_cache[system_id] = result
    return result


async def get_neighbors(system_id: int) -> frozenset[int]:
    """Return neighbours from cache, fetching from ESI only if needed."""
    if system_id not in adjacency_cache:
        await _fetch_neighbors(system_id)
    return adjacency_cache[system_id]


async def update_watch_list(origin_id: int):
    """BFS out to watch_jumps from origin; rebuild watched_systems."""
    global watched_systems

    # BFS — visit each frontier level in parallel
    visited  = {origin_id}
    frontier = {origin_id}
    distance: dict[int, int] = {}   # system_id -> jump distance

    for jump in range(1, watch_jumps + 1):
        neighbour_sets = await asyncio.gather(*[get_neighbors(sid) for sid in frontier])
        next_frontier: set[int] = set()
        for neighbours in neighbour_sets:
            next_frontier |= neighbours - visited
        visited  |= next_frontier
        frontier  = next_frontier
        for sid in frontier:
            distance[sid] = jump

    # ensure all discovered systems have names (cache may have gaps for unvisited
    # nodes that were added only as neighbours, not yet fetched themselves)
    uncached = [sid for sid in distance if sid not in id_to_name]
    if uncached:
        await asyncio.gather(*[_fetch_neighbors(sid) for sid in uncached])

    watched_systems = {
        id_to_name[sid]: dist
        for sid, dist in distance.items()
        if sid in id_to_name
    }
    print(f"Watch list updated: {len(watched_systems)} systems within {watch_jumps} jumps of {id_to_name.get(origin_id, origin_id)}")


# ---------------------------------------------------------------------------
# Location polling
# ---------------------------------------------------------------------------

async def poll_location():
    global current_solarsystem_id, current_solarsystem, esi_token
    while True:
        try:
            async with esi_session.get(
                f"{ESI_BASE}/v2/characters/{CHARACTER_ID}/location/",
                headers=_auth_headers()
            ) as resp:
                if resp.status == 401:
                    refreshed = await _refresh(esi_token.get('refresh_token', ''))
                    if refreshed:
                        esi_token = refreshed
                    await asyncio.sleep(5)
                    continue
                data      = await resp.json()
                system_id = data.get('solar_system_id')
                if system_id and system_id != current_solarsystem_id:
                    current_solarsystem_id = system_id
                    # fetch name if not already cached
                    if system_id not in id_to_name:
                        await _fetch_neighbors(system_id)
                    current_solarsystem = id_to_name.get(system_id, str(system_id))
                    print(f'Your new location is {current_solarsystem}')
                    await update_watch_list(system_id)
        except Exception as e:
            print(f'ESI location error: {e}')
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

async def name_filter(msg):
    if any(name in msg.message for name in usernames):
        print(f"The Pilot {msg.username} wants to talk to you")


async def proximity_filter(msg):
    if not watched_systems:
        return
    for name, jumps in watched_systems.items():
        if name not in msg.message:
            continue
        label = f"RUN! ({jumps}j)" if jumps <= watch_jumps else f"ok ({jumps}j)"
        print(f'INTEL [{msg.channel.channel}]: {name} — {label}  | {msg.username}: {msg.message}')


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

async def parse_msg(raw_msg, channel) -> Message | None:
    line_parser = re.compile(r'^\s*\[\s(.*?)\s\]\s(.*?)\s>\s(.*?)$', re.DOTALL)
    m = line_parser.match(raw_msg)
    if m:
        try:
            timestamp = datetime.strptime(m.group(1), "%Y.%m.%d %H:%M:%S")
        except ValueError:
            return None
        return Message(
            timestamp=timestamp,
            username=m.group(2),
            message=m.group(3),
            channel=channel,
        )
    return None


chat_line_delimiter = u"﻿"

async def parse_log(chat):
    # utf-16 encoded EVE log; seek to end to skip historical entries
    async with aiofiles.open(chat.path, mode='r', encoding="utf-16-le") as f:
        await f.seek(0, 2)
        while True:
            line    = await f.readline()
            raw_msg = line.strip(chat_line_delimiter)
            await asyncio.sleep(0.5)
            if raw_msg:
                msg = await parse_msg(raw_msg=raw_msg, channel=chat)
                if msg:
                    match msg:
                        case Message(username='EVE System'):
                            pass  # location handled by ESI polling
                        case _:
                            await proximity_filter(msg)
                            await name_filter(msg)


async def status():
    while True:
        print('-----  STATUS -----')
        print(f'You are in {current_solarsystem} (id: {current_solarsystem_id})')
        print(f'Watching {len(watched_systems)} systems within {watch_jumps} jumps')
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    global esi_session

    if not CLIENT_ID or not CHARACTER_ID:
        print("ERROR: Set CLIENT_ID and CHARACTER_ID in the config section at the top of the file.")
        return

    chatfiles = chatlogdir.glob(f"*_{today.strftime('%Y%m%d')}*.txt")

    async with aiohttp.ClientSession() as session:
        esi_session = session

        await authenticate()

        tasks = [asyncio.create_task(poll_location())]

        for chatfile in chatfiles:
            print(f"Watching: {chatfile.name}")
            tasks.append(asyncio.create_task(parse_log(Channel(chatfile.stem, chatfile))))

        # uncomment to enable periodic status reports:
        # tasks.append(asyncio.create_task(status()))

        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
