#!/usr/bin/env python3
"""
nova_unlock/ui/hello_overlay.py
─────────────────────────────
NovaUnlock Hello Overlay v1 - Apple Intelligence Style
Theme: Cyan spectrum (matches 4-dot animation)

Features:
✦ Rotating cyan-spectrum gradient border (chaaron taraf)
✦ Original 4-dot pulsing animation
✦ "hello" greeting with Sacramento font + neon glow
✦ Ultra-smooth handwriting (dash-offset + offscreen cache)
"""
OVERLAY_DEBUG = True

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo
import math
import time
import bisect
import threading
import queue
import socket
import os
import sys
import json
import signal
import re

# Protect against desktop session manager signals (SIGHUP/SIGTERM during KDE load)
for _sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, signal.SIG_IGN)
    except Exception:
        pass

SOCKET_PATH = "/tmp/nova_hello.sock"

# ── Color Palette ─────────────────────────────────────────────────────────
PURE_WHITE = (1.0, 1.0, 1.0)
SOFT_WHITE = (0.88, 0.91, 0.96)
FADED = (0.50, 0.54, 0.60)
ACCENT = (0.0, 0.75, 1.0)

DOT_COLORS = [
    (0.00, 0.85, 1.00),
    (0.00, 0.65, 0.95),
    (0.15, 0.80, 1.00),
    (0.00, 0.72, 0.88),
]

BORDER_COLORS = [
    (0.00, 0.45, 0.95),
    (0.00, 0.70, 1.00),
    (0.10, 0.90, 1.00),
    (0.20, 1.00, 0.95),
    (0.00, 0.85, 1.00),
    (0.30, 0.60, 1.00),
]

HELLO_COLORS = [
    (0.00, 0.80, 1.00),
    (0.20, 0.65, 1.00),
    (0.10, 0.95, 1.00),
]

BORDER_THICKNESS = 90
MAX_LIVE_WORDS = 6
FADE_SPEED = 12.0
SLIDE_SPEED = 8.0
SLIDE_DISTANCE = 20.0

HELLO_FONT_CANDIDATES = [
    "Sacramento",
    "Great Vibes",
    "Allura",
    "Snell Roundhand",
    "Dancing Script",
    "Brush Script MT",
    "Comic Sans MS",
    "Sans",
]

# Apple-style continuous "hello" (single stroke). Relative SVG is parsed once.
HELLO_SVG_D = (
    "M201.8,149.5c0,0-21.3-116.6,0.7-113.9s32.8,94.2,32.8,122.9"
    "s-14.5,43.7-29.4,16.1s44.2-99.6,75.6-103.2s29.4,51.1,29.4,51.1"
    "s1.9,22.9-11,22.4s-25.8-23.4,1-41.2s73.3-27.4,73.3,19.2"
    "s-15.6,64.9-33.8,64.9s-5.5-26.3,15.6-52.6s74.4-74.4,74.4-74.4"
    "s-30.4,50.6-30.4,83.4s9.2,42.6,25.8,40.7s36.7-25.8,46.9-51.1"
    "s29.4-108.5,29.4-108.5s0,75.7-7.3,101.5s7.3,34.8,21.1,32.1"
    "s41.3-26.3,51.5-50.1s22.9-75.2,36.7-76.6s10.1,16.1,10.1,16.1"
    "s-11.5,14.2,0.5,14.2s56.9-18.8,86.8-8.7"
)

_SVG_TOKEN_RE = re.compile(
    r"[MmCcSsLlHhVvZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?"
)


def _parse_svg_path(d):
    """Parse SVG path into absolute M/C/L commands (once)."""
    tokens = _SVG_TOKEN_RE.findall(d)
    cmds = []
    i = 0
    cx = cy = 0.0
    sx = sy = 0.0
    prev_cmd = None
    prev_cpx = prev_cpy = None

    def _nums(n):
        nonlocal i
        out = [float(tokens[i + k]) for k in range(n)]
        i += n
        return out

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
        else:
            cmd = prev_cmd
            if cmd == "M":
                cmd = "L"
            elif cmd == "m":
                cmd = "l"

        if cmd == "M":
            x, y = _nums(2)
            cx, cy = x, y
            sx, sy = x, y
            cmds.append(("M", x, y))
            prev_cpx = prev_cpy = None
        elif cmd == "m":
            x, y = _nums(2)
            cx += x
            cy += y
            sx, sy = cx, cy
            cmds.append(("M", cx, cy))
            prev_cpx = prev_cpy = None
        elif cmd == "C":
            x1, y1, x2, y2, x, y = _nums(6)
            cmds.append(("C", x1, y1, x2, y2, x, y))
            prev_cpx, prev_cpy = x2, y2
            cx, cy = x, y
        elif cmd == "c":
            x1, y1, x2, y2, x, y = _nums(6)
            cmds.append(("C", cx + x1, cy + y1, cx + x2, cy + y2, cx + x, cy + y))
            prev_cpx, prev_cpy = cx + x2, cy + y2
            cx, cy = cx + x, cy + y
        elif cmd in ("S", "s"):
            if cmd == "S":
                x2, y2, x, y = _nums(4)
            else:
                rx2, ry2, rx, ry = _nums(4)
                x2, y2, x, y = cx + rx2, cy + ry2, cx + rx, cy + ry
            if prev_cmd in ("C", "c", "S", "s") and prev_cpx is not None:
                x1 = 2.0 * cx - prev_cpx
                y1 = 2.0 * cy - prev_cpy
            else:
                x1, y1 = cx, cy
            cmds.append(("C", x1, y1, x2, y2, x, y))
            prev_cpx, prev_cpy = x2, y2
            cx, cy = x, y
        elif cmd == "L":
            x, y = _nums(2)
            cmds.append(("L", x, y))
            cx, cy = x, y
            prev_cpx = prev_cpy = None
        elif cmd == "l":
            x, y = _nums(2)
            cx += x
            cy += y
            cmds.append(("L", cx, cy))
            prev_cpx = prev_cpy = None
        elif cmd == "H":
            (x,) = _nums(1)
            cmds.append(("L", x, cy))
            cx = x
            prev_cpx = prev_cpy = None
        elif cmd == "h":
            (x,) = _nums(1)
            cx += x
            cmds.append(("L", cx, cy))
            prev_cpx = prev_cpy = None
        elif cmd == "V":
            (y,) = _nums(1)
            cmds.append(("L", cx, y))
            cy = y
            prev_cpx = prev_cpy = None
        elif cmd == "v":
            (y,) = _nums(1)
            cy += y
            cmds.append(("L", cx, cy))
            prev_cpx = prev_cpy = None
        elif cmd in ("Z", "z"):
            cmds.append(("L", sx, sy))
            cx, cy = sx, sy
            prev_cpx = prev_cpy = None
        else:
            break
        prev_cmd = cmd
    return cmds


