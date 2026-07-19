#!/usr/bin/env python3
"""
Multiplayer simulator — many bot clients on one PC.

Usage (server must be running, or pass --start-server):

  cd server && source .venv/bin/activate
  python ../tools/mp_sim.py                 # 3 bots, wander 20s
  python ../tools/mp_sim.py -n 5 --seconds 30
  python ../tools/mp_sim.py -n 4 --scenario meet
  python ../tools/mp_sim.py -n 2 --interactive

Bots register unique accounts, enter the world, move, and print who they see.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

try:
    import websockets
except ImportError:
    print("Need websockets: pip install websockets")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_json(method: str, url: str, data: dict | None = None, token: str | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def wait_for_server(base: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, body = http_json("GET", f"{base}/health")
            if st == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------------------
# Bot client
# ---------------------------------------------------------------------------

WALKABLE = {0, 2, 4}  # field, town, dungeon — mirrored from server map


@dataclass
class Bot:
    index: int
    base_http: str
    base_ws: str
    email: str = ""
    password: str = "password"
    username: str = ""
    token: str = ""
    char_id: int = 0
    name: str = ""
    x: int = 2
    y: int = 2
    level: int = 1
    seq: int = 0
    nearby: dict[int, dict] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    ws: Any = None
    connected: bool = False
    in_combat: bool = False
    map_tiles: list[list[int]] | None = None
    alive: bool = True

    def note(self, msg: str) -> None:
        line = f"[B{self.index}:{self.name or '?'}] {msg}"
        self.log.append(line)
        print(line, flush=True)

    def setup_account(self) -> None:
        tag = f"{int(time.time()) % 100000}_{self.index}"
        self.email = f"bot{tag}@example.com"
        self.username = f"Bot{self.index}_{tag[-4:]}"
        self.name = f"H{self.index}_{tag[-5:]}"

        st, reg = http_json(
            "POST",
            f"{self.base_http}/auth/register",
            {"email": self.email, "password": self.password, "username": self.username},
        )
        if st == 400 and isinstance(reg, dict) and "already" in str(reg).lower():
            st, reg = http_json(
                "POST",
                f"{self.base_http}/auth/login",
                {"email": self.email, "password": self.password},
            )
        if st not in (200, 201):
            raise RuntimeError(f"auth failed: {st} {reg}")
        self.token = reg["access_token"]

        st, ch = http_json(
            "POST",
            f"{self.base_http}/auth/characters",
            {"name": self.name},
            token=self.token,
        )
        if st == 400:
            st, chars = http_json("GET", f"{self.base_http}/auth/characters", token=self.token)
            if st != 200 or not chars:
                raise RuntimeError(f"no character: {ch}")
            ch = chars[0]
            self.name = ch["name"]
        elif st != 201:
            raise RuntimeError(f"create char failed: {st} {ch}")

        self.char_id = ch["id"]
        self.x = int(ch.get("world_x", 2))
        self.y = int(ch.get("world_y", 2))
        self.level = int(ch.get("level", 1))
        self.note(f"account ready char_id={self.char_id} at ({self.x},{self.y})")

    def walkable(self, x: int, y: int) -> bool:
        if not self.map_tiles:
            return 0 <= x < 20 and 0 <= y < 12
        if y < 0 or y >= len(self.map_tiles):
            return False
        row = self.map_tiles[y]
        if x < 0 or x >= len(row):
            return False
        return row[x] in WALKABLE

    async def connect(self) -> None:
        self.ws = await websockets.connect(self.base_ws, open_timeout=10, max_size=2**20)
        self.connected = True
        await self.send({"type": "auth", "token": self.token, "character_id": self.char_id})
        # reader task
        asyncio.create_task(self._reader())

    async def send(self, msg: dict) -> None:
        if self.ws is None:
            return
        await self.ws.send(json.dumps(msg))

    async def _reader(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._on_message(data)
        except Exception as exc:
            if self.alive:
                self.note(f"ws closed: {exc}")
            self.connected = False

    async def _on_message(self, data: dict) -> None:
        t = data.get("type")
        if t == "auth_ok":
            ch = data.get("character") or {}
            self.x = int(ch.get("world_x", self.x))
            self.y = int(ch.get("world_y", self.y))
            self.level = int(ch.get("level", self.level))
            if data.get("map") and data["map"].get("tiles"):
                self.map_tiles = data["map"]["tiles"]
            self.note(f"auth_ok at ({self.x},{self.y}) in_combat={data.get('in_combat')}")
            if data.get("in_combat"):
                self.in_combat = True
        elif t == "world_state":
            self.nearby = {}
            for p in data.get("players") or []:
                self.nearby[int(p["id"])] = p
            if data.get("map") and data["map"].get("tiles"):
                self.map_tiles = data["map"]["tiles"]
            if data.get("you"):
                self.x = int(data["you"]["x"])
                self.y = int(data["you"]["y"])
            names = [p.get("name") for p in self.nearby.values()]
            self.note(f"world_state nearby={len(self.nearby)} {names}")
        elif t == "move_ok":
            if data.get("ok"):
                self.x = int(data["x"])
                self.y = int(data["y"])
            else:
                self.x = int(data.get("x", self.x))
                self.y = int(data.get("y", self.y))
                if data.get("reason") not in (None, "rate_limit", "duplicate"):
                    self.note(f"move rejected: {data.get('reason')}")
        elif t == "player_joined":
            pid = int(data["player_id"])
            self.nearby[pid] = {
                "id": pid,
                "name": data.get("name"),
                "world_x": data.get("x"),
                "world_y": data.get("y"),
                "level": data.get("level"),
            }
            self.note(f"SEE JOIN {data.get('name')} at ({data.get('x')},{data.get('y')})")
        elif t == "player_left":
            pid = int(data["player_id"])
            left = self.nearby.pop(pid, None)
            self.note(f"SEE LEAVE {left.get('name') if left else pid}")
        elif t == "player_moved":
            pid = int(data["player_id"])
            if pid == self.char_id:
                return
            entry = self.nearby.get(pid) or {"id": pid, "name": f"P{pid}"}
            entry["world_x"] = data.get("x")
            entry["world_y"] = data.get("y")
            self.nearby[pid] = entry
        elif t == "combat_start" or t == "combat_resume":
            self.in_combat = True
            en = (data.get("enemy") or {}).get("name", "?")
            self.note(f"COMBAT vs {en}")
        elif t == "combat_end":
            self.in_combat = False
            self.note(f"combat end: {data.get('result')}")
        elif t == "error":
            if data.get("reason") not in ("rate_limit", "wait for your turn"):
                self.note(f"error: {data.get('reason')}")

    async def step(self, dx: int, dy: int) -> None:
        if self.in_combat or not self.connected:
            return
        nx, ny = self.x + dx, self.y + dy
        if not self.walkable(nx, ny):
            return
        self.seq += 1
        # optimistic
        self.x, self.y = nx, ny
        await self.send({"type": "move", "x": nx, "y": ny, "seq": self.seq})

    async def random_walk(self) -> None:
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        random.shuffle(dirs)
        for dx, dy in dirs:
            nx, ny = self.x + dx, self.y + dy
            if self.walkable(nx, ny):
                await self.step(dx, dy)
                return

    async def go_toward(self, tx: int, ty: int) -> bool:
        """One step toward target. Returns True if arrived."""
        if self.x == tx and self.y == ty:
            return True
        dx = 0 if self.x == tx else (1 if tx > self.x else -1)
        dy = 0 if self.y == ty else (1 if ty > self.y else -1)
        # prefer axis with larger distance
        if abs(tx - self.x) >= abs(ty - self.y):
            if self.walkable(self.x + dx, self.y):
                await self.step(dx, 0)
            elif dy and self.walkable(self.x, self.y + dy):
                await self.step(0, dy)
            else:
                await self.random_walk()
        else:
            if dy and self.walkable(self.x, self.y + dy):
                await self.step(0, dy)
            elif dx and self.walkable(self.x + dx, self.y):
                await self.step(dx, 0)
            else:
                await self.random_walk()
        return self.x == tx and self.y == ty

    async def fight_if_needed(self) -> None:
        if not self.in_combat:
            return
        await self.send({"type": "attack"})

    async def close(self) -> None:
        self.alive = False
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        self.connected = False


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

async def scenario_wander(bots: list[Bot], seconds: float) -> None:
    print(f"\n=== WANDER {len(bots)} bots for {seconds:.0f}s ===\n")
    end = time.time() + seconds
    while time.time() < end:
        for b in bots:
            if b.in_combat:
                await b.fight_if_needed()
            else:
                await b.random_walk()
        await asyncio.sleep(0.18)
        _print_snapshot(bots)
    _print_visibility_report(bots)


async def scenario_aoi(bots: list[Bot], seconds: float = 40.0) -> None:
    """Bot0 stays in town; Bot1 walks from far field into range — must get joins."""
    if len(bots) < 2:
        print("AOI needs at least 2 bots")
        return
    print(f"\n=== AOI enter-range test ({len(bots)} bots) ===\n")
    a, b = bots[0], bots[1]
    # Park A at town
    for _ in range(40):
        if a.x == 3 and a.y == 3:
            break
        await a.go_toward(3, 3)
        await asyncio.sleep(0.12)
    # Send B toward dungeon edge (far), then back to A
    far = (14, 8)
    for _ in range(80):
        if b.in_combat:
            await b.fight_if_needed()
        elif await b.go_toward(*far):
            break
        await asyncio.sleep(0.12)
    await asyncio.sleep(0.3)
    print(f"  After split: A@({a.x},{a.y}) sees {len(a.nearby)} | B@({b.x},{b.y}) sees {len(b.nearby)}")
    # Walk B back to A
    end = time.time() + seconds
    saw_join = False
    while time.time() < end:
        if b.in_combat:
            await b.fight_if_needed()
        else:
            await b.go_toward(a.x, a.y)
        if a.char_id in b.nearby and b.char_id in a.nearby:
            saw_join = True
            print(f"\n*** AOI SUCCESS: mutual visibility at A({a.x},{a.y}) B({b.x},{b.y}) ***\n")
            break
        await asyncio.sleep(0.14)
        _print_snapshot(bots)
    if not saw_join:
        print("\n*** AOI FAIL: never gained mutual visibility ***\n")
    _print_visibility_report(bots[:2])


async def scenario_meet(bots: list[Bot], seconds: float = 25.0) -> None:
    """All bots path toward town square (3,3) so they must see each other."""
    print(f"\n=== MEET at town (3,3) — {len(bots)} bots ===\n")
    target = (3, 3)
    end = time.time() + seconds
    while time.time() < end:
        all_there = True
        for b in bots:
            if b.in_combat:
                await b.fight_if_needed()
                all_there = False
                continue
            arrived = await b.go_toward(*target)
            if not arrived:
                all_there = False
        await asyncio.sleep(0.16)
        _print_snapshot(bots)
        if all_there and _everyone_sees_everyone(bots):
            print("\n*** SUCCESS: all bots at meet point and see each other ***\n")
            break
    _print_visibility_report(bots)


async def scenario_interactive(bots: list[Bot]) -> None:
    print(
        """
