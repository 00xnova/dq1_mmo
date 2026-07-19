from enum import StrEnum
from typing import Any


class ClientMessageType(StrEnum):
    AUTH = "auth"
    MOVE = "move"
    ATTACK = "attack"
    FLEE = "flee"
    USE_SPELL = "use_spell"
    EQUIP = "equip"
    UNEQUIP = "unequip"
    PING = "ping"


class ServerMessageType(StrEnum):
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"
    WORLD_STATE = "world_state"
    PLAYER_MOVED = "player_moved"
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    COMBAT_START = "combat_start"
    COMBAT_UPDATE = "combat_update"
    COMBAT_END = "combat_end"
    LEVEL_UP = "level_up"
    INVENTORY_UPDATE = "inventory_update"
    ERROR = "error"
    PONG = "pong"


def msg(msg_type: str, **payload: Any) -> dict:
    return {"type": msg_type, **payload}
