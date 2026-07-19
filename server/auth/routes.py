import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.google_sso import (
    exchange_code,
    get_authorization_url,
    is_configured,
    verify_id_token,
)
from auth.jwt_handler import create_access_token, decode_access_token
from auth.local_auth import hash_password, verify_password
from config import STARTING_GOLD
from database.db import db_write, get_db
from game.world_manager import SPAWN_X, SPAWN_Y
from models.player import (
    CharacterCreate,
    CharacterOut,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

_oauth_states: set[str] = set()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    db = await get_db()
    async with db.execute(
        "SELECT id, email, username FROM users WHERE id = ?",
        (payload["user_id"],),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {"id": row["id"], "email": row["email"], "username": row["username"]}


def _row_to_character(row) -> CharacterOut:
    return CharacterOut(
        id=row["id"],
        name=row["name"],
        level=row["level"],
        experience=row["experience"],
        strength=row["strength"],
        agility=row["agility"],
        max_hp=row["max_hp"],
        max_mp=row["max_mp"],
        current_hp=row["current_hp"],
        current_mp=row["current_mp"],
        gold=row["gold"],
        world_x=row["world_x"],
        world_y=row["world_y"],
        map_id=row["map_id"],
        equipment_weapon=row["equipment_weapon"],
        equipment_armor=row["equipment_armor"],
        equipment_shield=row["equipment_shield"],
        equipment_helmet=row["equipment_helmet"],
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister):
    try:
        password_hash = await hash_password(body.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="Password too long") from None

    email = body.email.lower().strip()
    username = body.username.strip()

    try:
        async with db_write() as db:
            async with db.execute(
                "SELECT id FROM users WHERE email = ? COLLATE NOCASE",
                (email,),
            ) as c:
                if await c.fetchone():
                    raise HTTPException(status_code=400, detail="Email already registered")
            async with db.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ) as c:
                if await c.fetchone():
                    raise HTTPException(status_code=400, detail="Username already taken")

            cursor = await db.execute(
                "INSERT INTO users (email, password_hash, username) VALUES (?, ?, ?)",
                (email, password_hash, username),
            )
            await db.commit()
            user_id = cursor.lastrowid
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email or username already taken") from None

    token = create_access_token(user_id, username)
    return TokenResponse(access_token=token, user_id=user_id, username=username)


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    email = body.email.lower().strip()
    db = await get_db()
    async with db.execute(
        "SELECT id, password_hash, username FROM users WHERE email = ? COLLATE NOCASE",
        (email,),
    ) as c:
        row = await c.fetchone()
    if row is None or not row["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not await verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(row["id"], row["username"])
    return TokenResponse(access_token=token, user_id=row["id"], username=row["username"])


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return UserOut(id=user["id"], email=user["email"], username=user["username"])


@router.get("/google/status")
async def google_status():
    return {"configured": is_configured()}


@router.get("/google/login")
async def google_login():
    if not is_configured():
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    state = secrets.token_urlsafe(24)
    _oauth_states.add(state)
    return {"url": get_authorization_url(state)}


@router.get("/google/callback")
async def google_callback(code: str = Query(...), state: str = Query(...)):
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    _oauth_states.discard(state)

    try:
        token_data = await exchange_code(code)
        profile = await verify_id_token(token_data["id_token"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google auth failed: {exc}") from exc

    if not profile.get("email_verified", True):
        raise HTTPException(status_code=400, detail="Google email not verified")

    email = profile["email"].lower()
    async with db_write() as db:
        async with db.execute(
            "SELECT id, username FROM users WHERE google_id = ? OR email = ? COLLATE NOCASE",
            (profile["google_id"], email),
        ) as c:
            row = await c.fetchone()

        if row:
            user_id = row["id"]
            username = row["username"]
            await db.execute(
                "UPDATE users SET google_id = COALESCE(google_id, ?) WHERE id = ?",
                (profile["google_id"], user_id),
            )
            await db.commit()
        else:
            base = "".join(ch for ch in profile["name"] if ch.isalnum() or ch in "_-")[:20] or "hero"
            username = base
            n = 1
            while True:
                async with db.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
                    (username,),
                ) as c:
                    if not await c.fetchone():
                        break
                n += 1
                username = f"{base}{n}"
            cursor = await db.execute(
                "INSERT INTO users (email, google_id, username) VALUES (?, ?, ?)",
                (email, profile["google_id"], username),
            )
            await db.commit()
            user_id = cursor.lastrowid

    token = create_access_token(user_id, username)
    return RedirectResponse(
        url=f"/auth/google/done?token={token}&username={username}&user_id={user_id}"
    )


@router.get("/google/done")
async def google_done(
    token: str = Query(...),
    username: str = Query(...),
    user_id: int = Query(...),
):
    return TokenResponse(access_token=token, user_id=user_id, username=username)


@router.post("/characters", response_model=CharacterOut, status_code=status.HTTP_201_CREATED)
async def create_character(body: CharacterCreate, user: dict = Depends(get_current_user)):
    name = body.name  # already normalized by validator

    try:
        async with db_write() as db:
            async with db.execute(
                "SELECT COUNT(*) AS n FROM characters WHERE user_id = ?",
                (user["id"],),
            ) as c:
                row = await c.fetchone()
                if int(row["n"]) >= 3:
                    raise HTTPException(status_code=400, detail="Maximum 3 characters per account")

            async with db.execute(
                "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
                (name,),
            ) as c:
                if await c.fetchone():
                    raise HTTPException(status_code=400, detail="Character name already taken")

            cursor = await db.execute(
                """
                INSERT INTO characters (user_id, name, world_x, world_y, gold)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user["id"], name, SPAWN_X, SPAWN_Y, str(STARTING_GOLD)),
            )
            char_id = cursor.lastrowid
            # Starter herb so new heroes can heal (DQ1 staple)
            await db.execute(
                "INSERT INTO item_instances (character_id, item_id, quantity, is_equipped) VALUES (?, 'herb', 3, 0)",
                (char_id,),
            )
            await db.commit()
            async with db.execute("SELECT * FROM characters WHERE id = ?", (char_id,)) as c:
                crow = await c.fetchone()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Character name already taken") from None

    return _row_to_character(crow)


@router.get("/characters", response_model=list[CharacterOut])
async def list_characters(user: dict = Depends(get_current_user)):
    db = await get_db()
    async with db.execute(
        "SELECT * FROM characters WHERE user_id = ? ORDER BY id",
        (user["id"],),
    ) as c:
        rows = await c.fetchall()
    return [_row_to_character(r) for r in rows]


@router.delete("/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(character_id: int, user: dict = Depends(get_current_user)):
    """Delete one of the caller's heroes (and their inventory).

    If the character is currently online, drop their WebSocket so they cannot
    keep acting with a deleted row.
    """
    async with db_write() as db:
        async with db.execute(
            "SELECT id FROM characters WHERE id = ? AND user_id = ?",
            (character_id, user["id"]),
        ) as c:
            row = await c.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Character not found")
        await db.execute(
            "DELETE FROM item_instances WHERE character_id = ?",
            (character_id,),
        )
        await db.execute(
            "DELETE FROM characters WHERE id = ? AND user_id = ?",
            (character_id, user["id"]),
        )
        await db.commit()

    # Kick live session if any (best-effort; tests / multiplayer safety)
    try:
        from game.combat_engine import combat_engine
        from network.websocket_manager import manager

        combat_engine.end(character_id)
        ws = manager._connections.get(character_id)
        if ws is not None:
            try:
                await ws.close(code=4001, reason="Character deleted")
            except Exception:
                pass
        await manager.disconnect(character_id, ws)
    except Exception:
        pass
    return None
