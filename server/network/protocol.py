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
    BUY = "buy"
    SELL = "sell"
    SHOP = "shop"
    INVENTORY = "inventory"
    USE_ITEM = "use_item"
    REST = "rest"  # town inn — restore HP/MP for gold
    PING = "ping"
    SYNC = "sync"  # request full presence snapshot
    CHAT = "chat"  # global chat (or channel=nearby|global|zone|whisper)
    SAY = "say"  # nearby (AOI) chat
    WHISPER = "whisper"  # private message (name or to_id/player_id)
    TELL = "tell"  # alias for whisper
    EMOTE = "emote"  # social emote to nearby players
    WHO = "who"  # lightweight online/nearby query
    LOOK = "look"  # examine nearby / online player (public card)
    EXAMINE = "examine"  # alias for look


class ServerMessageType(StrEnum):
    AUTH_OK = "auth_ok"
    AUTH_FAIL = "auth_fail"
    WORLD_STATE = "world_state"
    MOVE_OK = "move_ok"  # authoritative ack for the mover
    PLAYER_MOVED = "player_moved"
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    PLAYER_UPDATE = "player_update"
    COMBAT_START = "combat_start"
    COMBAT_RESUME = "combat_resume"
    COMBAT_UPDATE = "combat_update"
    COMBAT_END = "combat_end"
    LEVEL_UP = "level_up"
    INVENTORY_UPDATE = "inventory_update"
    SHOP_LIST = "shop_list"
    ITEM_USED = "item_used"
    REST_OK = "rest_ok"
    SPELL_CAST = "spell_cast"  # field magic result
    CHAT = "chat"
    EMOTE = "emote"
    WHO = "who"
    LOOK = "look"  # examine result
    ONLINE = "online"  # global online count pulse
    ERROR = "error"
    PONG = "pong"


def msg(msg_type: str, **payload: Any) -> dict:
    return {"type": msg_type, **payload}
