"""World state helpers (expanded in Phase 3)."""

# MVP testing map: 8x8, 0=grass walkable, 1=wall
MVP_MAP = [
    [1, 1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1, 1],
]

MAP_WIDTH = 8
MAP_HEIGHT = 8
VISIBILITY_RANGE = 10


def in_bounds(x: int, y: int) -> bool:
    return 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT


def is_walkable(x: int, y: int) -> bool:
    if not in_bounds(x, y):
        return False
    return MVP_MAP[y][x] == 0


def is_nearby(ax: float, ay: float, bx: float, by: float, rang: int = VISIBILITY_RANGE) -> bool:
    return abs(ax - bx) <= rang and abs(ay - by) <= rang
