from pydantic import BaseModel


class ItemInstanceOut(BaseModel):
    id: int
    item_id: str
    quantity: int
    is_equipped: bool


class EquipRequest(BaseModel):
    slot: str
    item_id: str


class UnequipRequest(BaseModel):
    slot: str