Interactive multiplayer sim
  status          — positions + who each bot sees
  move <i> <dir>  — n/s/e/w for bot i (0-based)
  wander          — one random step all
  meet            — path all toward (3,3) for 15s
  attack <i>      — bot i attacks if in combat
  sync            — all request presence sync
  quit
"""
    )
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("mp> ").strip())
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        if cmd in ("q", "quit", "exit"):
            break
        if cmd == "status":
            _print_snapshot(bots)
            _print_visibility_report(bots)
        elif cmd == "wander":
            for b in bots:
                await b.random_walk()
            await asyncio.sleep(0.2)
            _print_snapshot(bots)
        elif cmd == "meet":
            await scenario_meet(bots, 15)
        elif cmd == "sync":
            for b in bots:
                await b.send({"type": "sync"})
            await asyncio.sleep(0.3)
            _print_snapshot(bots)
        elif cmd == "move" and len(parts) >= 3:
            i = int(parts[1])
            d = parts[2].lower()
            delta = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}.get(d)
            if delta and 0 <= i < len(bots):
                await bots[i].step(*delta)
                await asyncio.sleep(0.15)
                _print_snapshot(bots)
        elif cmd == "attack" and len(parts) >= 2:
            i = int(parts[1])
            if 0 <= i < len(bots):
                await bots[i].send({"type": "attack"})
                await asyncio.sleep(0.2)
        else:
            print("unknown command")


def _print_snapshot(bots: list[Bot]) -> None:
    parts = []
    for b in bots:
        flag = "C" if b.in_combat else " "
        parts.append(f"{b.name}{flag}({b.x},{b.y}) sees:{len(b.nearby)}")
    print("  | " + " · ".join(parts), flush=True)


def _everyone_sees_everyone(bots: list[Bot]) -> bool:
    ids = {b.char_id for b in bots}
    for b in bots:
        others = ids - {b.char_id}
        seen = set(b.nearby.keys())
        if not others.issubset(seen):
            return False
    return True


def _print_visibility_report(bots: list[Bot]) -> None:
    print("\n--- Visibility report ---")
    ids = {b.char_id: b.name for b in bots}
    ok = True
    for b in bots:
        missing = []
        for oid, oname in ids.items():
            if oid == b.char_id:
                continue
            if oid not in b.nearby:
                missing.append(oname)
        if missing:
            ok = False
            print(f"  {b.name} MISSING: {missing}")
        else:
            seen = [ids.get(i, i) for i in b.nearby]
            print(f"  {b.name} sees all ({seen})")
    if ok and len(bots) > 1:
        print("  RESULT: full mutual visibility ✓")
    elif len(bots) == 1:
        print("  RESULT: single bot (nothing to see)")
    else:
        print("  RESULT: incomplete visibility (bots may be far apart — try --scenario meet)")
    print("-------------------------\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def amain(args: argparse.Namespace) -> int:
    base_http = args.http.rstrip("/")
    base_ws = args.ws or base_http.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

    if not wait_for_server(base_http, timeout=args.wait):
        print(f"Server not reachable at {base_http}/health")
        print("Start it with:  cd server && ./run.sh")
        return 1

    st, health = http_json("GET", f"{base_http}/health")
    print(f"Server OK: {health}")

    bots = [
        Bot(index=i, base_http=base_http, base_ws=base_ws)
        for i in range(args.n)
    ]
    for b in bots:
        b.setup_account()

    print(f"\nConnecting {len(bots)} bots to {base_ws} ...")
    await asyncio.gather(*(b.connect() for b in bots))
    await asyncio.sleep(0.5)

    # initial sync
    for b in bots:
        await b.send({"type": "sync"})
    await asyncio.sleep(0.4)

    try:
        if args.interactive:
            await scenario_interactive(bots)
        elif args.scenario == "meet":
            await scenario_meet(bots, args.seconds)
        elif args.scenario == "aoi":
            await scenario_aoi(bots, args.seconds)
        else:
            await scenario_wander(bots, args.seconds)
    finally:
        for b in bots:
            await b.close()

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DQ1 MMO multiplayer bot simulator")
    p.add_argument("-n", type=int, default=3, help="number of bots (default 3)")
    p.add_argument("--seconds", type=float, default=20.0, help="duration for auto scenarios")
    p.add_argument(
        "--scenario",
        choices=("wander", "meet", "aoi"),
        default="meet",
        help="auto scenario: meet | wander | aoi (default: meet)",
    )
    p.add_argument("-i", "--interactive", action="store_true", help="interactive command prompt")
    p.add_argument("--http", default="http://127.0.0.1:8000", help="HTTP base URL")
    p.add_argument("--ws", default="", help="WebSocket URL (default derived from --http)")
    p.add_argument("--wait", type=float, default=8.0, help="seconds to wait for server")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(amain(args)))
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
