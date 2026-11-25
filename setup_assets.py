"""One-time script to slice sheet.jpg into transparent PNGs and copy world.jpg."""

import os
from collections import deque
import pygame

GRID = [
    ["verdant", "crystalis", "mycel"],
    ["grazer",  "shellkin",  "nullborn"],
    ["ravager", "skyrender", "remains"],
]

def remove_white_bg(surf, threshold=235):
    """Flood-fill from the borders to make outer white pixels transparent."""
    w, h = surf.get_size()
    out = surf.convert_alpha()
    visited = bytearray(w * h)
    q = deque()

    def is_white(x, y):
        r, g, b, _ = out.get_at((x, y))
        return r >= threshold and g >= threshold and b >= threshold

    # Seed from all four edges
    for x in range(w):
        for y in (0, h - 1):
            if is_white(x, y):
                visited[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not visited[y * w + x] and is_white(x, y):
                visited[y * w + x] = 1
                q.append((x, y))

    while q:
        x, y = q.popleft()
        out.set_at((x, y), (0, 0, 0, 0))
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                idx = ny * w + nx
                if not visited[idx] and is_white(nx, ny):
                    visited[idx] = 1
                    q.append((nx, ny))

    # Crop tightly around the visible sprite
    bounds = out.get_bounding_rect(min_alpha=20)
    if bounds.w > 0 and bounds.h > 0:
        return out.subsurface(bounds).copy()
    return out


def main():
    pygame.init()
    pygame.display.set_mode((1, 1), pygame.HIDDEN)

    os.makedirs("assets/sprites", exist_ok=True)
    os.makedirs("assets/world", exist_ok=True)

    # 1. Slice the 3x3 sprite sheet
    if os.path.isfile("sheet.jpg"):
        sheet = pygame.image.load("sheet.jpg").convert_alpha()
        sw, sh = sheet.get_size()
        cw, ch = sw // 3, sh // 3

        for row in range(3):
            for col in range(3):
                name = GRID[row][col]
                # Bottom 19% of each cell holds the text label — crop it out
                cell_rect = pygame.Rect(col * cw, row * ch, cw, int(ch * 0.81))
                cell = sheet.subsurface(cell_rect).copy()
                cleaned = remove_white_bg(cell)
                out_path = f"assets/sprites/{name}.png"
                pygame.image.save(cleaned, out_path)
                print(f"Saved {out_path}")
    else:
        print("sheet.jpg not found in project root.")

    # 2. Save terrain as PNG
    if os.path.isfile("world.jpg"):
        terrain = pygame.image.load("world.jpg").convert()
        pygame.image.save(terrain, "assets/world/terrain.png")
        print("Saved assets/world/terrain.png")
    else:
        print("world.jpg not found in project root.")

    pygame.quit()


if __name__ == "__main__":
    main()