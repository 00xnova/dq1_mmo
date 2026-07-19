import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from auth.routes import router as auth_router
from config import CORS_ORIGINS, HOST, PORT
from database.db import close_db, init_db
from network.message_handler import handle_message
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="DQ1 MMO Server", version="0.1.0", lifespan=lifespan)

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
    return {"status": "ok", "service": "dq1-mmo"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    character_id: int | None = None
    user_id: int | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(msg(ServerMessageType.ERROR, reason="invalid json"))
                )
                continue

            if not isinstance(data, dict):
                await websocket.send_text(
                    json.dumps(msg(ServerMessageType.ERROR, reason="message must be object"))
                )
                continue

            character_id, user_id, outbound = await handle_message(character_id, user_id, data)

            for out in outbound:
                if out.get("type") == ServerMessageType.AUTH_OK and character_id is not None:
                    await manager.connect(character_id, websocket)
                    await manager.broadcast(
                        msg(
                            ServerMessageType.PLAYER_JOINED,
                            player_id=character_id,
                            name=out.get("character", {}).get("name"),
                            x=out.get("character", {}).get("world_x"),
                            y=out.get("character", {}).get("world_y"),
                        ),
                        exclude=character_id,
                    )
                await websocket.send_text(json.dumps(out))
    except WebSocketDisconnect:
        pass
    finally:
        if character_id is not None:
            await manager.disconnect(character_id)
            await manager.broadcast(
                msg(ServerMessageType.PLAYER_LEFT, player_id=character_id),
                exclude=character_id,
            )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
