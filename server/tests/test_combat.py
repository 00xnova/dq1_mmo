"""Battle engine smoke tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.combat_engine import Battle
from game.data_loader import get_enemy, load_data
from game.progression import apply_xp, level_for_xp


def _hero(level=1, **kw):
    base = {
        "name": "Test",
        "level": level,
        "strength": 4,
        "agility": 4,
        "max_hp": 15,
        "max_mp": 0,
        "current_hp": 15,
        "current_mp": 0,
        "experience": 0,
        "gold": "0",
    }
    base.update(kw)
    return base


def test_data_loaded():
    data = load_data()
    assert len(data["enemies"]) >= 40
    assert get_enemy("slime") is not None
    assert "copper_sword" in data["equipment"]


def test_slime_victory():
    b = Battle(_hero(), "slime", seed=42)
    assert b.outcome == "ongoing"
    for _ in range(30):
        if b.outcome != "ongoing":
            break
        r = b.act({"type": "attack"})
        assert r["ok"]
    assert b.outcome == "victory"
    assert b.rewards["xp"] >= 1
    assert b.hero["experience"] >= 1


def test_flee_action_legal():
    b = Battle(_hero(), "slime", seed=1)
    legal = {a["type"] for a in b.legal_actions()}
    assert "attack" in legal and "flee" in legal


def test_illegal_action():
    b = Battle(_hero(), "slime", seed=1)
    r = b.act({"type": "spell", "id": "hurt"})  # lv1 no hurt
    assert r["ok"] is False


def test_level_up():
    hero = _hero(experience=0, level=1)
    report = apply_xp(hero, 7)
    assert hero["level"] == 2
    assert report["level_ups"]
    assert level_for_xp(0) == 1
    assert level_for_xp(7) == 2


def test_equipment_raises_atk():
    bare = Battle(_hero(strength=4), "slime", seed=5)
    geared = Battle(
        _hero(strength=4, equipment_weapon="copper_sword"),
        "slime",
        seed=5,
    )
    assert geared.hero["attack_power"] == bare.hero["attack_power"] + 10
