"""
Sidebar panels for the Pygame viewer: Overview, Web, Energy, Dynamics, Lab.

Each draw_* function takes the viewer, the surface and the rectangle it may
use. Anything clickable is registered with `viewer.add_target(rect, fn)`
while drawing, so hit-testing always matches what is on screen.
"""

import math

import pygame

from data.species import SPECIES
from Interface import education as edu
from Interface.experiments import EXPERIMENTS, BY_KEY
from Interface.theme import (
    BG, PANEL_BORDER, TEXT, MUTED, ACCENT, BTN_BG, BTN_HOVER, BTN_ACTIVE,
    DANGER_BG, DANGER_HOVER, SPECIES_COLOR, EVENT_COLORS, REMAINS_COLOR,
    SOIL_COLOR,
)


# ---------------------------------------------------------------- helpers

def wrap_text(font, text, max_width):
    """Split text into lines that fit `max_width` pixels."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_text(surf, font, text, color, pos):
    img = font.render(text, True, color)
    surf.blit(img, pos)
    return img.get_width()


def draw_wrapped(surf, font, text, color, x, y, width, line_h=16, max_lines=None):
    """Draw wrapped text; returns the y below the last line."""
    lines = wrap_text(font, text, width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        surf.blit(font.render(line, True, color), (x, y))
        y += line_h
    return y


def alpha_rect(surf, rect, color, radius=0):
    """Filled rectangle with alpha (colour is RGBA)."""
    s = pygame.Surface(pygame.Rect(rect).size, pygame.SRCALPHA)
    pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
    surf.blit(s, pygame.Rect(rect).topleft)


def small_button(viewer, surf, rect, label, on_click, active=False, danger=False):
    rect = pygame.Rect(rect)
    hovered = rect.collidepoint(viewer.mouse_pos)
    if danger:
        color = DANGER_HOVER if hovered else DANGER_BG
    elif active:
        color = BTN_ACTIVE
    else:
        color = BTN_HOVER if hovered else BTN_BG
    pygame.draw.rect(surf, color, rect, border_radius=5)
    pygame.draw.rect(surf, PANEL_BORDER, rect, 1, border_radius=5)
    img = viewer.fonts["sm"].render(label, True, TEXT)
    surf.blit(img, img.get_rect(center=rect.center))
    if rect.bottom <= getattr(viewer, "panel_bottom", 10 ** 6):
        viewer.add_target(rect, on_click)       # clipped-away buttons must not be clickable


def section_title(viewer, surf, text, x, y):
    draw_text(surf, viewer.fonts["md"], text, TEXT, (x, y))
    return y + 20


def _compact(n):
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return f"{n:.0f}"


def _line_chart(surf, rect, series, y_min, y_max, baseline=None):
    """series: [(colour, [values...])], all the same length."""
    pygame.draw.rect(surf, BG, rect, border_radius=4)
    pygame.draw.rect(surf, PANEL_BORDER, rect, 1, border_radius=4)
    if y_max - y_min < 1e-9:
        y_max = y_min + 1
    if baseline is not None and y_min < baseline < y_max:
        by = rect.bottom - 4 - (baseline - y_min) / (y_max - y_min) * (rect.h - 8)
        for x in range(rect.x + 4, rect.right - 4, 8):
            pygame.draw.line(surf, PANEL_BORDER, (x, by), (x + 4, by), 1)
    for colour, values in series:
        if len(values) < 2:
            continue
        pts = []
        for i, v in enumerate(values):
            px = rect.x + 4 + i / (len(values) - 1) * (rect.w - 8)
            py = rect.bottom - 4 - (v - y_min) / (y_max - y_min) * (rect.h - 8)
            pts.append((px, py))
        pygame.draw.lines(surf, colour, False, pts, 2)


# --------------------------------------------------------------- overview

def draw_overview(viewer, surf, rect):
    """Species bars (click to spawn), population history and the event log."""
    f = viewer.fonts
    snap = viewer.snap
    sx, sw = rect.x, rect.w
    y = rect.y

    y = section_title(viewer, surf, "Species  (click row to spawn)", sx, y)
    peak = max([c for c in snap.counts.values()] + [10])
    bar_max = max(60, sw - 125)
    viewer._species_rects.clear()

    for name in SPECIES:
        row_rect = pygame.Rect(sx - 4, y - 1, sw + 8, 17)
        viewer._species_rects[name] = row_rect
        is_armed = (viewer.spawn_species == name)
        if is_armed:
            pygame.draw.rect(surf, (45, 62, 82), row_rect, border_radius=3)
            pygame.draw.rect(surf, SPECIES_COLOR.get(name, ACCENT), row_rect, 1, border_radius=3)
        elif row_rect.collidepoint(viewer.mouse_pos):
            pygame.draw.rect(surf, (30, 38, 49), row_rect, border_radius=3)

        count = snap.counts.get(name, 0)
        col = SPECIES_COLOR.get(name, TEXT)
        draw_text(surf, f["sm"], name, col, (sx, y))
        bar_w = int(((count ** 0.5) / (peak ** 0.5)) * bar_max)
        pygame.draw.rect(surf, (32, 39, 49), (sx + 80, y + 3, bar_max, 10), border_radius=3)
        if bar_w > 0:
            pygame.draw.rect(surf, col, (sx + 80, y + 3, bar_w, 10), border_radius=3)
        draw_text(surf, f["sm"], str(count), TEXT, (sx + 86 + bar_max, y))
        viewer.add_target(row_rect, lambda n=name: viewer.pick_spawn(n))
        y += 18

    # Mini population history graph
    y += 8
    y = section_title(viewer, surf, "Population History", sx, y)
    remaining = rect.bottom - y - 12
    graph_h = max(65, min(105, remaining // 2))
    graph_rect = pygame.Rect(sx, y, sw, graph_h)
    pygame.draw.rect(surf, BG, graph_rect, border_radius=4)
    pygame.draw.rect(surf, PANEL_BORDER, graph_rect, 1, border_radius=4)

    rec = viewer.recorder
    pts = ([(r["turn"], r) for r in rec.rows[-250:]]
           if (rec and rec.rows) else list(viewer.history)[-250:])
    if len(pts) >= 2:
        max_y = max(10, max(c.get(s, 0) for _, c in pts for s in SPECIES))
        for name in SPECIES:
            col = SPECIES_COLOR.get(name, TEXT)
            coords = []
            for i, (_, counts) in enumerate(pts):
                px = graph_rect.x + 4 + (i / (len(pts) - 1)) * (graph_rect.w - 8)
                val = counts.get(name, 0)
                py = graph_rect.bottom - 4 - ((val ** 0.5) / (max_y ** 0.5)) * (graph_rect.h - 8)
                coords.append((px, py))
            pygame.draw.lines(surf, col, False, coords, 2)

    # Plain-English Ecosystem Log (each line also says why, on hover)
    y = graph_rect.bottom + 10
    y = section_title(viewer, surf, "Ecosystem Log", sx, y)
    max_lines = max(1, (rect.bottom - y - 8) // 18)
    events = list(viewer.detector.events)[-max_lines:] if viewer.detector else []
    events.reverse()

    from Interface.pygame_viewer import format_event
    if not events:
        draw_text(surf, f["sm"], "Ecosystem stable", MUTED, (sx, y))
    else:
        for e in events:
            col = EVENT_COLORS.get(e.kind, MUTED)
            row = pygame.Rect(sx - 4, y - 1, sw + 8, 18)
            draw_text(surf, f["sm"], format_event(e), col, (sx, y))
            if row.collidepoint(viewer.mouse_pos):
                viewer.tooltip = (edu.lesson_for(e.kind), col)
            y += 18


# -------------------------------------------------------------------- web

def _node_radius(viewer, name):
    snap = viewer.snap
    if name == "Remains":
        peak = max(200.0, snap.remains_total)
        return 9 + 9 * math.sqrt(min(1.0, snap.remains_total / peak))
    if name == "Soil":
        return 9 + 9 * snap.fertility_mean
    peak = max([c for c in snap.counts.values()] + [10])
    return 9 + 11 * math.sqrt(snap.counts.get(name, 0) / peak)


def _node_color(name):
    if name == "Remains":
        return REMAINS_COLOR
    if name == "Soil":
        return SOIL_COLOR
    return SPECIES_COLOR.get(name, TEXT)


def draw_web(viewer, surf, rect):
    f = viewer.fonts
    snap = viewer.snap
    show_card = rect.h >= 430
    card_h = 118 if show_card else 0
    area = pygame.Rect(rect.x, rect.y + 20, rect.w, rect.h - 24 - card_h)

    draw_text(surf, f["md"], "Food Web", TEXT, (rect.x, rect.y))
    draw_text(surf, f["sm"], "arrows show energy flow  |  click a node",
              MUTED, (rect.x + 82, rect.y + 2))

    pygame.draw.rect(surf, BG, area, border_radius=5)
    pygame.draw.rect(surf, PANEL_BORDER, area, 1, border_radius=5)

    def pos(name):
        nx, ny = edu.WEB_NODES[name]
        return (area.x + 10 + nx * (area.w - 20), area.y + 10 + ny * (area.h - 26))

    def corner(point):
        return (area.x + 10 + point[0] * (area.w - 20), area.y + 10 + point[1] * (area.h - 26))

    focus = viewer.card_species()
    t = viewer.anim_time

    # ---- arrows ----
    for src, dst, key, route in edu.web_edges():
        a, b = pos(src), pos(dst)
        pts = [a] + [corner(p) for p in route] + [b]

        # shorten the first and last segments so arrows stop at the node rims
        def trim(p, q, r):
            d = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
            k = min(0.45, r / d)
            return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)

        pts[0] = trim(pts[0], pts[1], _node_radius(viewer, src) + 2)
        pts[-1] = trim(pts[-1], pts[-2], _node_radius(viewer, dst) + 6)

        pulse = viewer.edge_pulse.get(key, 0.0) if key else 0.0
        related = focus in (src, dst)
        if key is None:
            base = (110, 160, 90)           # nutrient loop
        else:
            base = (74, 88, 104)
        if related:
            base = tuple(min(255, int(c * 1.5)) for c in base)
        col = tuple(int(b + (255 - b) * pulse * 0.6) for b in base)
        width = 2 + (1 if related else 0) + int(pulse * 2)

        if key is None:
            for p, q in zip(pts, pts[1:]):
                _dashed(surf, col, p, q)
        else:
            pygame.draw.lines(surf, col, False, pts, width)

        # arrow head
        p, q = pts[-2], pts[-1]
        ang = math.atan2(q[1] - p[1], q[0] - p[0])
        head = [
            q,
            (q[0] - 9 * math.cos(ang - 0.45), q[1] - 9 * math.sin(ang - 0.45)),
            (q[0] - 9 * math.cos(ang + 0.45), q[1] - 9 * math.sin(ang + 0.45)),
        ]
        pygame.draw.polygon(surf, col, head)

        # energy packets travelling along a busy arrow
        if pulse > 0.05:
            _packets(surf, pts, t, pulse, _node_color(src))

    # ---- nodes ----
    for name in edu.WEB_NODES:
        cx, cy = pos(name)
        r = _node_radius(viewer, name)
        col = _node_color(name)
        node_rect = pygame.Rect(int(cx - r - 4), int(cy - r - 4), int(2 * r + 8), int(2 * r + 22))

        glow = pygame.Surface((int(r * 4), int(r * 4)), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*col, 40), (int(r * 2), int(r * 2)), int(r * 1.7))
        surf.blit(glow, (int(cx - r * 2), int(cy - r * 2)))
        pygame.draw.circle(surf, (24, 30, 38), (int(cx), int(cy)), int(r))
        pygame.draw.circle(surf, col, (int(cx), int(cy)), int(r), 3 if name == focus else 2)

        sprites = getattr(viewer, "sprites", None)
        icon = sprites.get(name.lower() if name in ("Remains",) else name, int(r * 1.7)) if sprites else None
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=(int(cx), int(cy))))

        if name == "Remains":
            label = f"Remains {_compact(snap.remains_total)}"
        elif name == "Soil":
            label = f"Soil {int(snap.fertility_mean * 100)}%"
        else:
            label = f"{name} {snap.counts.get(name, 0)}"
        img = f["sm"].render(label, True, col if name != focus else TEXT)
        surf.blit(img, (int(cx - img.get_width() / 2), int(cy + r + 2)))

        if name in SPECIES:
            viewer.add_target(node_rect, lambda n=name: viewer.set_card_species(n))
            if node_rect.collidepoint(viewer.mouse_pos):
                viewer.tooltip = (edu.SPECIES_INFO.get(name, {}).get("blurb", ""), col)

    draw_text(surf, f["sm"], "everything that dies becomes Remains",
              (80, 100, 112), (area.x + 10, area.bottom - 18))

    if show_card:
        _draw_card(viewer, surf, pygame.Rect(rect.x, area.bottom + 4, rect.w, card_h - 4), focus)


def _dashed(surf, color, p, q, dash=6):
    d = math.hypot(q[0] - p[0], q[1] - p[1])
    if d < 1:
        return
    n = int(d // (dash * 2)) + 1
    for i in range(n):
        s = i * dash * 2 / d
        e = min(1.0, (i * 2 + 1) * dash / d)
        if s >= 1:
            break
        pygame.draw.line(
            surf, color,
            (p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s),
            (p[0] + (q[0] - p[0]) * e, p[1] + (q[1] - p[1]) * e), 2)


def _packets(surf, pts, t, pulse, colour):
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    total = sum(lengths) or 1.0
    for k in range(3):
        d = ((t * 0.7 + k / 3) % 1.0) * total
        for (a, b), seg in zip(zip(pts, pts[1:]), lengths):
            if d <= seg:
                u = d / (seg or 1.0)
                pygame.draw.circle(
                    surf, colour,
                    (int(a[0] + (b[0] - a[0]) * u), int(a[1] + (b[1] - a[1]) * u)),
                    3)
                break
            d -= seg


def _draw_card(viewer, surf, rect, species):
    f = viewer.fonts
    card = edu.card_for(species)
    col = SPECIES_COLOR.get(species, ACCENT)
    pygame.draw.rect(surf, (26, 33, 42), rect, border_radius=6)
    pygame.draw.rect(surf, col, rect, 1, border_radius=6)

    sprites = getattr(viewer, "sprites", None)
    icon = sprites.get(species, 56) if sprites else None
    tx = rect.x + 10
    if icon is not None:
        surf.blit(icon, icon.get_rect(center=(rect.x + 36, rect.y + 36)))
        tx = rect.x + 72

    draw_text(surf, f["md"], f"{species}", col, (tx, rect.y + 6))
    draw_text(surf, f["sm"], card["role"], MUTED, (tx, rect.y + 24))
    eats = ", ".join(card["diet"]) or "-"
    eaten = ", ".join(card["eaten_by"]) or "nothing hunts it"
    stats = f"eats: {eats}  |  eaten by: {eaten}"
    draw_wrapped(surf, f["sm"], stats, TEXT, tx, rect.y + 42, rect.right - tx - 8, 14, 2)
    draw_wrapped(surf, f["sm"], card["blurb"], MUTED, rect.x + 10, rect.y + 74, rect.w - 20, 14, 2)
    spd = viewer.snap.traits.get(species, (1.0, 1.0))
    if species in viewer.evolving:
        extra = f"speed {card['speed']} x{spd[0]:.2f}   senses {card['perception']} x{spd[1]:.2f}"
        draw_text(surf, f["sm"], extra, ACCENT, (rect.x + 10, rect.bottom - 18))


# ----------------------------------------------------------------- energy

def draw_energy(viewer, surf, rect):
    f = viewer.fonts
    snap = viewer.snap
    x, w = rect.x, rect.w
    y = section_title(viewer, surf, "Energy Pyramid", x, rect.y)

    levels = {label: (energy, count) for label, energy, count in edu.trophic_levels(snap)}
    stack = [("Predators", (255, 82, 82)),
             ("Herbivores", (255, 202, 40)),
             ("Producers", (92, 214, 92))]
    peak = max([levels[n][0] for n, _ in stack] + [1.0])
    bar_h = 30 if rect.h > 420 else 24
    cx = x + w // 2

    for name, col in stack:
        energy, count = levels[name]
        bw = max(8, int((w - 20) * (energy / peak)))
        bar = pygame.Rect(cx - bw // 2, y, bw, bar_h)
        pygame.draw.rect(surf, col, bar, border_radius=4)
        label = f"{name}  {_compact(energy)} energy  |  {count}"
        img = f["sm"].render(label, True, TEXT)
        if bw > img.get_width() + 10:
            surf.blit(img, img.get_rect(center=bar.center))
            pass
        else:
            surf.blit(img, (cx - img.get_width() // 2, y + bar_h + 1))
            y += 14
        y += bar_h + 4

    passed = edu.energy_passed_up()
    note = (f"Only ~{int(passed['grazing'] * 100)}% of a bite and ~{int(passed['hunting'] * 100)}% "
            f"of a catch becomes energy, so each level up holds much less.")
    y = draw_wrapped(surf, f["sm"], note, MUTED, x, y + 2, w, 14, 3) + 4

    # recyclers and soil
    rec_energy, rec_count = levels["Recyclers"][0], levels["Recyclers"][1]
    draw_text(surf, f["sm"], f"Recyclers {_compact(rec_energy)} energy | {rec_count}", (196, 154, 108), (x, y))
    y += 16
    draw_text(surf, f["sm"], f"Remains on the ground {_compact(snap.remains_total)}", REMAINS_COLOR, (x, y))
    y += 16
    draw_text(surf, f["sm"], "Soil richness", SOIL_COLOR, (x, y))
    bar = pygame.Rect(x + 96, y + 3, w - 140, 9)
    pygame.draw.rect(surf, (32, 39, 49), bar, border_radius=3)
    pygame.draw.rect(surf, SOIL_COLOR, (bar.x, bar.y, int(bar.w * snap.fertility_mean), bar.h), border_radius=3)
    draw_text(surf, f["sm"], f"{int(snap.fertility_mean * 100)}%", TEXT, (bar.right + 6, y))
    y += 24

    # how things die
    rows = viewer.recorder.rows if viewer.recorder else []
    y = section_title(viewer, surf, "How things died (last 100 turns)", x, y)
    deaths = edu.mortality(rows, 100)
    total = sum(n for _, n, _ in deaths) or 1
    strip = pygame.Rect(x, y, w, 14)
    pygame.draw.rect(surf, (32, 39, 49), strip, border_radius=3)
    cursor = strip.x
    for label, n, col in deaths:
        seg = int(strip.w * n / total)
        if seg > 0:
            pygame.draw.rect(surf, col, (cursor, strip.y, seg, strip.h))
            cursor += seg
    y += 20
    lx = x
    for label, n, col in deaths:
        text = f"{label} {n}"
        img = f["sm"].render(text, True, col)
        if lx + img.get_width() > rect.right:
            lx, y = x, y + 15
        surf.blit(img, (lx, y))
        lx += img.get_width() + 12
    y += 22

    # activity
    if y < rect.bottom - 40:
        y = section_title(viewer, surf, "Activity (last 100 turns)", x, y)
        recent = rows[-100:]
        for key, label in (("births", "Births"), ("meals_grazed", "Plants grazed"),
                           ("kills", "Kills"), ("failed_hunts", "Failed hunts"),
                           ("remains_eaten", "Remains recycled")):
            if y > rect.bottom - 16:
                break
            n = sum(r.get(key, 0) for r in recent)
            draw_text(surf, f["sm"], f"{label:<17}{_compact(n)}", TEXT, (x, y))
            y += 15


# --------------------------------------------------------------- dynamics

def draw_dynamics(viewer, surf, rect):
    f = viewer.fonts
    x, w = rect.x, rect.w
    y = section_title(viewer, surf, "Predator-Prey Cycle", x, rect.y)

    plot_h = max(120, min(190, int(rect.h * 0.40)))
    plot = pygame.Rect(x, y, w, plot_h)
    pygame.draw.rect(surf, BG, plot, border_radius=5)
    pygame.draw.rect(surf, PANEL_BORDER, plot, 1, border_radius=5)

    prey_names = [s for s, d in SPECIES.items() if d["type"] == "Consumer"]
    pred_names = [s for s, d in SPECIES.items() if d["type"] == "Predator"]
    pts = [(sum(c.get(n, 0) for n in prey_names), sum(c.get(n, 0) for n in pred_names))
           for _, c in list(viewer.history)[-300:]]
    if len(pts) >= 2:
        mx = max(10, max(p[0] for p in pts))
        my = max(4, max(p[1] for p in pts))
        coords = [(plot.x + 8 + p[0] / mx * (plot.w - 16),
                   plot.bottom - 8 - p[1] / my * (plot.h - 16)) for p in pts]
        n = len(coords)
        for i in range(1, n):
            shade = 40 + int(215 * i / n)
            pygame.draw.line(surf, (shade // 3, shade, 255 - shade // 2), coords[i - 1], coords[i], 2)
        pygame.draw.circle(surf, TEXT, (int(coords[-1][0]), int(coords[-1][1])), 5)
        pygame.draw.circle(surf, ACCENT, (int(coords[-1][0]), int(coords[-1][1])), 3)
    draw_text(surf, f["sm"], "predators", MUTED, (plot.x + 6, plot.y + 3))
    lab = "herbivores"
    draw_text(surf, f["sm"], lab, MUTED, (plot.right - f["sm"].size(lab)[0] - 6, plot.bottom - 16))
    y = plot.bottom + 4
    y = draw_wrapped(surf, f["sm"],
                     "Each loop: prey boom, predators follow, prey crash, predators starve.",
                     MUTED, x, y, w, 14, 2) + 6

    # evolution
    y = section_title(viewer, surf, "Evolution: average genes", x, y)
    from organisms import evolution
    if not evolution.ENABLED:
        draw_text(surf, f["sm"], "(evolution is frozen)", (255, 167, 38), (x + 190, y - 18))

    history = list(viewer.gene_history)
    chart_h = max(46, (rect.bottom - y - 70) // 2)
    for idx, label in ((0, "Speed gene"), (1, "Sense gene")):
        draw_text(surf, f["sm"], label, MUTED, (x, y))
        y += 14
        chart = pygame.Rect(x, y, w, chart_h)
        series, lo, hi = [], 1.0, 1.0
        for name in sorted(viewer.evolving, key=lambda s: SPECIES[s]["type"]):
            if name == "Nullborn":
                continue
            values = [g.get(name, (1.0, 1.0))[idx] for _, g in history[-250:]]
            if len(values) >= 2:
                lo, hi = min(lo, min(values)), max(hi, max(values))
                series.append((SPECIES_COLOR[name], values))
        _line_chart(surf, chart, series, lo - 0.04, hi + 0.04, baseline=1.0)
        y += chart_h + 6

    # legend with current values
    lx = x
    for name in sorted(viewer.evolving, key=lambda s: SPECIES[s]["type"]):
        if name == "Nullborn":
            continue
        spd, sns = viewer.snap.traits.get(name, (1.0, 1.0))
        text = f"{name[:4]} {spd:.2f}/{sns:.2f}"
        img = f["sm"].render(text, True, SPECIES_COLOR[name])
        if lx + img.get_width() > rect.right:
            lx, y = x, y + 15
        surf.blit(img, (lx, y))
        lx += img.get_width() + 10


# -------------------------------------------------------------------- lab

def draw_lab(viewer, surf, rect):
    f = viewer.fonts
    lab = viewer.lab
    x, w = rect.x, rect.w
    y = section_title(viewer, surf, "Lab: what if...?", x, rect.y)

    colw = (w - 8) // 2
    row = 0
    for spec in EXPERIMENTS:
        col = row % 2
        bx = x + col * (colw + 8)
        by = y + (row // 2) * 30
        on = lab.is_on(spec["key"])
        label = spec["label"] + ("  ON" if on else "")
        small_button(viewer, surf, (bx, by, colw, 26), label,
                     lambda k=spec["key"]: viewer.lab_toggle(k),
                     active=on, danger=(spec["kind"] == "action"))
        row += 1
    y += ((row + 1) // 2) * 30 + 2
    small_button(viewer, surf, (x, y, w, 24), "Reset all experiments", viewer.lab_reset)
    y += 32

    spec = BY_KEY.get(lab.last)
    if spec:
        # the box shrinks on small windows instead of running off the panel
        box_h = max(86, min(124, rect.bottom - y - 4))
        box = pygame.Rect(x, y, w, box_h)
        pygame.draw.rect(surf, (26, 33, 42), box, border_radius=6)
        pygame.draw.rect(surf, PANEL_BORDER, box, 1, border_radius=6)
        yy = draw_wrapped(surf, f["sm"], spec["predict"], ACCENT, x + 8, y + 8, w - 16, 14, 3)
        if viewer.lab_reveal:
            draw_wrapped(surf, f["sm"], spec["lesson"], TEXT, x + 8, yy + 6, w - 16, 14,
                         max(2, (box.bottom - yy - 12) // 14))
        else:
            small_button(viewer, surf, (x + 8, box.bottom - 32, 150, 24), "Reveal the answer",
                         viewer.reveal_lesson)
        y += box_h + 8
    else:
        y = draw_wrapped(surf, f["sm"],
                         "Pick an experiment, predict the outcome out loud, then watch.",
                         MUTED, x, y, w, 14, 2) + 6

    # presentation tools
    if y < rect.bottom - 60:
        y = section_title(viewer, surf, "Presentation", x, y)
        tools = [
            ("Showcase (S)", viewer.toggle_showcase, viewer.showcase_on),
            ("Step Menu (G)", viewer.toggle_step_menu, getattr(viewer, "show_step_menu", False)),
            ("Notes (N)", viewer.toggle_speaker_notes, getattr(viewer.director, "show_speaker_notes", False)),
            ("Pause @ Cap (B)", viewer.toggle_pause_on_caption, getattr(viewer.director, "pause_on_caption", False)),
            ("Soil map (M)", viewer.toggle_soil, viewer.show_soil),
            ("Clean view (H)", viewer.toggle_clean, False),
            ("Screenshot (P)", viewer.screenshot, False),
            ("Record (V)", viewer.toggle_record, viewer.recording),
            ("Help (F1)", viewer.toggle_help, viewer.show_help),
        ]
        for i, (label, fn, active) in enumerate(tools):
            bx = x + (i % 2) * (colw + 8)
            by = y + (i // 2) * 28
            if by + 24 > rect.bottom:
                break
            small_button(viewer, surf, (bx, by, colw, 24), label, fn, active=active)
