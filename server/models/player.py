from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    username: str = Field(min_length=2, max_length=24)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class CharacterCreate(BaseModel):
    name: str = Field(min_length=2, max_length=16)


class CharacterOut(BaseModel):
    id: int
    name: str
    level: int
    experience: int
    strength: int
    agility: int
    max_hp: int
    max_mp: int
    current_hp: int
    current_mp: int
    gold: str
    world_x: float
    world_y: float
    map_id: int
    equipment_weapon: str | None = None
    equipment_armor: str | None = None
    equipment_shield: str | None = None
    equipment_helmet: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    username: str
