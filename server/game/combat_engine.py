"""Server-side DQ1 combat — ported/wired in Phase 4."""


class CombatEngine:
    def __init__(self) -> None:
        self.active: dict[int, dict] = {}

    def is_in_combat(self, character_id: int) -> bool:
        return character_id in self.active


combat_engine = CombatEngine()
