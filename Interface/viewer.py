"""
Feature 12: live simulation viewer (matplotlib).

    from Interface.viewer import SimulationViewer
    viewer = SimulationViewer(sim, recorder=recorder, detector=detector)
    viewer.show()

Panels: the world map (organisms, organic remains), species population
counters, a population history graph, energy statistics, the environment
and resources, and a recent-events list. Controls: Play/Pause, Step, a speed
slider, a remains toggle, and click-to-inspect an organism.

Keys: space = play/pause, right arrow = one turn, up/down = speed,
      r = toggle remains, c = clear selection.

The viewer only ever reads a Snapshot and asks the simulation to advance;
it never edits the world.
"""

import contextlib
import io
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, Slider

from data.species import SPECIES
from Interface.snapshot import take_snapshot


# ------------------------------------------------------------------ style

BACKGROUND = "#0f1318"
PANEL = "#181e26"
MAP_BACKGROUND = "#141a21"
TEXT = "#d7dde4"
MUTED = "#7f8b99"
GRID = "#2a323d"

# colour and marker for each species (unknown species get a fallback)
SPECIES_STYLE = {
    "Verdant":   {"color": "#5cd65c", "marker": "s"},
    "Crystalis": {"color": "#4dd0e1", "marker": "s"},
    "Grazer":    {"color": "#ffca28", "marker": "o"},
    "Shellkin":  {"color": "#b36bff", "marker": "o"},
    "Ravager":   {"color": "#ff5252", "marker": "^"},
    "Skyrender": {"color": "#ff8ab3", "marker": "^"},
    "Mycel":     {"color": "#c49a6c", "marker": "D"},
    "Nullborn":  {"color": "#b0bec5", "marker": "P"},
}
FALLBACK_STYLE = {"color": "#ffffff", "marker": "o"}

# base marker area (points^2) by organism type
BASE_SIZE = {"Producer": 24, "Consumer": 58, "Predator": 100,
             "Decomposer": 48, "Scavenger": 56}

REMAINS_COLOR = "#a47c5a"

# colour of an event in the recent-events list
EVENT_COLORS = {
    "population_boom": "#5cd65c", "ecosystem_recovery": "#4dd0e1",
    "population_crash": "#ff5252", "ecosystem_crisis": "#ff1744",
    "food_shortage": "#ffa726", "predator_dominance": "#ff8a65",
    "resource_competition": "#ffd54f", "trophic_cascade": "#ce93d8",
    "predator_starving_amid_prey": "#f48fb1",
}

# turns per second; "max" runs as many turns as fit in a frame
SPEEDS = [1, 2, 5, 10, 20, 50, 100, "max"]
DEFAULT_SPEED_INDEX = 3
FRAME_INTERVAL_MS = 40
PANEL_PERIOD = 0.7             # seconds between full redraws of the side panels
MAX_SPEED_BUDGET = 0.03        # seconds of simulation per frame at "max"

HISTORY_WINDOW = 400           # turns shown on the history graph
EVENT_LINES = 10


def style_for(species):
    return SPECIES_STYLE.get(species, FALLBACK_STYLE)


def marker_size(kind, fullness):
    """Bigger = better fed."""
    return BASE_SIZE.get(kind, 50) * (0.55 + 0.9 * fullness)


def remains_size(amount):
    """Area grows with the square root of the pile, so big piles don't swamp the map."""
    return min(420.0, 14.0 + 7.0 * amount ** 0.5)


def fit_axes(ax, title=None):
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=7)
    if title:
        ax.set_title(title, color=TEXT, fontsize=9, loc="left", pad=4)


# ----------------------------------------------------------------- viewer

