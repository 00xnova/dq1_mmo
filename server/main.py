import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from auth.routes import router as auth_router
from config import CORS_ORIGINS, HOST, PORT, VERSION
from database.db import close_db, init_db
from game.combat_engine import combat_engine, reset_combat_engine
from network.message_handler import handle_disconnect, handle_message
from network.presence import start_presence_tasks, stop_presence_tasks
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager, reset_manager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dq1")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fresh multiplayer state each process/start (prevents cross-test leakage).
    reset_manager()
    reset_combat_engine()
    db_gen = await init_db()
    start_presence_tasks()
    try:
        yield
    finally:
        try:
            await stop_presence_tasks()
        except Exception:
            log.exception("stop_presence_tasks failed")
        try:
            reset_manager()
            reset_combat_engine()
        except Exception:
            log.exception("reset multiplayer state failed")
        try:
            await close_db(db_gen)
        except Exception:
            log.exception("close_db failed")


app = FastAPI(title="DQ1 MMO Server", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/health")
async def health():
    import time as _time

    from config import PROCESS_STARTED_AT

    return {
        "status": "ok",
        "service": "dq1-mmo",
        "version": VERSION,
        "online": len(manager.online_ids()),
        "zones": manager.zone_counts(),
        "combats": len(combat_engine.active),
        "uptime": max(0, int(_time.time() - PROCESS_STARTED_AT)),
    }


@app.get("/world/map")
async def world_map():
    from game.world_manager import map_payload

    return map_payload()


def _json_safe(obj):
    return json.loads(json.dumps(obj, default=str))


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(_json_safe(payload)))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    character_id: int | None = None
    user_id: int | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 16_384:
                await _send(websocket, msg(ServerMessageType.ERROR, reason="message too large"))
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, msg(ServerMessageType.ERROR, reason="invalid json"))
                continue

            if not isinstance(data, dict) or "type" not in data:
                await _send(
                    websocket,
                    msg(ServerMessageType.ERROR, reason="message must be object with type"),
                )
                continue

            # Heartbeats + lightweight presence must never be rate-limited
            msg_type = data.get("type")
            _exempt = (
                "ping",
                "pong",
                "sync",
                "who",
                "players",
                "online_list",
                "near",
                "nearby_list",
                "here",
                "zone",
                "where",
                "area",
                "whereami",
                "coords",
                "pos",
                "position",
                "counts",
                "census",
                "population",
                "look",
                "examine",
                "status",
                "me",
                "whoami",
                "stats",
                "sheet",
                "gold",
                "money",
                "wallet",
                "hp",
                "mp",
                "vitals",
                "life",
                "xp",
                "exp",
                "level",
                "experience",
                "spells",
                "magic",
                "spell_list",
                "inventory",
                "bag",
                "inv",
                "items",
                "version",
                "ver",
                "about",
                "time",
                "uptime",
                "servertime",
                "clock",
                "find",
                "search",
                "help",
                "commands",
                "ignore",
                "unignore",
                "ignores",
                "mute",
                "unmute",
                "block",
                "unblock",
                "ignore_list",
                "reply",
                "lastwhisper",
                "last_whisper",
                "last",
                "reply_to",
                "who_last",
                "roll",
                "dice",
                "d100",
                "discard",
                "drop",
                "destroy",
                "throw_away",
                "motd",
                "message_of_the_day",
                "rules",
                "afk",
                "away",
                "back",
                "quit",
                "logout",
                "exit",
                "leave_world",
            )
            if character_id is not None and msg_type not in _exempt:
                if not manager.allow_message(character_id):
                    await _send(websocket, msg(ServerMessageType.ERROR, reason="rate_limit"))
                    continue
            elif character_id is not None and msg_type in _exempt:
                manager.touch(character_id)

            try:
                character_id, user_id, outbound, connect_meta = await handle_message(
                    character_id, user_id, data
                )
            except Exception as exc:
                log.exception("handle_message failed")
                await _send(
                    websocket, msg(ServerMessageType.ERROR, reason=f"server error: {exc}")
                )
                continue

            if connect_meta is not None:
                from game.world_manager import map_payload

                peers = await manager.connect(
                    connect_meta["character_id"],
                    websocket,
                    name=connect_meta["name"],
                    x=connect_meta["x"],
                    y=connect_meta["y"],
                    map_id=connect_meta["map_id"],
                    level=connect_meta["level"],
                    in_combat=bool(connect_meta.get("in_combat")),
                )

                # Drop placeholder world_state from handler
                outbound = [
                    o for o in outbound if o.get("type") != ServerMessageType.WORLD_STATE
                ]

                # Notify peers that can see us (AOI already linked in connect)
                # Full snapshot for joining client
                from game.world_manager import zone_at as _zone_at

                try:
                    join_zone = _zone_at(int(connect_meta["x"]), int(connect_meta["y"]))
                except Exception:
                    join_zone = None
                sid = manager.session_id(connect_meta["character_id"])
                join_payload = msg(
                    ServerMessageType.PLAYER_JOINED,
                    player_id=connect_meta["character_id"],
                    name=connect_meta["name"],
                    x=connect_meta["x"],
                    y=connect_meta["y"],
                    level=connect_meta["level"],
                    in_combat=bool(connect_meta.get("in_combat")),
                    idle=False,
                )
                if join_zone:
                    join_payload["zone"] = join_zone
                if sid is not None:
                    join_payload["session_id"] = sid
                for p in peers:
                    await manager.send(p["id"], join_payload)
                # Soft-grace restore snapshot for client multiplayer UI
                ignores_snap = manager.ignore_list(connect_meta["character_id"])
                lw_id, lw_name = manager.last_whisper_from(connect_meta["character_id"])
                last_whisper = None
                if lw_id is not None or lw_name:
                    last_whisper = {"id": lw_id, "name": lw_name}
                outbound.append(
                    msg(
                        ServerMessageType.WORLD_STATE,
                        players=peers,
                        enemies=[],
                        map=map_payload(),
                        you={
                            "x": connect_meta["x"],
                            "y": connect_meta["y"],
                            "zone": join_zone,
                        },
                        online=len(manager.online_ids()),
                        nearby_count=len(peers),
                        zones=manager.zone_counts(),
                        roster=manager.online_roster(),
                        repel=manager.repel_remaining(connect_meta["character_id"]),
                        radiant=manager.radiant_remaining(connect_meta["character_id"]),
                        zone=join_zone,
                        session_id=sid,
                        ignores=ignores_snap,
                        last_whisper=last_whisper,
                    )
                )
                # Stamp session id + multiplayer welcome on auth_ok (not a chat
                # line — avoids polluting the chat stream for clients/tests).
                online_n = len(manager.online_ids())
                hero = str(connect_meta.get("name") or "Hero")
                zone_bit = f" in the {join_zone}" if join_zone else ""
                heroes = "hero" if online_n == 1 else "heroes"
                nearby_n = len(peers)
                near_bit = f", {nearby_n} nearby" if nearby_n else ""
                welcome = (
                    f"Welcome, {hero}! {online_n} {heroes} online{zone_bit}{near_bit}."
                )
                for o in outbound:
                    if o.get("type") == ServerMessageType.AUTH_OK:
                        o["session_id"] = sid
                        o["online"] = online_n
                        o["nearby_count"] = nearby_n
                        o["zones"] = manager.zone_counts()
                        o["welcome"] = welcome
                        o["ignores"] = ignores_snap
                        o["last_whisper"] = last_whisper
                        o["repel"] = manager.repel_remaining(
                            connect_meta["character_id"]
                        )
                        o["radiant"] = manager.radiant_remaining(
                            connect_meta["character_id"]
                        )

            # Deliver auth_ok / world_state / combat_resume BEFORE any global pulse so
            # clients always see auth_ok as the first post-auth message (not `online`).
            send_failed = False
            for out in outbound:
                try:
                    await _send(websocket, out)
                except Exception:
                    log.warning(
                        "send failed for character=%s type=%s",
                        character_id,
                        out.get("type"),
                    )
                    send_failed = True
                    break
            if send_failed:
                break

            if connect_meta is not None:
                # Re-announce combat flag after soft reconnect so AOI peers stay correct
                if connect_meta.get("in_combat"):
                    try:
                        await manager.publish_status(
                            connect_meta["character_id"], pulse_online=True
                        )
                    except Exception:
                        log.exception("publish_status on combat reconnect failed")
                # Roster pulse after the joiner already received auth_ok + world_state
                try:
                    await manager.broadcast_online()
                except Exception:
                    log.exception("broadcast_online failed")

    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        # Starlette raises when receive() is called after the socket died mid-loop
        if "not connected" not in str(exc).lower():
            log.exception("websocket runtime error")
    except Exception:
        log.exception("websocket loop crashed")
    finally:
        if character_id is not None and manager.owns(character_id, websocket):
            try:
                await handle_disconnect(character_id)
            except Exception:
                log.exception("handle_disconnect failed for %s", character_id)
            try:
                await manager.disconnect(character_id, websocket)
            except Exception:
                log.exception("manager.disconnect failed for %s", character_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
