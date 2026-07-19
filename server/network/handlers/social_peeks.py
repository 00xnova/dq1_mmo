"""Rate-exempt multiplayer social peeks (extracted from message_handler)."""

from __future__ import annotations

from typing import Any

from network.handlers._common import peer_status_suffix, social_peer_card
from network.protocol import ServerMessageType, msg
from network.websocket_manager import manager

LASTWHISPER_TYPES = frozenset(
    {"lastwhisper", "last_whisper", "last", "reply_to", "who_last"}
)
SOCIAL_TYPES = frozenset(
    {"social", "peers", "contacts", "social_peers", "who_social"}
)
LASTEMOTE_TYPES = frozenset(
    {"lastemote", "last_emote", "who_emote", "emote_last"}
)
LASTSHARE_TYPES = frozenset(
    {"lastshare", "last_share", "who_share", "share_last"}
)
LASTINVITE_TYPES = frozenset(
    {"lastinvite", "last_invite", "who_invite", "invite_last"}
)
PENDING_TYPES = frozenset(
    {"pending", "invites", "meetup", "invite_status", "pending_invites"}
)

ALL_TYPES = (
    LASTWHISPER_TYPES
    | SOCIAL_TYPES
    | LASTEMOTE_TYPES
    | LASTSHARE_TYPES
    | LASTINVITE_TYPES
    | PENDING_TYPES
)


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch social peeks. Returns None if msg_type is not a social peek."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)

    if msg_type in LASTWHISPER_TYPES:
        lid, lname = manager.last_whisper_from(character_id)
        peer = social_peer_card(manager, lid, lname, viewer_id=character_id)
        online = bool(peer and peer.get("online"))
        if peer:
            lw_msg = f"Last whisper: {peer['name']}{peer_status_suffix(peer)}"
        else:
            lw_msg = "No one to reply to yet."
        outbound.append(
            msg(
                "lastwhisper",
                peer=peer,
                online=online,
                message=lw_msg,
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in SOCIAL_TYPES:
        w_id, w_name = manager.last_whisper_from(character_id)
        i_from_id, i_from_name = manager.last_invite_from(character_id)
        i_to_id, i_to_name = manager.last_invite_to(character_id)
        e_id, e_name = manager.last_emote_to(character_id)
        ef_id, ef_name = manager.last_emote_from(character_id)
        s_id, s_name = manager.last_share_to(character_id)
        sf_id, sf_name = manager.last_share_from(character_id)
        whisper = social_peer_card(manager, w_id, w_name, viewer_id=character_id)
        invite_from = social_peer_card(
            manager, i_from_id, i_from_name, viewer_id=character_id
        )
        invite_to = social_peer_card(
            manager, i_to_id, i_to_name, viewer_id=character_id
        )
        emote = social_peer_card(manager, e_id, e_name, viewer_id=character_id)
        emote_from = social_peer_card(
            manager, ef_id, ef_name, viewer_id=character_id
        )
        share = social_peer_card(manager, s_id, s_name, viewer_id=character_id)
        share_from = social_peer_card(
            manager, sf_id, sf_name, viewer_id=character_id
        )
        bits: list[str] = []
        if whisper:
            bits.append(f"/r → {whisper['name']}" + peer_status_suffix(whisper))
        if invite_from:
            bits.append(
                f"invite from {invite_from['name']}" + peer_status_suffix(invite_from)
            )
        if invite_to:
            bits.append(
                f"invite to {invite_to['name']}" + peer_status_suffix(invite_to)
            )
        if emote:
            bits.append(f"emote → {emote['name']}" + peer_status_suffix(emote))
        if emote_from:
            bits.append(
                f"emote from {emote_from['name']}" + peer_status_suffix(emote_from)
            )
        if share:
            bits.append(f"share → {share['name']}" + peer_status_suffix(share))
        if share_from:
            bits.append(
                f"share from {share_from['name']}" + peer_status_suffix(share_from)
            )
        outbound.append(
            msg(
                "social",
                whisper=whisper,
                invite_from=invite_from,
                invite_to=invite_to,
                emote=emote,
                emote_from=emote_from,
                share=share,
                share_from=share_from,
                has_any=bool(bits),
                message=(
                    "Social · " + " · ".join(bits) if bits else "No social peers yet."
                ),
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in LASTEMOTE_TYPES:
        to_id, to_name = manager.last_emote_to(character_id)
        from_id, from_name = manager.last_emote_from(character_id)
        to_peer = social_peer_card(manager, to_id, to_name, viewer_id=character_id)
        from_peer = social_peer_card(
            manager, from_id, from_name, viewer_id=character_id
        )
        bits_le: list[str] = []
        if to_peer:
            bits_le.append(f"to {to_peer['name']}" + peer_status_suffix(to_peer))
        if from_peer:
            bits_le.append(
                f"from {from_peer['name']}" + peer_status_suffix(from_peer)
            )
        if bits_le:
            le_msg = "Last emote · " + " · ".join(bits_le)
        else:
            le_msg = "No directed emote target yet."
        peer = to_peer or from_peer
        online = bool(peer and peer.get("online"))
        outbound.append(
            {
                "type": "lastemote",
                "peer": peer,
                "to": to_peer,
                "from": from_peer,
                "from_peer": from_peer,
                "online": online,
                "has_to": to_peer is not None,
                "has_from": from_peer is not None,
                "message": le_msg,
            }
        )
        return character_id, user_id, outbound, None

    if msg_type in LASTSHARE_TYPES:
        to_id, to_name = manager.last_share_to(character_id)
        from_id, from_name = manager.last_share_from(character_id)
        to_peer = social_peer_card(manager, to_id, to_name, viewer_id=character_id)
        from_peer = social_peer_card(
            manager, from_id, from_name, viewer_id=character_id
        )
        bits_ls: list[str] = []
        if to_peer:
            bits_ls.append(f"to {to_peer['name']}" + peer_status_suffix(to_peer))
        if from_peer:
            bits_ls.append(
                f"from {from_peer['name']}" + peer_status_suffix(from_peer)
            )
        if bits_ls:
            ls_msg = "Last share · " + " · ".join(bits_ls)
        else:
            ls_msg = "No location share yet."
        peer = to_peer or from_peer
        online = bool(peer and peer.get("online"))
        outbound.append(
            {
                "type": "lastshare",
                "peer": peer,
                "to": to_peer,
                "from": from_peer,
                "from_peer": from_peer,
                "online": online,
                "has_to": to_peer is not None,
                "has_from": from_peer is not None,
                "message": ls_msg,
            }
        )
        return character_id, user_id, outbound, None

    if msg_type in LASTINVITE_TYPES:
        lid, lname = manager.last_invite_from(character_id)
        peer = social_peer_card(manager, lid, lname, viewer_id=character_id)
        online = bool(peer and peer.get("online"))
        if peer:
            li_msg = f"Last invite from: {peer['name']}{peer_status_suffix(peer)}"
        else:
            li_msg = "No meetup invite yet."
        outbound.append(
            msg(
                "lastinvite",
                peer=peer,
                online=online,
                message=li_msg,
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in PENDING_TYPES:
        from_id, from_name = manager.last_invite_from(character_id)
        to_id, to_name = manager.last_invite_to(character_id)
        incoming = social_peer_card(
            manager, from_id, from_name, viewer_id=character_id
        )
        outgoing = social_peer_card(
            manager, to_id, to_name, viewer_id=character_id
        )
        bits: list[str] = []
        if incoming:
            bits.append(f"from {incoming['name']}" + peer_status_suffix(incoming))
        if outgoing:
            bits.append(f"to {outgoing['name']}" + peer_status_suffix(outgoing))
        if bits:
            message = "Pending meetup · " + " · ".join(bits)
        else:
            message = "No pending meetup invites."
        outbound.append(
            msg(
                "pending",
                incoming=incoming,
                outgoing=outgoing,
                has_incoming=incoming is not None,
                has_outgoing=outgoing is not None,
                message=message,
            )
        )
        return character_id, user_id, outbound, None

    return None
