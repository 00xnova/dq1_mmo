from pydantic import BaseModel


class EnemyOut(BaseModel):
    id: str
    name: str
    hp: int
    max_hp: int
    strength: int
    agility: int
