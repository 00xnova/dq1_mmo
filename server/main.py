import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from auth.routes import router as auth_router
from config import CORS_ORIGINS, HOST, PORT, VERSION
from database.db import close_db, init_db
from game.combat_engine import combat_engine
from network.message_handler import handle_disconnect, handle_message
from network.presence import start_presence_tasks, stop_presence_tasks
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dq1")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    start_presence_tasks()
    yield
    await stop_presence_tasks()
    await close_db()


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
    return {
        "status": "ok",
        "service": "dq1-mmo",
        "version": VERSION,
        "online": len(manager.online_ids()),
        "combats": len(combat_engine.active),
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

            if character_id is not None and not manager.allow_message(character_id):
                await _send(websocket, msg(ServerMessageType.ERROR, reason="rate_limit"))
                continue

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
                )

                # Drop placeholder world_state from handler
                outbound = [
                    o for o in outbound if o.get("type") != ServerMessageType.WORLD_STATE
                ]

                # Notify peers that can see us (AOI already linked in connect)
                join_payload = msg(
                    ServerMessageType.PLAYER_JOINED,
                    player_id=connect_meta["character_id"],
                    name=connect_meta["name"],
                    x=connect_meta["x"],
                    y=connect_meta["y"],
                    level=connect_meta["level"],
                )
                for p in peers:
                    await manager.send(p["id"], join_payload)

                # Full snapshot for joining client
                outbound.append(
                    msg(
                        ServerMessageType.WORLD_STATE,
                        players=peers,
                        enemies=[],
                        map=map_payload(),
                        you={"x": connect_meta["x"], "y": connect_meta["y"]},
                        online=len(manager.online_ids()),
                    )
                )

            for out in outbound:
                await _send(websocket, out)

    except WebSocketDisconnect:
        pass
    finally:
        if character_id is not None and manager.owns(character_id, websocket):
            await handle_disconnect(character_id)
            # disconnect notifies AOI peers with player_left
            await manager.disconnect(character_id, websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