class SimulationViewer:

    def __init__(self, sim, recorder=None, detector=None, speed_index=DEFAULT_SPEED_INDEX,
                 start_paused=True, figsize=(17, 9.2)):

        self.sim = sim
        self.world = sim.world
        self.recorder = recorder
        self.detector = detector or getattr(recorder, "detector", None)

        self.paused = start_paused
        self.speed_index = speed_index
        self.show_remains = True
        self.selected = None
        self._acc = 0.0
        self._last_tick = None
        self._timer = None
        self._blit = False          # turned on by show(); see _enable_blit
        self._bg = None
        self._last_panels = 0.0

        # (turn, {species: count}); rebuilt from the world as it advances
        self.history = deque(maxlen=5000)

        self._configure_keys()
        self._build(figsize)
        self.refresh()

    # ---------------------------------------------------------- building

    @staticmethod
    def _configure_keys():
        # free the arrow keys and 'r' for the viewer
        for key in ("keymap.back", "keymap.forward", "keymap.home"):
            if key in plt.rcParams:
                plt.rcParams[key] = []

    def _build(self, figsize):
        self.fig = plt.figure(figsize=figsize, facecolor=BACKGROUND)

        try:
            self.fig.canvas.manager.set_window_title("GAIA - simulation viewer")
        except Exception:
            pass

        self._build_map()
        self._build_population()
        self._build_history()
        self._build_energy()
        self._build_environment()
        self._build_events()
        self._build_controls()

        canvas = self.fig.canvas
        canvas.mpl_connect("button_press_event", self._on_click)
        canvas.mpl_connect("key_press_event", self._on_key)

    def _build_map(self):
        ax = self.ax_map = self.fig.add_axes([0.025, 0.15, 0.475, 0.80])
        ax.set_facecolor(MAP_BACKGROUND)
        ax.set_xlim(0, self.world.width)
        ax.set_ylim(0, self.world.height)
        ax.set_aspect("equal", adjustable="box")
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=7)
        ax.grid(color=GRID, linewidth=0.4, alpha=0.6)
        ax.set_axisbelow(True)

        self.map_title = ax.set_title("", color=TEXT, fontsize=11, loc="left", pad=6)

        self.remains_scatter = ax.scatter(
            [], [], s=[], c=REMAINS_COLOR, alpha=0.32,
            edgecolors=REMAINS_COLOR, linewidths=0.8, zorder=2)

        self.scatters = {}
        for species in SPECIES:
            style = style_for(species)
            self.scatters[species] = ax.scatter(
                [], [], s=[], c=style["color"], marker=style["marker"],
                edgecolors="none", alpha=0.9, zorder=3)

        self.selection_ring = ax.scatter(
            [], [], s=260, facecolors="none", edgecolors="white",
            linewidths=1.4, zorder=5)

        self.info_text = ax.text(
            0.012, 0.988, "", transform=ax.transAxes, va="top", ha="left",
            color=TEXT, fontsize=8, family="monospace", zorder=6,
            bbox=dict(boxstyle="round,pad=0.4", fc=BACKGROUND, ec=GRID, alpha=0.85))
        self.info_text.set_visible(False)

        # Everything on the map that changes every frame. With blitting on,
        # only these are redrawn between full redraws.
        self._animated = [self.map_title, self.remains_scatter,
                          *self.scatters.values(), self.selection_ring, self.info_text]

    def _build_population(self):
        ax = self.ax_pop = self.fig.add_axes([0.545, 0.60, 0.215, 0.35])
        fit_axes(ax, "Population")
        ax.set_xlim(0, 1.45)
        ax.set_ylim(len(SPECIES) - 0.4, -0.7)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)

        self.pop_bars = []
        self.pop_labels = []
        self.pop_counts = []
        for i, species in enumerate(SPECIES):
            color = style_for(species)["color"]
            bar = ax.barh(i, 0, height=0.62, color=color, alpha=0.85)[0]
            label = ax.text(-0.0, i - 0.0, species, color=color, fontsize=8.5,
                            va="center", ha="left", zorder=4, weight="bold")
            count = ax.text(0, i, "", color=TEXT, fontsize=8.5, va="center", ha="left")
            self.pop_bars.append(bar)
            self.pop_labels.append(label)
            self.pop_counts.append(count)

        self.pop_total = ax.text(1.0, 1.02, "", transform=ax.transAxes, color=MUTED,
                                 fontsize=8, ha="right", va="bottom")

    def _build_history(self):
        ax = self.ax_hist = self.fig.add_axes([0.555, 0.09, 0.205, 0.42])
        fit_axes(ax, "Population history  (log-ish scale)")
        ax.set_yscale("symlog", linthresh=10)
        ax.set_yticks([0, 5, 10, 50, 100, 200, 400])
        ax.set_yticklabels(["0", "5", "10", "50", "100", "200", "400"])
        ax.grid(color=GRID, linewidth=0.4, alpha=0.6)
        ax.set_xlim(0, 50)
        ax.set_ylim(0, 20)

        self.hist_lines = {}
        for species in SPECIES:
            (line,) = ax.plot([], [], color=style_for(species)["color"],
                              linewidth=1.3, alpha=0.95)
            self.hist_lines[species] = line

    def _build_energy(self):
        ax = self.ax_energy = self.fig.add_axes([0.785, 0.60, 0.20, 0.35])
        fit_axes(ax, "Energy")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(len(SPECIES) + 2.2, -0.2)
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)

        header = f"{'':<10}{'mean':>6}{'min':>6}{'max':>6}"
        ax.text(0.0, 0.0, header, color=MUTED, fontsize=7.5, family="monospace", va="center")

        self.energy_rows = []
        self.energy_fill = []
        for i, species in enumerate(SPECIES, start=1):
            color = style_for(species)["color"]
            # background bar = how full the average member is
            ax.barh(i, 1.0, height=0.7, color=GRID, alpha=0.35)
            fill = ax.barh(i, 0, height=0.7, color=color, alpha=0.28)[0]
            text = ax.text(0.01, i, "", color=color, fontsize=7.5,
                           family="monospace", va="center")
            self.energy_rows.append(text)
            self.energy_fill.append(fill)

        self.energy_total = ax.text(0.0, len(SPECIES) + 1.4, "", color=TEXT,
                                    fontsize=8, va="center")

    def _build_environment(self):
        ax = self.ax_env = self.fig.add_axes([0.785, 0.325, 0.20, 0.235])
        fit_axes(ax, "Environment & resources")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(6.4, -0.3)
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)

        self.env_bars = {}
        self.env_values = {}
        rows = [("Light", "#ffd54f"), ("Radiation", "#4dd0e1"), ("World full", "#9e9e9e")]
        for i, (name, color) in enumerate(rows):
            ax.text(0.0, i, name, color=TEXT, fontsize=8, va="center")
            ax.barh(i, 0.55, left=0.27, height=0.5, color=GRID, alpha=0.5)
            self.env_bars[name] = ax.barh(i, 0, left=0.27, height=0.5, color=color, alpha=0.9)[0]
            self.env_values[name] = ax.text(0.86, i, "", color=TEXT, fontsize=8, va="center")

        self.remains_text = ax.text(0.0, 3.3, "", color=REMAINS_COLOR, fontsize=8.5,
                                    va="center", weight="bold")
        self.resource_text = ax.text(0.0, 4.5, "", color=TEXT, fontsize=8,
                                     va="top", family="monospace")

    def _build_events(self):
        ax = self.ax_events = self.fig.add_axes([0.785, 0.09, 0.20, 0.205])
        fit_axes(ax, "Recent events")
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlim(0, 1)
        ax.set_ylim(EVENT_LINES, -0.2)
        for spine in ("top", "right", "bottom", "left"):
            ax.spines[spine].set_visible(False)

        self.event_texts = [
            ax.text(0.0, i + 0.5, "", color=MUTED, fontsize=7, family="monospace", va="center")
            for i in range(EVENT_LINES)
        ]

    def _build_controls(self):
        fig = self.fig

        self.ax_play = fig.add_axes([0.03, 0.045, 0.075, 0.055])
        self.btn_play = Button(self.ax_play, "Play", color=PANEL, hovercolor=GRID)
        self.btn_play.on_clicked(lambda _e: self.toggle_pause())

        self.ax_step = fig.add_axes([0.115, 0.045, 0.075, 0.055])
        self.btn_step = Button(self.ax_step, "Step", color=PANEL, hovercolor=GRID)
        self.btn_step.on_clicked(lambda _e: self.step(1))

        self.ax_speed = fig.add_axes([0.235, 0.058, 0.13, 0.03])
        self.speed_slider = Slider(
            self.ax_speed, "", 0, len(SPEEDS) - 1, valinit=self.speed_index,
            valstep=1, color="#4dd0e1")
        self.speed_slider.valtext.set_visible(False)
        self.speed_slider.on_changed(self._on_speed)
        self.speed_label = fig.text(0.188, 0.073, "Speed", color=TEXT, fontsize=9, va="center")
        self.speed_value = fig.text(0.372, 0.073, "", color=TEXT, fontsize=9, va="center")

        self.ax_remains = fig.add_axes([0.45, 0.045, 0.085, 0.055])
        self.btn_remains = Button(self.ax_remains, "Remains: on", color=PANEL, hovercolor=GRID)
        self.btn_remains.on_clicked(lambda _e: self.toggle_remains())

        for button in (self.btn_play, self.btn_step, self.btn_remains):
            button.label.set_color(TEXT)
            button.label.set_fontsize(10)
        self.btn_remains.label.set_fontsize(9)
        for ax in (self.ax_play, self.ax_step, self.ax_remains):
            for spine in ax.spines.values():
                spine.set_color(GRID)
        self.ax_speed.set_facecolor(GRID)

        self._update_speed_text()

    # ----------------------------------------------------------- control

    @property
    def speed(self):
        return SPEEDS[self.speed_index]

    def _update_speed_text(self):
        value = self.speed
        self.speed_value.set_text("max" if value == "max" else f"{value} turns/s")
        self.btn_play.label.set_text("Play" if self.paused else "Pause")

    def _on_speed(self, value):
        self.speed_index = int(round(value))
        self._acc = 0.0
        self._update_speed_text()

    def set_speed_index(self, index):
        index = max(0, min(len(SPEEDS) - 1, index))
        self.speed_slider.set_val(index)     # triggers _on_speed

    def toggle_pause(self):
        self.paused = not self.paused
        self._acc = 0.0
        self._last_tick = None
        self._update_speed_text()
        self.fig.canvas.draw_idle()

    def toggle_remains(self):
        self.show_remains = not self.show_remains
        self.btn_remains.label.set_text("Remains: on" if self.show_remains else "Remains: off")
        self.refresh()

    def _advance(self, turns=None, deadline=None):
        """
        Run turns with the simulation's own printing silenced: `turns` of
        them, or as many as fit before `deadline` (a perf_counter time).
        Without a recorder, the viewer notes the populations after every
        turn so its history graph has no gaps.
        """
        done = 0
        with contextlib.redirect_stdout(io.StringIO()):
            while True:
                if turns is not None and done >= turns:
                    break
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                self.sim.advance_turn()
                done += 1
                if self.recorder is None:
                    self._remember(take_snapshot(self.world))
        return done

    def step(self, turns=1):
        """Advance the simulation and redraw."""
        self._advance(turns=turns)
        self.refresh()

    def _on_key(self, event):
        key = event.key
        if key == " ":
            self.toggle_pause()
        elif key == "right":
            self.step(1)
        elif key == "up":
            self.set_speed_index(self.speed_index + 1)
        elif key == "down":
            self.set_speed_index(self.speed_index - 1)
        elif key == "r":
            self.toggle_remains()
        elif key == "c":
            self.selected = None
            self.refresh()

    def _on_click(self, event):
        if event.inaxes is not self.ax_map or event.xdata is None:
            return

        snap = take_snapshot(self.world)
        if not snap.organisms:
            return

        reach = max(snap.width, snap.height) * 0.035
        best, best_key = None, None
        for view in snap.organisms:
            d = ((view.x - event.xdata) ** 2 + (view.y - event.ydata) ** 2) ** 0.5
            if d >= reach:
                continue
            # On a tie (an animal standing on a plant) prefer the animal
            key = (round(d, 6), 1 if view.kind == "Producer" else 0)
            if best_key is None or key < best_key:
                best, best_key = view, key

        self.selected = best.ref if best else None
        self.refresh()

    # ------------------------------------------------------- animation

    def show(self):
        """Open the window and run until it is closed."""
        self._enable_blit()
        self._timer = self.fig.canvas.new_timer(interval=FRAME_INTERVAL_MS)
        self._timer.add_callback(self._on_frame)
        self._timer.start()
        plt.show()

    # Blitting: the map is redrawn every frame on top of a saved copy of the
    # rest of the window, which is only redrawn a few times a second.
    def _enable_blit(self):
        if self._blit or not self.fig.canvas.supports_blit:
            return
        self._blit = True
        self._bg = None
        for artist in self._animated:
            artist.set_animated(True)
        self._draw_cid = self.fig.canvas.mpl_connect("draw_event", self._on_draw)
        self.fig.canvas.draw_idle()

    def _disable_blit(self):
        if not self._blit:
            return
        self._blit = False
        self._bg = None
        self.fig.canvas.mpl_disconnect(self._draw_cid)
        for artist in self._animated:
            artist.set_animated(False)

    def _on_draw(self, event):
        if event is not None and event.canvas is not self.fig.canvas:
            return
        self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)
        self._draw_animated()

    def _draw_animated(self):
        for artist in self._animated:
            self.fig.draw_artist(artist)

    def _blit_map(self):
        if self._bg is None:
            self.fig.canvas.draw_idle()
            return
        canvas = self.fig.canvas
        canvas.restore_region(self._bg)
        self._draw_animated()
        canvas.blit(self.fig.bbox)
        canvas.flush_events()

    def _on_frame(self):
        if self.paused:
            self._last_tick = None
            return

        now = time.perf_counter()
        if self._last_tick is None:
            self._last_tick = now
            return
        dt = now - self._last_tick
        self._last_tick = now

        if self.speed == "max":
            self._advance(deadline=now + MAX_SPEED_BUDGET)
        else:
            self._acc = min(self._acc + dt * self.speed, self.speed)
            turns = int(self._acc)
            if turns:
                self._acc -= turns
                self._advance(turns=turns)

        if not self._blit or now - self._last_panels >= PANEL_PERIOD:
            self._last_panels = now
            self.refresh()               # everything
        else:
            self.refresh_map()           # just the map, fast

    # ----------------------------------------------------------- drawing

    def refresh(self):
        snap = take_snapshot(self.world)
        self._remember(snap)

        self._draw_map(snap)
        self._draw_population(snap)
        self._draw_history(snap)
        self._draw_energy(snap)
        self._draw_environment(snap)
        self._draw_events(snap)

        self.fig.canvas.draw_idle()
        return snap

    def refresh_map(self):
        """Cheap per-frame update: only the map artists are redrawn."""
        snap = take_snapshot(self.world)
        self._remember(snap)
        self._draw_map(snap)
        self._blit_map()
        return snap

    def _remember(self, snap):
        if self.history and self.history[-1][0] == snap.turn:
            self.history[-1] = (snap.turn, dict(snap.counts))
        elif self.history and snap.turn < self.history[-1][0]:
            self.history.clear()
            self.history.append((snap.turn, dict(snap.counts)))
        else:
            self.history.append((snap.turn, dict(snap.counts)))

    def _draw_map(self, snap):
        by_species = {name: [] for name in SPECIES}
        for view in snap.organisms:
            by_species[view.species].append(view)

        for species, scatter in self.scatters.items():
            members = by_species[species]
            if members:
                scatter.set_offsets(np.array([[m.x, m.y] for m in members]))
                scatter.set_sizes(np.array(
                    [marker_size(m.kind, m.fullness) for m in members]))
            else:
                scatter.set_offsets(np.empty((0, 2)))
                scatter.set_sizes(np.array([]))

        patches = snap.remains_patches if self.show_remains else []
        if patches:
            self.remains_scatter.set_offsets(np.array([[x, y] for x, y, _ in patches]))
            self.remains_scatter.set_sizes(np.array([remains_size(a) for _, _, a in patches]))
        else:
            self.remains_scatter.set_offsets(np.empty((0, 2)))
            self.remains_scatter.set_sizes(np.array([]))

        # selected organism
        chosen = None
        if self.selected is not None:
            for view in snap.organisms:
                if view.ref is self.selected:
                    chosen = view
                    break
            if chosen is None:               # it died or was removed
                self.selected = None

        if chosen:
            self.selection_ring.set_offsets(np.array([[chosen.x, chosen.y]]))
            self.info_text.set_text(
                f"{chosen.name}\n"
                f"{chosen.species} ({chosen.kind})\n"
                f"energy {chosen.energy:6.1f}  ({chosen.fullness * 100:3.0f}% full)\n"
                f"age    {chosen.age}\n"
                f"at     ({chosen.x:.1f}, {chosen.y:.1f})")
            self.info_text.set_visible(True)
        else:
            self.selection_ring.set_offsets(np.empty((0, 2)))
            self.info_text.set_visible(False)

        season = ""
        if snap.seasonal:
            season = "   |   season: " + (
                "bright" if snap.light > 0.85 else "dim" if snap.light < 0.65 else "mild")
        self.map_title.set_text(
            f"Turn {snap.turn}    light {snap.light:.2f}{season}")

    def _draw_population(self, snap):
        peak = max([c for c in snap.counts.values()] + [10])
        scale = 1.0 / peak ** 0.5            # square-root scale: small species stay visible

        for i, species in enumerate(SPECIES):
            count = snap.counts[species]
            length = (count ** 0.5) * scale * 0.95
            self.pop_bars[i].set_width(length)
            self.pop_bars[i].set_x(0.30)
            self.pop_labels[i].set_position((0.0, i))
            self.pop_counts[i].set_position((0.30 + length + 0.02, i))
            self.pop_counts[i].set_text(str(count))

        self.pop_total.set_text(
            f"{snap.total_population} / {snap.population_limit} alive")

    def _history_points(self):
        """(turn, counts) pairs: the recorder's full history if there is one
        (no gaps at high speed), otherwise what the viewer has seen itself."""
        if self.recorder is not None and self.recorder.rows:
            return [(r["turn"], r) for r in self.recorder.rows]
        return list(self.history)

    def _draw_history(self, snap):
        points = self._history_points()
        if not points:
            return

        end = points[-1][0]
        start = max(0, end - HISTORY_WINDOW)
        points = [(t, c) for t, c in points if t >= start]

        turns = [t for t, _ in points]
        top = 10
        for species, line in self.hist_lines.items():
            values = [c.get(species, 0) for _, c in points]
            line.set_data(turns, values)
            top = max(top, max(values))

        self.ax_hist.set_xlim(start, max(end, start + 50))
        self.ax_hist.set_ylim(0, max(12, top * 1.25))

    def _draw_energy(self, snap):
        for i, species in enumerate(SPECIES):
            stats = snap.energy[species]
            if stats.n:
                text = f"{species[:9]:<10}{stats.mean:>6.0f}{stats.low:>6.0f}{stats.high:>6.0f}"
                cap = max(1.0, snap.energy and self._cap(species))
                fill = max(0.0, min(1.0, stats.mean / cap))
            else:
                text = f"{species[:9]:<10}{'-':>6}{'-':>6}{'-':>6}"
                fill = 0.0
            self.energy_rows[i].set_text(text)
            self.energy_fill[i].set_width(fill)

        self.energy_total.set_text(f"total energy alive: {snap.total_energy:,.0f}")

    @staticmethod
    def _cap(species):
        from Interface.snapshot import holding_capacity
        return holding_capacity(species)

    def _draw_environment(self, snap):
        values = {
            "Light": snap.light,
            "Radiation": snap.radiation,
            "World full": snap.total_population / max(1, snap.population_limit),
        }
        for name, value in values.items():
            value = max(0.0, min(1.0, value))
            self.env_bars[name].set_width(0.55 * value)
            self.env_values[name].set_text(f"{value * 100:.0f}%")

        self.remains_text.set_text(
            f"Organic remains: {snap.remains_total:,.0f}  ({len(snap.remains_patches)} patches)")

        if snap.resources:
            lines = [f"{name}: {qty:g} units" for name, qty in snap.resources[:5]]
        else:
            lines = ["Resources: none placed"]
        self.resource_text.set_text("\n".join(lines))

    def _draw_events(self, snap):
        events = list(self.detector.events)[-EVENT_LINES:] if self.detector else []
        events.reverse()                     # newest first

        for i, text in enumerate(self.event_texts):
            if i < len(events):
                e = events[i]
                label = e.kind.replace("_", " ")
                short = f"{e.turn:>4} {label[:27]:<27} {e.species[:9]}"
                text.set_text(short)
                text.set_color(EVENT_COLORS.get(e.kind, MUTED))
            else:
                text.set_text("")

        if not events and self.detector is not None:
            self.event_texts[0].set_text("nothing notable yet")
            self.event_texts[0].set_color(MUTED)
        elif self.detector is None:
            self.event_texts[0].set_text("no event detector attached")
            self.event_texts[0].set_color(MUTED)

    # ------------------------------------------------------------ output

    def save_png(self, path, dpi=110):
        was_blitting = self._blit
        self._disable_blit()
        try:
            self.refresh()
            self.fig.savefig(path, dpi=dpi, facecolor=self.fig.get_facecolor())
        finally:
            if was_blitting:
                self._enable_blit()
        return path

    def close(self):
        plt.close(self.fig)