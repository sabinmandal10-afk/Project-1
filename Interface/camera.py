"""
A tiny 2D camera for the map: zoom, pan and follow.

Pure maths (no pygame), so it can be tested on its own. World coordinates
have y pointing up; screen coordinates have y pointing down. At zoom 1.0 and
a centred camera it matches the viewer's original full-map mapping exactly.
"""

MIN_ZOOM = 1.0
MAX_ZOOM = 5.0


class Camera:

    def __init__(self, world_w, world_h):
        self.world_w = float(world_w)
        self.world_h = float(world_h)
        self.zoom = 1.0
        self.cx = self.world_w / 2
        self.cy = self.world_h / 2
        self.follow = None          # an organism to keep centred, or None
        # target values the camera glides toward (smooth movement)
        self._zoom_goal = 1.0
        self._cx_goal = self.cx
        self._cy_goal = self.cy

    # ---------- mapping ----------

    def world_to_screen(self, wx, wy, rect):
        sx = rect.centerx + (wx - self.cx) * (rect.w / self.world_w) * self.zoom
        sy = rect.centery - (wy - self.cy) * (rect.h / self.world_h) * self.zoom
        return sx, sy

    def screen_to_world(self, sx, sy, rect):
        wx = self.cx + (sx - rect.centerx) / ((rect.w / self.world_w) * self.zoom)
        wy = self.cy - (sy - rect.centery) / ((rect.h / self.world_h) * self.zoom)
        return wx, wy

    def pixels_per_unit(self, rect):
        """Horizontal pixels per world unit at the current zoom."""
        return (rect.w / self.world_w) * self.zoom

    def visible_world(self):
        """(left, bottom, right, top) of the world currently in view."""
        half_w = self.world_w / (2 * self.zoom)
        half_h = self.world_h / (2 * self.zoom)
        return (self.cx - half_w, self.cy - half_h,
                self.cx + half_w, self.cy + half_h)

    # ---------- control ----------

    def _clamp_goal(self):
        half_w = self.world_w / (2 * self._zoom_goal)
        half_h = self.world_h / (2 * self._zoom_goal)
        self._cx_goal = max(half_w, min(self.world_w - half_w, self._cx_goal))
        self._cy_goal = max(half_h, min(self.world_h - half_h, self._cy_goal))

    def zoom_at(self, factor, wx=None, wy=None):
        """Zoom by `factor`, keeping the world point (wx, wy) under the cursor."""
        wx = self._cx_goal if wx is None else wx
        wy = self._cy_goal if wy is None else wy
        old = self._zoom_goal
        new = max(MIN_ZOOM, min(MAX_ZOOM, old * factor))
        if new == old:
            return
        # keep the chosen world point at the same relative place on screen
        ratio = old / new
        self._cx_goal = wx + (self._cx_goal - wx) * ratio
        self._cy_goal = wy + (self._cy_goal - wy) * ratio
        self._zoom_goal = new
        self._clamp_goal()

    def pan_pixels(self, dx, dy, rect):
        """Drag the map by a screen-space amount."""
        self.follow = None
        self._cx_goal -= dx / ((rect.w / self.world_w) * self._zoom_goal)
        self._cy_goal += dy / ((rect.h / self.world_h) * self._zoom_goal)
        self._clamp_goal()
        # dragging should feel immediate
        self.cx, self.cy = self._cx_goal, self._cy_goal

    def focus(self, wx, wy, zoom=None):
        if zoom is not None:
            self._zoom_goal = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._cx_goal, self._cy_goal = wx, wy
        self._clamp_goal()

    def reset(self):
        self.follow = None
        self._zoom_goal = 1.0
        self._cx_goal = self.world_w / 2
        self._cy_goal = self.world_h / 2

    def set_world_size(self, w, h):
        self.world_w, self.world_h = float(w), float(h)
        self.reset()
        self.zoom, self.cx, self.cy = 1.0, self.world_w / 2, self.world_h / 2

    def update(self, dt, follow_pos=None):
        """Glide toward the goals. `follow_pos` is the followed organism's (x, y)."""
        if self.follow is not None and follow_pos is not None:
            self._cx_goal, self._cy_goal = follow_pos
            if self._zoom_goal < 2.2:
                self._zoom_goal = 2.2
            self._clamp_goal()

        k = 1 - pow(0.0005, dt)          # frame-rate independent easing
        self.zoom += (self._zoom_goal - self.zoom) * k
        self.cx += (self._cx_goal - self.cx) * k
        self.cy += (self._cy_goal - self.cy) * k
        if abs(self.zoom - self._zoom_goal) < 1e-3:
            self.zoom = self._zoom_goal
        if abs(self.cx - self._cx_goal) < 1e-3:
            self.cx = self._cx_goal
        if abs(self.cy - self._cy_goal) < 1e-3:
            self.cy = self._cy_goal

    @property
    def is_default(self):
        return self.zoom == 1.0 and self._zoom_goal == 1.0