_HELLO_SVG_PATH = _parse_svg_path(HELLO_SVG_D)


def _smootherstep(t):
    """Zero jerk at ends — silkier than smoothstep."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _write_ease(t):
    """Pen-down ease: soft attack, fluid middle, gentle settle."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    s = _smootherstep(t)
    # tiny ease-in bias so the first stroke doesn't "pop"
    return s * s * (1.6 - 0.6 * s)


class JarvisOverlay(Gtk.Window):
    # Hello timing (seconds) — keep in sync with autohide
    HELLO_WRITE = 2.55
    HELLO_PAUSE = 0.12
    NAME_WRITE = 0.85
    HELLO_HOLD = 1.55
    HELLO_FADE = 0.75

    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._text = ""
        self._display_text = ""
        self._state = "idle"
        self._audio_rms = 0.0
        self._rms_smooth = 0.0
        self._bar_heights = [0.0] * 7
        self._visible = False
        self._opacity = 0.0
        self._target_op = 0.0
        self._slide_y = SLIDE_DISTANCE
        self._target_sy = 0.0
        self._phase = 0.0
        self._border_phase = 0.0
        self._hello_phase = 0.0
        self._last_t = time.time()
        self._queue = queue.Queue()
        self._word_times = {}
        self._hide_timer = None
        self._hold_until = 0.0
        self._border_intensity = 0.0
        self._hello_font = self._pick_cursive_font()

        self._hello_path_cache = None
        self._hello_layout = None
        self._hello_stroke_surf = None
        self._hello_stroke_key = None
        self._hello_stroke_progress = -1.0
        self._hello_dirty = None
        self._frame_clock = None

        self._setup_window()
        self.connect("delete-event", self._on_delete_event)
        self.connect("unmap-event", self._on_unmap_event)
        self.connect("realize", self._on_realize)
        self._topmost_tick_counter = 0

        da = Gtk.DrawingArea()
        da.connect("draw", self._draw)
        self.add(da)
        self._da = da

        GLib.timeout_add_full(GLib.PRIORITY_HIGH, 8, self._tick)

    def _hello_total(self):
        return (
            self.HELLO_WRITE
            + self.HELLO_PAUSE
            + self.NAME_WRITE
            + self.HELLO_HOLD
            + self.HELLO_FADE
        )

    def _on_realize(self, *_):
        try:
            clock = self.get_frame_clock()
            if clock:
                self._frame_clock = clock
                clock.connect("update", self._on_frame_update)
                clock.begin_updating()
        except Exception:
            pass

    def _on_frame_update(self, clock, *_):
        if self._state == "hello" and (self._visible or self._opacity > 0.01):
            try:
                self._da.queue_draw()
            except Exception:
                pass
        return True

    def _on_delete_event(self, widget, event):
        if self._state == "hello" and time.time() < self._hold_until:
            return True
        return False

    def _on_unmap_event(self, widget, event):
        if self._state == "hello" and time.time() < self._hold_until:
            GLib.idle_add(self._force_topmost)
            return True
        return False

    def _force_topmost(self):
        try:
            if not self.get_visible():
                self.show_all()
                self._visible = True
            self.set_keep_above(True)
            self.stick()
            self.present()
            win = self.get_window()
            if win:
                win.raise_()
                win.show()
        except Exception:
            pass

    def _pick_cursive_font(self):
        try:
            import subprocess
            result = subprocess.run(
                ["fc-list", ":family"],
                capture_output=True, text=True, timeout=2,
            )
            installed = result.stdout.lower()
            for font in HELLO_FONT_CANDIDATES:
                if font.lower() in installed:
                    if OVERLAY_DEBUG:
                        print(f"Hello font: {font}", flush=True)
                    return font
        except Exception:
            pass
        return "Sans"

    def _setup_window(self):
        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_sensitive(False)
        self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        self.stick()

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        if not monitor and display and display.get_n_monitors() > 0:
            monitor = display.get_monitor(0)

        if monitor:
            geo = monitor.get_geometry()
            self._sw = geo.width
            self._sh = geo.height
            gx, gy = geo.x, geo.y
        else:
            self._sw = 1920
            self._sh = 1200
            gx, gy = 0, 0

        self.set_size_request(self._sw, self._sh)
        self.move(gx, gy)

        self.realize()
        region = cairo.Region(cairo.RectangleInt(0, 0, 0, 0))
        self.get_window().input_shape_combine_region(region, 0, 0)

    # ══════════════════════════════════════════════════════════════════════
    #  MAIN DRAW
    # ══════════════════════════════════════════════════════════════════════

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if self._opacity < 0.005 and self._border_intensity < 0.005:
            return

        if self._state == "hello":
            if self._opacity < 0.01:
                return
            cr.save()
            if self._slide_y != 0:
                cr.translate(0, self._slide_y)
            self._draw_hello(cr, w, h)
            cr.restore()
            return

        if self._border_intensity > 0.005:
            self._draw_ai_border(cr, w, h)

        if self._opacity < 0.005:
            return

        hud_h = 200
        hud_y_offset = h - hud_h - 60

        cr.save()
        cr.translate(0, hud_y_offset + self._slide_y)
        if self._state == "listening" and not self._display_text:
            self._draw_premium_dots(cr, w, hud_h)
        elif self._state == "processing":
            self._draw_premium_dots(cr, w, hud_h)
            if self._display_text:
                self._draw_words(cr, w, hud_h, below=True)
        else:
            if self._display_text:
                self._draw_words(cr, w, hud_h)
        cr.restore()

    # ══════════════════════════════════════════════════════════════════════
    #  Apple Intelligence Border
    # ══════════════════════════════════════════════════════════════════════

    def _draw_ai_border(self, cr, w, h):
        intensity = self._border_intensity
        thickness = BORDER_THICKNESS

        for x_offset in range(0, w, 80):
            t = (x_offset / max(w, 1)) * 0.25
            color = self._sample_border_color(t)
            self._paint_edge_segment(
                cr, x_offset, 0, 80, thickness, color, intensity, side="top"
            )

        for y_offset in range(0, h, 80):
            t = 0.25 + (y_offset / max(h, 1)) * 0.25
            color = self._sample_border_color(t)
            self._paint_edge_segment(
                cr, w - thickness, y_offset, thickness, 80,
                color, intensity, side="right",
            )

        for x_offset in range(w, 0, -80):
            t = 0.5 + ((w - x_offset) / max(w, 1)) * 0.25
            color = self._sample_border_color(t)
            self._paint_edge_segment(
                cr, x_offset - 80, h - thickness, 80, thickness,
                color, intensity, side="bottom",
            )

        for y_offset in range(h, 0, -80):
            t = 0.75 + ((h - y_offset) / max(h, 1)) * 0.25
            color = self._sample_border_color(t)
            self._paint_edge_segment(
                cr, 0, y_offset - 80, thickness, 80,
                color, intensity, side="left",
            )

        corner_size = thickness * 2.5
        corners = [
            (0, 0, 0.0),
            (w, 0, 0.25),
            (w, h, 0.5),
            (0, h, 0.75),
        ]
        for cx, cy, t_off in corners:
            color = self._sample_border_color(t_off + 0.125)
            pulse = 0.85 + 0.15 * math.sin(self._border_phase * 1.2 + t_off * 6.28)
            grad = cairo.RadialGradient(cx, cy, 0, cx, cy, corner_size)
            grad.add_color_stop_rgba(0.0, color[0], color[1], color[2], 0.55 * intensity * pulse)
            grad.add_color_stop_rgba(0.5, color[0], color[1], color[2], 0.25 * intensity * pulse)
            grad.add_color_stop_rgba(1.0, color[0], color[1], color[2], 0.0)
            cr.set_source(grad)
            cr.rectangle(0, 0, w, h)
            cr.fill()

    def _sample_border_color(self, t):
        rotation = (self._border_phase * 0.15) % 1.0
        t_rot = (t + rotation) % 1.0
        n = len(BORDER_COLORS)
        idx_f = t_rot * n
        i0 = int(idx_f) % n
        i1 = (i0 + 1) % n
        blend = idx_f - int(idx_f)
        c0 = BORDER_COLORS[i0]
        c1 = BORDER_COLORS[i1]
        return (
            c0[0] * (1 - blend) + c1[0] * blend,
            c0[1] * (1 - blend) + c1[1] * blend,
            c0[2] * (1 - blend) + c1[2] * blend,
        )

    def _paint_edge_segment(self, cr, x, y, ew, eh, color, intensity, side):
        r, g, b = color
        if side == "top":
            grad = cairo.LinearGradient(0, y, 0, y + eh)
            grad.add_color_stop_rgba(0.0, r, g, b, 0.65 * intensity)
            grad.add_color_stop_rgba(0.4, r, g, b, 0.30 * intensity)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
        elif side == "bottom":
            grad = cairo.LinearGradient(0, y, 0, y + eh)
            grad.add_color_stop_rgba(0.0, r, g, b, 0.0)
            grad.add_color_stop_rgba(0.6, r, g, b, 0.30 * intensity)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.65 * intensity)
        elif side == "left":
            grad = cairo.LinearGradient(x, 0, x + ew, 0)
            grad.add_color_stop_rgba(0.0, r, g, b, 0.65 * intensity)
            grad.add_color_stop_rgba(0.4, r, g, b, 0.30 * intensity)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.0)
        else:
            grad = cairo.LinearGradient(x, 0, x + ew, 0)
            grad.add_color_stop_rgba(0.0, r, g, b, 0.0)
            grad.add_color_stop_rgba(0.6, r, g, b, 0.30 * intensity)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.65 * intensity)
        cr.set_source(grad)
        cr.rectangle(x, y, ew, eh)
        cr.fill()

    # ══════════════════════════════════════════════════════════════════════
    #  HELLO PATH CACHE — build once, dash-reveal every frame
    # ══════════════════════════════════════════════════════════════════════

    def _append_hello_native(self, cr, ox=0.0, oy=0.0, scale=1.0):
        for cmd in _HELLO_SVG_PATH:
            if cmd[0] == "M":
                cr.move_to(ox + cmd[1] * scale, oy + cmd[2] * scale)
            elif cmd[0] == "C":
                cr.curve_to(
                    ox + cmd[1] * scale, oy + cmd[2] * scale,
                    ox + cmd[3] * scale, oy + cmd[4] * scale,
                    ox + cmd[5] * scale, oy + cmd[6] * scale,
                )
            elif cmd[0] == "L":
                cr.line_to(ox + cmd[1] * scale, oy + cmd[2] * scale)

    def _build_hello_segments(self, scale):
        """Sample native path once per scale. Used only for pen-tip / timing."""
        cache_key = round(scale, 4)
        cached = self._hello_path_cache
        if cached and cached.get("key") == cache_key:
            return cached

        dense_pts = []
        dists = []
        weights = []
        total_len = 0.0
        total_w = 0.0
        cur_x = cur_y = 0.0
        prev_dx = prev_dy = 0.0
        have_prev = False
        minx = miny = 1e9
        maxx = maxy = -1e9

        def _touch(x, y):
            nonlocal minx, miny, maxx, maxy
            if x < minx:
                minx = x
            if y < miny:
                miny = y
            if x > maxx:
                maxx = x
            if y > maxy:
                maxy = y

        STEPS = 24
        for cmd in _HELLO_SVG_PATH:
            if cmd[0] == "M":
                cur_x, cur_y = cmd[1] * scale, cmd[2] * scale
                dense_pts.append((cur_x, cur_y))
                dists.append(total_len)
                weights.append(total_w)
                _touch(cur_x, cur_y)
                have_prev = False
            elif cmd[0] in ("C", "L"):
                if cmd[0] == "C":
                    x1, y1 = cmd[1] * scale, cmd[2] * scale
                    x2, y2 = cmd[3] * scale, cmd[4] * scale
                    x3, y3 = cmd[5] * scale, cmd[6] * scale

                    def _bez(t, ax=cur_x, ay=cur_y, bx=x1, by=y1, cx=x2, cy=y2, dx=x3, dy=y3):
                        mt = 1.0 - t
                        return (
                            mt**3 * ax + 3 * mt**2 * t * bx + 3 * mt * t**2 * cx + t**3 * dx,
                            mt**3 * ay + 3 * mt**2 * t * by + 3 * mt * t**2 * cy + t**3 * dy,
                        )

                    samples = STEPS
                    end_x, end_y = x3, y3
                else:
                    end_x, end_y = cmd[1] * scale, cmd[2] * scale

                    def _bez(t, ax=cur_x, ay=cur_y, dx=end_x, dy=end_y):
                        return (ax + (dx - ax) * t, ay + (dy - ay) * t)

                    samples = 8

                px, py = cur_x, cur_y
                for step in range(1, samples + 1):
                    t = step / float(samples)
                    bx, by = _bez(t)
                    ddx, ddy = bx - px, by - py
                    d = math.hypot(ddx, ddy)
                    if d <= 1e-6:
                        continue
                    turn = 0.0
                    if have_prev:
                        cross = abs(prev_dx * ddy - prev_dy * ddx)
                        turn = cross / (d + 1e-6)
                        # normalize roughly to 0..1
                        turn = min(1.0, turn / max(d, 1.0))
                    # Slow down on tight loops (e, o) — real handwriting cadence
                    wadd = d * (1.0 + 2.4 * turn)
                    total_len += d
                    total_w += wadd
                    dense_pts.append((bx, by))
                    dists.append(total_len)
                    weights.append(total_w)
                    _touch(bx, by)
                    prev_dx, prev_dy = ddx, ddy
                    have_prev = True
                    px, py = bx, by
                cur_x, cur_y = end_x, end_y

        if not dense_pts:
            dense_pts = [(0.0, 0.0)]
            dists = [0.0]
            weights = [0.0]
            minx = miny = 0.0
            maxx = maxy = 1.0

        result = {
            "key": cache_key,
            "pts": dense_pts,
            "dists": dists,
            "weights": weights,
            "total_len": max(total_len, 1.0),
            "total_w": max(total_w, 1.0),
            "bbox": (minx, miny, maxx, maxy),
        }
        self._hello_path_cache = result
        return result

    def _hello_point_at(self, data, progress):
        """Arc-length (weighted) point + tangent. O(log N)."""
        pts = data["pts"]
        weights = data["weights"]
        target = data["total_w"] * max(0.0, min(1.0, progress))
        if len(pts) == 1:
            return pts[0][0], pts[0][1], 1.0, 0.0
        idx = bisect.bisect_right(weights, target)
        if idx <= 0:
            x0, y0 = pts[0]
            x1, y1 = pts[min(1, len(pts) - 1)]
            return x0, y0, x1 - x0, y1 - y0
        if idx >= len(pts):
            x0, y0 = pts[-2]
            x1, y1 = pts[-1]
            return x1, y1, x1 - x0, y1 - y0
        prev_w = weights[idx - 1]
        next_w = weights[idx]
        seg = next_w - prev_w
        t = 0.0 if seg <= 0 else max(0.0, min(1.0, (target - prev_w) / seg))
        x0, y0 = pts[idx - 1]
        x1, y1 = pts[idx]
        return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, x1 - x0, y1 - y0

    def _hello_progress_to_arclen(self, data, progress):
        """Map eased 0..1 write progress → real path length (via weighted cadence)."""
        progress = max(0.0, min(1.0, progress))
        target_w = data["total_w"] * progress
        weights = data["weights"]
        dists = data["dists"]
        idx = bisect.bisect_right(weights, target_w)
        if idx <= 0:
            return 0.0
        if idx >= len(dists):
            return data["total_len"]
        prev_w = weights[idx - 1]
        next_w = weights[idx]
        seg = next_w - prev_w
        t = 0.0 if seg <= 0 else (target_w - prev_w) / seg
        return dists[idx - 1] + (dists[idx] - dists[idx - 1]) * t

    def _hello_get_layout(self, w, h):
        uname = "you"
        try:
            payload = (self._text or "").strip()
            if payload.lower().startswith("hello"):
                cand = payload[len("hello"):].strip().lstrip(",").strip()
                if cand:
                    uname = cand
        except Exception:
            pass
        if uname == "you":
            uname = os.environ.get("USER", "") or "you"
        suffix_text = f", {uname}"

        key = (w, h, suffix_text, self._hello_font)
        cached = self._hello_layout
        if cached and cached.get("key") == key:
            return cached

        target_hello_w = min(w * 0.34, 660.0)
        # Probe native bbox at scale=1
        probe = self._build_hello_segments(1.0)
        nminx, nminy, nmaxx, nmaxy = probe["bbox"]
        path_native_w = max(8.0, nmaxx - nminx)
        path_native_h = max(8.0, nmaxy - nminy)
        scale = max(0.55, target_hello_w / path_native_w)

        data = self._build_hello_segments(scale)
        minx, miny, maxx, maxy = data["bbox"]
        scaled_path_w = maxx - minx

        # Measure suffix once
        tmp = cairo.ImageSurface(cairo.FORMAT_A8, 8, 8)
        tcr = cairo.Context(tmp)
        tcr.select_font_face(
            self._hello_font, cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL
        )
        font_size = int(118 * scale)
        tcr.set_font_size(font_size)
        suffix_ext = tcr.text_extents(suffix_text)
        suffix_w = suffix_ext.x_advance or suffix_ext.width
        suffix_xb = suffix_ext.x_bearing
        suffix_yb = suffix_ext.y_bearing
        suffix_h = suffix_ext.height

        gap = 16.0 * scale
        total_w = scaled_path_w + gap + suffix_w
        left_margin = (w - total_w) / 2.0
        # Align native minx to left_margin
        ox = left_margin - minx
        # Vertically center path
        path_h = maxy - miny
        oy = (h - path_h) / 2.0 - miny

        end_x, end_y, _, _ = self._hello_point_at(data, 1.0)
        suffix_x = ox + end_x + gap
        # Baseline: sit on the visual center-right of the word
        suffix_y = oy + end_y + font_size * 0.12

        pad = int(36 * scale + 24)
        surf_x = int(min(left_margin, ox + minx) - pad)
        surf_y = int(min(oy + miny, suffix_y + suffix_yb) - pad)
        surf_w = int(total_w + pad * 2 + 8)
        surf_h = int(max(path_h, suffix_h) + pad * 2 + 8)
        surf_w = max(64, min(surf_w, w + pad * 2))
        surf_h = max(64, min(surf_h, h + pad * 2))

        layout = {
            "key": key,
            "uname": uname,
            "suffix_text": suffix_text,
            "scale": scale,
            "ox": ox,
            "oy": oy,
            "data": data,
            "font_size": font_size,
            "suffix_w": suffix_w,
            "suffix_h": suffix_h,
            "suffix_xb": suffix_xb,
            "suffix_yb": suffix_yb,
            "suffix_x": suffix_x,
            "suffix_y": suffix_y,
            "surf_x": surf_x,
            "surf_y": surf_y,
            "surf_w": surf_w,
            "surf_h": surf_h,
            "left_margin": left_margin,
            "total_w": total_w,
        }
        self._hello_layout = layout
        self._hello_stroke_surf = None
        self._hello_stroke_key = None
        self._hello_stroke_progress = -1.0
        return layout

    def _hello_ensure_stroke_surface(self, layout):
        key = (layout["surf_w"], layout["surf_h"], layout["scale"])
        if self._hello_stroke_surf is not None and self._hello_stroke_key == key:
            return self._hello_stroke_surf
        surf = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, layout["surf_w"], layout["surf_h"]
        )
        self._hello_stroke_surf = surf
        self._hello_stroke_key = key
        self._hello_stroke_progress = -1.0
        return surf

    def _hello_render_stroke(self, layout, progress, alpha):
        """
        Draw revealed stroke into a small offscreen buffer using dash-offset.
        Cairo dashes along the real cubics — no per-frame polyline rebuild.
        """
        surf = self._hello_ensure_stroke_surface(layout)
        # Reuse last frame if progress barely moved and alpha is stable-ish
        q = round(progress, 4)
        if q == self._hello_stroke_progress and alpha >= 0.999:
            return surf

        cr = cairo.Context(surf)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_antialias(cairo.ANTIALIAS_BEST)
        cr.set_tolerance(0.08)

        scale = layout["scale"]
        data = layout["data"]
        ox = layout["ox"] - layout["surf_x"]
        oy = layout["oy"] - layout["surf_y"]

        drawn = self._hello_progress_to_arclen(data, progress)
        total = data["total_len"]
        if drawn < 0.15:
            self._hello_stroke_progress = q
            return surf

        cr.new_path()
        self._append_hello_native(cr, ox, oy, scale)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_dash([drawn, total + 4.0])

        # Soft ambient glow
        cr.set_source_rgba(1, 1, 1, alpha * 0.18)
        cr.set_line_width(15.0 * scale)
        cr.stroke_preserve()

        # Cyan bloom (thin, cheap, sells the ink)
        cr.set_source_rgba(0.0, 0.85, 1.0, alpha * 0.22)
        cr.set_line_width(11.0 * scale)
        cr.stroke_preserve()

        # Crisp core
        cr.set_source_rgba(1, 1, 1, alpha)
        cr.set_line_width(8.2 * scale)
        cr.stroke()

        self._hello_stroke_progress = q
        return surf

    def _draw_hello(self, cr, w, h):
        layout = self._hello_get_layout(w, h)
        phase = self._hello_phase
        total = self._hello_total()
        if phase >= total and self._opacity < 0.01:
            return

        write_t = self.HELLO_WRITE
        pause_t = self.HELLO_PAUSE
        name_t = self.NAME_WRITE
        hold_t = self.HELLO_HOLD
        fade_t = self.HELLO_FADE

        if phase < write_t + pause_t + name_t + hold_t:
            fade = 1.0
        else:
            t = (phase - write_t - pause_t - name_t - hold_t) / max(fade_t, 0.001)
            fade = 1.0 - (0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t))))

        alpha = fade * self._opacity
        if alpha < 0.01:
            return

        # Glassy plate
        cr.set_source_rgba(0, 0, 0, 0.88 * fade * max(self._opacity, 0.0))
        cr.rectangle(0, 0, w, h)
        cr.fill()

        if phase < write_t:
            raw = phase / write_t
            hello_progress = _write_ease(raw)
        else:
            hello_progress = 1.0

        surf = self._hello_render_stroke(layout, hello_progress, alpha)
        cr.set_source_surface(surf, layout["surf_x"], layout["surf_y"])
        cr.paint()

        # Glowing pen + comet trail (follows weighted cadence)
        if 0.012 < hello_progress < 0.992:
            data = layout["data"]
            scale = layout["scale"]
            ox, oy = layout["ox"], layout["oy"]
            # comet: a few ghosts behind the nib
            trail = (0.0, 0.010, 0.022, 0.038, 0.058)
            for i, back in enumerate(trail):
                p = hello_progress - back
                if p <= 0.0:
                    continue
                px, py, tx, ty = self._hello_point_at(data, p)
                ex, ey = ox + px, oy + py
                falloff = 1.0 - i / float(len(trail))
                rad = (15.0 - i * 1.6) * scale
                glow = cairo.RadialGradient(ex, ey, 0, ex, ey, rad)
                if i == 0:
                    glow.add_color_stop_rgba(0.0, 1, 1, 1, 0.96 * alpha)
                    glow.add_color_stop_rgba(0.28, 0.55, 0.95, 1.0, 0.70 * alpha)
                    glow.add_color_stop_rgba(0.62, 0.0, 0.85, 1.0, 0.32 * alpha)
                    glow.add_color_stop_rgba(1.0, 0.0, 0.85, 1.0, 0.0)
                else:
                    a = 0.22 * falloff * alpha
                    glow.add_color_stop_rgba(0.0, 0.4, 0.9, 1.0, a)
                    glow.add_color_stop_rgba(1.0, 0.0, 0.85, 1.0, 0.0)
                cr.set_source(glow)
                cr.arc(ex, ey, rad, 0, 2 * math.pi)
                cr.fill()

            # tiny ink nib
            px, py, _, _ = self._hello_point_at(data, hello_progress)
            cr.set_source_rgba(1, 1, 1, 0.95 * alpha)
            cr.arc(ox + px, oy + py, 2.15 * scale, 0, 2 * math.pi)
            cr.fill()

        # ", username" — clip wipe after the stroke settles
        if phase > write_t + pause_t * 0.35:
            name_phase = phase - write_t - pause_t
            if name_phase > 0:
                if name_phase < name_t:
                    name_progress = _smootherstep(name_phase / name_t)
                else:
                    name_progress = 1.0

                suffix_text = layout["suffix_text"]
                suffix_x = layout["suffix_x"]
                suffix_y = layout["suffix_y"]
                font_size = layout["font_size"]
                suffix_w = layout["suffix_w"]

                cr.save()
                cr.select_font_face(
                    self._hello_font,
                    cairo.FONT_SLANT_ITALIC,
                    cairo.FONT_WEIGHT_NORMAL,
                )
                cr.set_font_size(font_size)
                clip_w = suffix_w * name_progress + 6
                cr.rectangle(
                    suffix_x + layout["suffix_xb"] - 3,
                    suffix_y + layout["suffix_yb"] - 4,
                    clip_w,
                    layout["suffix_h"] + 10,
                )
                cr.clip()

                cr.set_source_rgba(1, 1, 1, alpha * 0.22)
                cr.move_to(suffix_x + 1.0, suffix_y + 1.0)
                cr.show_text(suffix_text)

                cr.set_source_rgba(1, 1, 1, alpha)
                cr.move_to(suffix_x, suffix_y)
                cr.show_text(suffix_text)
                cr.restore()

        # Dirty rect for next tick (writing phase only)
        if hello_progress < 1.0:
            self._hello_dirty = (
                layout["surf_x"],
                layout["surf_y"],
                layout["surf_w"],
                layout["surf_h"],
            )
        else:
            self._hello_dirty = None

    # ══════════════════════════════════════════════════════════════════════
    #  DOTS ENGINE
    # ══════════════════════════════════════════════════════════════════════

    def _draw_premium_dots(self, cr, w, h):
        cx = w * 0.5
        cy = h * 0.5 + 10

        target = max(0.0, min(1.0, self._audio_rms))
        self._rms_smooth += (target - self._rms_smooth) * 0.22
        rms = self._rms_smooth
        phase = self._phase

        ALPINA_DEEP = (0.02, 0.05, 0.12)
        ALPINA_NAVY = (0.05, 0.12, 0.28)
        ALPINA_BLUE = (0.10, 0.35, 0.75)
        ALPINA_CYAN = (0.30, 0.70, 1.0)
        ALPINA_CHROME = (0.85, 0.92, 1.0)
        ALPINA_RED = (0.95, 0.15, 0.20)

        base_r = 70

        haze = cairo.RadialGradient(cx, cy, base_r * 1.2, cx, cy, base_r * 2.2)
        haze.add_color_stop_rgba(0.0, *ALPINA_BLUE, 0.0)
        haze.add_color_stop_rgba(0.3, *ALPINA_BLUE, 0.18 + rms * 0.15)
        haze.add_color_stop_rgba(0.7, *ALPINA_CYAN, 0.08)
        haze.add_color_stop_rgba(1.0, *ALPINA_NAVY, 0.0)
        cr.set_source(haze)
        cr.arc(cx, cy, base_r * 2.2, 0, 2 * math.pi)
        cr.fill()

        outer_ring_r = base_r * 1.45
        cr.set_source_rgba(*ALPINA_CHROME, 0.15)
        cr.set_line_width(0.8)
        cr.arc(cx, cy, outer_ring_r, 0, 2 * math.pi)
        cr.stroke()

        num_ticks = 60
        for i in range(num_ticks):
            angle = (i / num_ticks) * 2 * math.pi - math.pi / 2
            is_major = (i % 5 == 0)
            tick_len = 6 if is_major else 3
            tick_w = 1.2 if is_major else 0.6
            x1 = cx + math.cos(angle) * outer_ring_r
            y1 = cy + math.sin(angle) * outer_ring_r
            x2 = cx + math.cos(angle) * (outer_ring_r + tick_len)
            y2 = cy + math.sin(angle) * (outer_ring_r + tick_len)
            cr.set_source_rgba(*ALPINA_CHROME, 0.6 if is_major else 0.25)
            cr.set_line_width(tick_w)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        sweep_start = -math.pi / 2 + phase * 0.6
        sweep_len = math.pi * 0.4 + rms * math.pi * 0.6
        for offset in (0, 0.5, 1.0):
            cr.set_source_rgba(*ALPINA_CYAN, 0.7 - offset * 0.3)
            cr.set_line_width(2.5 + (1 - offset) * 1.5)
            cr.arc(cx, cy, outer_ring_r - 2, sweep_start, sweep_start + sweep_len)
            cr.stroke()

        tip_x = cx + math.cos(sweep_start + sweep_len) * (outer_ring_r - 2)
        tip_y = cy + math.sin(sweep_start + sweep_len) * (outer_ring_r - 2)
        tip_glow = cairo.RadialGradient(tip_x, tip_y, 0, tip_x, tip_y, 12)
        tip_glow.add_color_stop_rgba(0.0, 1, 1, 1, 1.0)
        tip_glow.add_color_stop_rgba(0.5, *ALPINA_CYAN, 0.6)
        tip_glow.add_color_stop_rgba(1.0, *ALPINA_CYAN, 0.0)
        cr.set_source(tip_glow)
        cr.arc(tip_x, tip_y, 12, 0, 2 * math.pi)
        cr.fill()

        inner_ring_r = base_r * 1.15
        num_segments = 36
        for i in range(num_segments):
            seg_angle = (i / num_segments) * 2 * math.pi
            seg_phase = (phase * 1.5 + i * 0.18) % (2 * math.pi)
            seg_active = (math.sin(seg_phase) + 1) / 2
            seg_active = max(0.15, seg_active * (0.5 + rms * 0.8))
            x1 = cx + math.cos(seg_angle) * (inner_ring_r - 1.5)
            y1 = cy + math.sin(seg_angle) * (inner_ring_r - 1.5)
            x2 = cx + math.cos(seg_angle) * (inner_ring_r + 1.5)
            y2 = cy + math.sin(seg_angle) * (inner_ring_r + 1.5)
            cr.set_source_rgba(*ALPINA_CYAN, seg_active * 0.85)
            cr.set_line_width(1.6)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

        hex_r = base_r * 0.75
        hex_rot = phase * 0.15

        cr.save()
        cr.translate(cx, cy + 2)
        cr.rotate(hex_rot)
        cr.set_source_rgba(0, 0, 0, 0.4)
        cr.move_to(hex_r, 0)
        for i in range(1, 7):
            a = i * math.pi / 3
            cr.line_to(math.cos(a) * hex_r, math.sin(a) * hex_r)
        cr.close_path()
        cr.fill()
        cr.restore()

        cr.save()
        cr.translate(cx, cy)
        cr.rotate(hex_rot)
        hex_grad = cairo.LinearGradient(0, -hex_r, 0, hex_r)
        hex_grad.add_color_stop_rgba(0.0, *ALPINA_NAVY, 1.0)
        hex_grad.add_color_stop_rgba(0.5, *ALPINA_DEEP, 1.0)
        hex_grad.add_color_stop_rgba(1.0, 0.0, 0.02, 0.08, 1.0)
        cr.set_source(hex_grad)
        cr.move_to(hex_r, 0)
        for i in range(1, 7):
            a = i * math.pi / 3
            cr.line_to(math.cos(a) * hex_r, math.sin(a) * hex_r)
        cr.close_path()
        cr.fill_preserve()
        cr.set_source_rgba(*ALPINA_CHROME, 0.6)
        cr.set_line_width(1.5)
        cr.stroke()
        cr.restore()

        core_r = 28 + rms * 18
        core_glow = cairo.RadialGradient(cx, cy, core_r * 0.5, cx, cy, core_r * 1.6)
        core_glow.add_color_stop_rgba(0.0, *ALPINA_CYAN, 0.0)
        core_glow.add_color_stop_rgba(0.4, *ALPINA_CYAN, 0.5 + rms * 0.3)
        core_glow.add_color_stop_rgba(1.0, *ALPINA_BLUE, 0.0)
        cr.set_source(core_glow)
        cr.arc(cx, cy, core_r * 1.6, 0, 2 * math.pi)
        cr.fill()

        core_grad = cairo.RadialGradient(
            cx - core_r * 0.2, cy - core_r * 0.25, 0, cx, cy, core_r
        )
        core_grad.add_color_stop_rgba(0.0, 1, 1, 1, 1.0)
        core_grad.add_color_stop_rgba(0.2, *ALPINA_CHROME, 1.0)
        core_grad.add_color_stop_rgba(0.5, *ALPINA_CYAN, 1.0)
        core_grad.add_color_stop_rgba(0.85, *ALPINA_BLUE, 1.0)
        core_grad.add_color_stop_rgba(1.0, *ALPINA_NAVY, 1.0)
        cr.set_source(core_grad)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

        cr.set_source_rgba(*ALPINA_CHROME, 0.85)
        cr.set_line_width(1.2)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.stroke()

        notch_y = cy - outer_ring_r - 4
        notch_w = 18
        cr.set_source_rgba(*ALPINA_BLUE, 0.95)
        cr.rectangle(cx - notch_w, notch_y, notch_w / 3, 4)
        cr.fill()
        cr.set_source_rgba(0.5, 0.2, 0.7, 0.95)
        cr.rectangle(cx - notch_w + notch_w / 3, notch_y, notch_w / 3, 4)
        cr.fill()
        cr.set_source_rgba(*ALPINA_RED, 0.95)
        cr.rectangle(cx, notch_y, notch_w / 3 * 2, 4)
        cr.fill()

        hl = cairo.RadialGradient(
            cx - core_r * 0.3, cy - core_r * 0.55, 0,
            cx - core_r * 0.3, cy - core_r * 0.55, core_r * 0.5,
        )
        hl.add_color_stop_rgba(0.0, 1, 1, 1, 0.75)
        hl.add_color_stop_rgba(0.5, 1, 1, 1, 0.2)
        hl.add_color_stop_rgba(1.0, 1, 1, 1, 0.0)
        cr.set_source(hl)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

    def _draw_words(self, cr, w, h, below=False):
        words = self._display_text.split()
        if not words:
            return

        now = time.time()
        fs = self._font_size(self._display_text)
        if below:
            fs = max(18, int(fs * 0.60))

        sp = self._space_w(cr, fs)
        widths_n = [self._word_w(cr, wd, fs, False) for wd in words]
        widths_b = [self._word_w(cr, wd, fs, True) for wd in words]
        last = len(words) - 1

        total_w = sum(
            widths_b[i] if (i == last and self._state == "listening") else widths_n[i]
            for i in range(len(words))
        ) + sp * max(0, len(words) - 1)

        x = (w - total_w) / 2
        y = (h / 2 + 38 + fs / 3) if below else (h / 2 + fs / 3)

        for i, word in enumerate(words):
            wk = f"{i}_{word}"
            if wk not in self._word_times:
                self._word_times[wk] = now
            age = now - self._word_times[wk]
            fade = min(1.0, age / 0.15)

            if self._state == "processing":
                r, g, b = FADED
                a, bold = fade * 0.7, False
            elif self._state == "speaking":
                word_delay = i * 0.06
                speak_fade = min(1.0, max(0.0, (age - word_delay) / 0.2))
                r, g, b = PURE_WHITE
                a, bold = speak_fade * 0.92, False
            elif i == last and self._state == "listening":
                r, g, b = PURE_WHITE
                a, bold = fade, True
                cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                cr.set_font_size(fs)
                line_progress = min(1.0, age / 0.25)
                line_w = widths_b[i] * line_progress
                cr.set_source_rgba(*ACCENT, fade * 0.65)
                cr.set_line_width(2.2)
                cr.move_to(x, y + fs * 0.22)
                cr.line_to(x + line_w, y + fs * 0.22)
                cr.stroke()
            else:
                dist = last - i
                dim = max(0.45, 1.0 - dist * 0.07)
                t = min(1.0, dist * 0.12)
                r = SOFT_WHITE[0] * (1 - t) + FADED[0] * t
                g = SOFT_WHITE[1] * (1 - t) + FADED[1] * t
                b = SOFT_WHITE[2] * (1 - t) + FADED[2] * t
                a, bold = fade * dim, False

            wt = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, wt)
            cr.set_font_size(fs)
            cr.set_source_rgba(0, 0, 0, a * 0.35)
            cr.move_to(x + 1.0, y + 1.0)
            cr.show_text(word)
            cr.set_source_rgba(r, g, b, a)
            cr.move_to(x, y)
            cr.show_text(word)
            x += (widths_b[i] if bold else widths_n[i]) + sp

    def _font_size(self, t):
        n = len(t)
        if n > 80:
            return 22
        if n > 55:
            return 28
        if n > 35:
            return 34
        return 40

    def _space_w(self, cr, fs):
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(fs)
        return cr.text_extents(" ").x_advance * 1.15

    def _word_w(self, cr, word, fs, bold):
        wt = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, wt)
        cr.set_font_size(fs)
        return cr.text_extents(word).x_advance

    # ══════════════════════════════════════════════════════════════════════
    #  ANIMATION TICK
    # ══════════════════════════════════════════════════════════════════════

    def _tick(self):
        now = time.time()
        dt = now - self._last_t
        if dt < 0:
            dt = 0.0
        elif dt > 0.08:
            dt = 0.08
        self._last_t = now

        try:
            while True:
                self._handle(self._queue.get_nowait())
        except queue.Empty:
            pass

        diff = self._target_op - self._opacity
        if abs(diff) > 0.002:
            self._opacity += diff * min(1.0, dt * FADE_SPEED)
        else:
            self._opacity = self._target_op

        sy_diff = self._target_sy - self._slide_y
        if abs(sy_diff) > 0.3:
            self._slide_y += sy_diff * min(1.0, dt * SLIDE_SPEED)
        else:
            self._slide_y = self._target_sy

        target_border = 1.0 if (self._visible and self._state != "idle") else 0.0
        if self._state == "hello":
            target_border = 0.0
        bi_diff = target_border - self._border_intensity
        if abs(bi_diff) > 0.002:
            self._border_intensity += bi_diff * min(1.0, dt * 4.0)
        else:
            self._border_intensity = target_border

        if self._opacity < 0.005 and self._border_intensity < 0.005 and self._visible:
            self.hide()
            self._visible = False
            self._text = ""
            self._display_text = ""
            self._word_times.clear()
            self._slide_y = SLIDE_DISTANCE
            self._hello_stroke_surf = None
            self._hello_layout = None

        self._phase += dt
        self._border_phase += dt
        self._hello_phase += dt

        if self._visible or self._border_intensity > 0.005:
            if self._frame_clock is None or self._state != "hello":
                self._da.queue_draw()

        return True

    # ══════════════════════════════════════════════════════════════════════
    #  COMMAND HANDLER
    # ══════════════════════════════════════════════════════════════════════

    def _handle(self, cmd):
        a = cmd.get("action")
        if a == "audio":
            lvl = cmd.get("level", 0.0)
            try:
                self._audio_rms = max(0.0, min(1.0, float(lvl)))
            except Exception:
                pass
            return

        if a == "show":
            self._state = cmd.get("state", "listening")
            self._hold_until = time.time() + (2.0 if self._state == "listening" else 1.0)
            new_text = cmd.get("text", "")
            self._text = new_text
            self._display_text = new_text
            self._word_times.clear()
            self._target_op = 1.0
            self._opacity = max(self._opacity, 0.6)
            self._slide_y = SLIDE_DISTANCE * 0.3
            self._target_sy = 0.0
            if self._hide_timer:
                GLib.source_remove(self._hide_timer)
                self._hide_timer = None
            if not self._visible:
                self.show_all()
                self._visible = True

        elif a == "update":
            new_text = cmd.get("text", "")
            if new_text != self._text:
                self._text = new_text
                all_words = new_text.split()
                if len(all_words) > MAX_LIVE_WORDS:
                    display_words = all_words[-MAX_LIVE_WORDS:]
                    self._display_text = "… " + " ".join(display_words)
                else:
                    self._display_text = new_text
                new_word_times = {}
                for i, w in enumerate(self._display_text.split()):
                    key = f"{i}_{w}"
                    new_word_times[key] = self._word_times.get(key, time.time())
                self._word_times = new_word_times
                if not self._visible:
                    self._target_op = 1.0
                    self._opacity = 0.6
                    self.show_all()
                    self._visible = True

        elif a == "final":
            final_text = cmd.get("text", "")
            self._text = final_text
            self._display_text = final_text
            self._state = "processing"
            self._word_times.clear()
            self._target_op = 1.0
            if self._hide_timer:
                GLib.source_remove(self._hide_timer)
            dur = max(4.0, len(final_text) * 0.05)
            self._hold_until = time.time() + max(8.0, dur)
            self._hide_timer = GLib.timeout_add(max(8000, int(dur * 1000)), self._autohide)

        elif a == "speaking":
            text = cmd.get("text", "")
            if len(text) > 120:
                text = text[:120] + "…"
            self._text = text
            self._display_text = text
            self._state = "speaking"
            self._word_times.clear()
            self._target_op = 1.0
            if not self._visible:
                self._opacity = 0.6
                self._slide_y = SLIDE_DISTANCE * 0.3
                self._target_sy = 0.0
                self.show_all()
                self._visible = True
            dur = max(3.0, len(text) * 0.05)
            if self._hide_timer:
                GLib.source_remove(self._hide_timer)
            self._hide_timer = GLib.timeout_add(max(8000, int(dur * 1000)), self._autohide)

        elif a == "hello":
            text = cmd.get("text", "hello")
            total = self._hello_total()
            duration = max(float(cmd.get("duration", total)), total + 0.25)
            self._text = text
            self._display_text = text
            self._state = "hello"
            self._hello_phase = 0.0
            self._target_op = 1.0
            self._opacity = 1.0
            self._slide_y = 0.0
            self._target_sy = 0.0
            self._hello_layout = None
            self._hello_stroke_surf = None
            self._hello_stroke_progress = -1.0
            self._last_t = time.time()

            if not self._visible:
                self.show_all()
                self._visible = True
            if self._hide_timer:
                GLib.source_remove(self._hide_timer)
            self._hold_until = time.time() + duration
            self._hide_timer = GLib.timeout_add(int(duration * 1000), self._autohide)

        elif a == "hide":
            if time.time() < self._hold_until:
                return
            self._target_op = 0.0
            self._target_sy = SLIDE_DISTANCE * 0.5
            self._state = "idle"

    def _autohide(self):
        self._target_op = 0.0
        self._target_sy = SLIDE_DISTANCE * 0.5
        self._state = "idle"
        self._hide_timer = None
        return False

    def push(self, cmd):
        self._queue.put(cmd)


def start_socket_server(overlay):
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o777)
    server.listen(5)
    server.settimeout(1.0)

    def _serve():
        while True:
            try:
                conn, _ = server.accept()
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                conn.close()
                if data:
                    for line in data.decode().splitlines():
                        line = line.strip()
                        if line:
                            cmd = json.loads(line)
                            GLib.idle_add(overlay.push, cmd)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Socket error: {e}", file=sys.stderr)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    print(f"Overlay v3 (CIPHER theme border) ready: {SOCKET_PATH}", flush=True)


if __name__ == "__main__":
    overlay = JarvisOverlay()
    start_socket_server(overlay)
    Gtk.main()