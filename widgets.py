"""自绘现代控件库（Canvas 实现，零额外依赖）

包含：圆形图标按钮、主行动按钮、进度圆环、可拖动进度条、
滚动容器、现代下拉框、标签徽章、Toast 提示、模态对话框。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import icons
import theme as T


# ============================================================
# 圆形 / 圆角图标按钮
# ============================================================
class IconButton(tk.Canvas):
    """自绘图标按钮

    - variant="ghost" ：无底色，悬停时出现半透明圆底
    - variant="solid" ：始终有底色（主行动按钮）
    """

    def __init__(self, master, icon, command=None, size=34, icon_size=16,
                 variant="ghost", fg=None, bg=None, hover_bg=None,
                 active_bg=None, tooltip=None, radius=None, icon_font=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=size, height=size, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._icon = icon
        self._command = command
        self._size = size
        self._icon_size = icon_size
        self._variant = variant
        self._fg = fg or (T.TEXT_ON_ACCENT if variant == "solid" else T.TEXT_2)
        self._fg_hover = T.TEXT if variant == "ghost" else self._fg
        self._radius = radius if radius is not None else size / 2
        self._enabled = True
        self._hover = False

        if variant == "solid":
            self._bg_normal = active_bg or T.ACCENT
            self._bg_hover = hover_bg or T.ACCENT_HOVER
        else:
            self._bg_normal = self._bg
            self._bg_hover = hover_bg or T.HOVER

        self._shape = None
        self._icon_ids = []

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._redraw())

        self._redraw()
        if tooltip:
            Tooltip(self, tooltip)

    # ---------------- 绘制 ----------------
    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or self._size
        h = self.winfo_height() or self._size
        if w <= 1:
            w, h = self._size, self._size

        bg = self._bg_normal if self._enabled else self._bg
        if self._hover and self._enabled:
            bg = self._bg_hover

        if bg != self._bg:
            self._shape = icons.rounded_rect(
                self, 1, 1, w - 1, h - 1, self._radius,
                fill=bg, outline=bg)
        else:
            self._shape = None

        fg = self._fg if self._enabled else T.TEXT_3
        if self._hover and self._enabled and self._variant == "ghost":
            fg = self._fg_hover

        self._icon_ids = icons.draw_icon(
            self, self._icon, w / 2, h / 2,
            size=self._icon_size, color=fg)

    def _set_bg(self, color):
        if color != self._bg:
            self._bg = color
            try:
                self.configure(bg=color)
            except Exception:
                pass

    # ---------------- 交互 ----------------
    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _on_press(self, _e=None):
        if self._enabled:
            self.move("all", 0, 1)

    def _on_release(self, _e=None):
        if not self._enabled:
            return
        self.move("all", 0, -1)
        if self._command:
            try:
                self._command()
            except Exception as exc:
                print("[按钮] 回调异常:", exc)

    # ---------------- 对外 ----------------
    def set_icon(self, icon, fg=None):
        self._icon = icon
        if fg:
            self._fg = fg
        self._redraw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._redraw()

    def set_colors(self, bg=None, hover_bg=None, fg=None):
        if bg:
            self._bg = bg
        if bg:
            self._bg_normal = bg
        if hover_bg:
            self._bg_hover = hover_bg
        if fg:
            self._fg = fg
        self._redraw()


# ============================================================
# 主行动按钮（圆角 + 图标 + 文字）
# ============================================================
class PrimaryButton(tk.Canvas):
    """带图标和文字的圆角按钮"""

    def __init__(self, master, text, icon=None, command=None,
                 bg=None, fg=None, hover_bg=None, panel_bg=None,
                 height=34, font=None, min_width=92, pad_x=16, radius=None,
                 outline=None, tooltip=None):
        self._panel = panel_bg or T.PANEL
        super().__init__(master, height=height, bg=self._panel,
                         highlightthickness=0, bd=0, takefocus=0)
        self._text = text
        self._icon = icon
        self._command = command
        self._bg_normal = bg or T.ELEVATED
        self._bg_hover = hover_bg or T.HOVER
        self._fg = fg or T.TEXT
        self._outline = outline
        self._font = font or T.Fonts(master).body
        self._height = height
        self._pad_x = pad_x
        self._min_width = min_width
        self._radius = radius if radius is not None else T.RADIUS_SM
        self._hover = False
        self._enabled = True
        self._natural = self._calc_natural_width()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._redraw())
        self._lock_natural()
        if tooltip:
            Tooltip(self, tooltip)

    def _calc_natural_width(self):
        """按文字实际像素宽度算出按钮应该多宽"""
        try:
            import tkinter.font as tkfont
            width = tkfont.Font(font=self._font).measure(self._text)
        except Exception:
            width = len(self._text) * 9
        if self._icon:
            width += 22
        return int(max(self._min_width, width + self._pad_x * 2))

    def _lock_natural(self):
        """Canvas 默认会随父容器拉伸，这里锁成自然宽度"""
        try:
            self.configure(width=self._natural)
            self.pack_propagate(False)
        except Exception:
            pass

    def pack(self, **kw):  # noqa: D102
        super().pack(**kw)
        self._lock_natural()

    def grid(self, **kw):  # noqa: D102
        super().grid(**kw)
        self._lock_natural()

    def place(self, **kw):  # noqa: D102
        super().place(**kw)
        self._lock_natural()

    def _redraw(self):
        self.delete("all")
        h = self._height
        w = max(self.winfo_width(), self._natural)

        bg = self._bg_hover if (self._hover and self._enabled) else self._bg_normal
        if not self._enabled:
            bg = T.ELEVATED

        icons.rounded_rect(self, 1, 1, w - 1, h - 1, self._radius,
                           fill=bg,
                           outline=self._outline or bg)

        fg = self._fg if self._enabled else T.TEXT_3
        cx = w / 2
        if self._icon:
            import tkinter.font as tkfont
            try:
                fw = tkfont.Font(font=self._font).measure(self._text)
            except Exception:
                fw = len(self._text) * 8
            total = fw + 22
            start = cx - total / 2
            icons.draw_icon(self, self._icon, start + 8, h / 2, 14, fg)
            self.create_text(start + 22, h / 2, text=self._text, fill=fg,
                             font=self._font, anchor="w")
        else:
            self.create_text(cx, h / 2, text=self._text, fill=fg,
                             font=self._font, anchor="center")

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _on_press(self, _e=None):
        if self._enabled:
            self.move("all", 0, 1)

    def _on_release(self, _e=None):
        if not self._enabled:
            return
        self.move("all", 0, -1)
        if self._command:
            try:
                self._command()
            except Exception as exc:
                print("[按钮] 回调异常:", exc)

    def set_text(self, text):
        self._text = text
        self._natural = self._calc_natural_width()
        self._lock_natural()
        self._redraw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._redraw()


# ============================================================
# 进度圆环
# ============================================================
class ProgressRing(tk.Canvas):
    """循环进度圆环：背景轨道 + 高亮弧线 + 中心文字"""

    def __init__(self, master, size=20, thickness=2.6, bg=None,
                 track=None, color=None, font=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=size, height=size, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._size = size
        self._th = thickness
        self._track = track or T.BORDER
        self._color = color or T.ACCENT
        self._font = font
        self._value = 0.0
        self._text = ""
        self._dragging = False      # set_value 里会判断，必须存在
        self._lock_natural()
        self._redraw()

    def _lock_natural(self):
        """锁成正方形，否则被 place 拉伸成一大块"""
        try:
            self.configure(width=self._size, height=self._size)
            self.pack_propagate(False)
        except Exception:
            pass

    def place(self, **kw):  # noqa: D102
        super().place(**kw)
        self._lock_natural()

    def set_value(self, value, text=None):
        self._value = max(0.0, min(1.0, float(value or 0)))
        if text is not None:
            self._text = text
        self._redraw()

    def _redraw(self):
        self.delete("all")
        s = self._size
        pad = self._th / 2 + 1
        self.create_oval(pad, pad, s - pad, s - pad,
                         outline=self._track, width=self._th)
        if self._value > 0.003:
            self.create_arc(pad, pad, s - pad, s - pad,
                            start=90, extent=-359.99 * self._value,
                            style="arc", outline=self._color,
                            width=self._th)
        if self._text:
            self.create_text(s / 2, s / 2, text=self._text,
                             fill=self._color,
                             font=self._font or ("Segoe UI", 8, "bold"))


# ============================================================
# 可拖动进度条
# ============================================================
class SeekBar(tk.Canvas):
    """播放进度条：已播放部分高亮，支持点击 / 拖动跳转"""

    def __init__(self, master, on_seek=None, bg=None, height=18, pad=2):
        self._bg = bg or T.PLAYBAR
        super().__init__(master, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._on_seek = on_seek
        self._pad = pad
        self._pos = 0.0     # 0~1
        self._hover = False
        self._dragging = False
        self._enabled = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---------------- 绘制 ----------------
    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 200
        h = self.winfo_height() or 18
        if w <= 1:
            w = 200
        cy = h / 2
        x1, x2 = self._pad, w - self._pad
        track_h = 5 if (self._hover or self._dragging) else 4
        color = T.ACCENT_HOVER if (self._hover or self._dragging) else T.ACCENT

        icons.rounded_rect(self, x1, cy - track_h / 2, x2, cy + track_h / 2,
                           track_h / 2, fill=T.ELEVATED, outline=T.ELEVATED)

        pos = max(0.0, min(1.0, self._pos))
        if pos > 0.001:
            fill_x = x1 + (x2 - x1) * pos
            if fill_x - x1 < track_h:
                fill_x = x1 + track_h
            icons.rounded_rect(self, x1, cy - track_h / 2, fill_x,
                               cy + track_h / 2, track_h / 2,
                               fill=color, outline=color)
            if self._hover or self._dragging:
                r = 6.5
                icons.circle(self, fill_x, cy, r, fill="#ffffff",
                             outline=color, width=2)

    # ---------------- 交互 ----------------
    def _ratio_from_event(self, event):
        w = self.winfo_width() or 200
        x1, x2 = self._pad, w - self._pad
        if x2 <= x1:
            return 0.0
        return max(0.0, min(1.0, (event.x - x1) / (x2 - x1)))

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _on_press(self, event):
        if not self._enabled:
            return
        self._dragging = True
        self._pos = self._ratio_from_event(event)
        self._redraw()

    def _on_drag(self, event):
        if not self._dragging:
            return
        self._pos = self._ratio_from_event(event)
        self._redraw()

    def _on_release(self, event):
        if not self._dragging:
            return
        self._dragging = False
        self._pos = self._ratio_from_event(event)
        self._redraw()
        if self._on_seek and self._enabled:
            try:
                self._on_seek(self._pos)
            except Exception as exc:
                print("[进度条] 跳转异常:", exc)

    # ---------------- 对外 ----------------
    def set_pos(self, ratio, enabled=True):
        if self._dragging:
            return
        self._enabled = bool(enabled)
        self._pos = max(0.0, min(1.0, float(ratio or 0)))
        self._redraw()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._redraw()


# ============================================================
# 音量滑杆
# ============================================================
class VolumeSlider(tk.Canvas):
    """自绘音量滑杆：固定宽度，点击 / 拖动调音量"""

    def __init__(self, master, on_change=None, bg=None, width=96, height=24,
                 initial=0.7):
        self._bg = bg or T.PLAYBAR
        super().__init__(master, width=width, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._on_change = on_change
        self._value = max(0.0, min(1.0, initial))
        self._hover = False
        self._dragging = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def _geometry(self):
        w = self.winfo_width() or 96
        h = self.winfo_height() or 24
        return w, h

    def _redraw(self):
        self.delete("all")
        w, h = self._geometry()
        if w <= 1:
            w = 96
        cy = h / 2
        x1, x2 = 2, w - 2
        th = 5 if (self._hover or self._dragging) else 4
        icons.rounded_rect(self, x1, cy - th / 2, x2, cy + th / 2, th / 2,
                           fill=T.ELEVATED, outline=T.ELEVATED)
        fill_x = x1 + (x2 - x1) * self._value
        if self._value > 0.001:
            if fill_x - x1 < th:
                fill_x = x1 + th
            color = T.ACCENT_HOVER if (self._hover or self._dragging) else T.ACCENT
            icons.rounded_rect(self, x1, cy - th / 2, fill_x, cy + th / 2,
                               th / 2, fill=color, outline=color)
            if self._hover or self._dragging:
                icons.circle(self, fill_x, cy, 6, fill="#ffffff",
                             outline=color, width=2)

    def _ratio(self, event):
        w, _ = self._geometry()
        x1, x2 = 2, w - 2
        if x2 <= x1:
            return 0.0
        return max(0.0, min(1.0, (event.x - x1) / (x2 - x1)))

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _on_press(self, event):
        self._dragging = True
        self._value = self._ratio(event)
        self._redraw()
        self._fire()

    def _on_drag(self, event):
        if not self._dragging:
            return
        self._value = self._ratio(event)
        self._redraw()
        self._fire()

    def _on_release(self, _e=None):
        self._dragging = False
        self._redraw()
        self._fire()

    def _fire(self):
        if self._on_change:
            try:
                self._on_change(self._value)
            except Exception as exc:
                print("[音量] 回调异常:", exc)

    def set_value(self, value, notify=False):
        self._value = max(0.0, min(1.0, float(value or 0)))
        self._redraw()
        if notify:
            self._fire()

    def get_value(self):
        return self._value


# ============================================================
# 垂直滚动容器
# ============================================================
class ScrollFrame(ttk.Frame):
    """可滚动容器：把控件放进 self.body"""

    def __init__(self, master, bg=None, **kw):
        super().__init__(master, style="Panel.TFrame", **kw)
        self._bg = bg or T.PANEL

        self.canvas = tk.Canvas(self, bg=self._bg, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                 command=self.canvas.yview,
                                 style="Modern.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self._on_scroll_set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.body = tk.Frame(self.canvas, bg=self._bg)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self)

    def _on_scroll_set(self, first, last):
        try:
            if float(first) <= 0.0 and float(last) >= 1.0:
                self.vsb.pack_forget()
            else:
                self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        except Exception:
            pass
        self.vsb.set(first, last)

    def _on_body_configure(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _bind_wheel(self, widget):
        """滚轮事件需要绑定到每个子控件上（Tk 不做冒泡）"""
        widget.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        # 只有指针位于本容器内才滚动
        try:
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            if widget is None:
                return
            parent = widget
            inside = False
            while parent is not None:
                if parent is self:
                    inside = True
                    break
                parent = getattr(parent, "master", None)
            if not inside:
                return
        except Exception:
            pass
        delta = event.delta
        step = -1 * (delta // 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(step, "units")

    def scroll_to_top(self):
        self.canvas.yview_moveto(0.0)

    def destroy(self):
        try:
            self.unbind_all("<MouseWheel>")
        except Exception:
            pass
        super().destroy()


# ============================================================
# 现代下拉框（自绘，替代 ttk.Combobox）
# ============================================================
class Dropdown(tk.Canvas):
    """自绘下拉选择器：点击弹出深色菜单"""

    def __init__(self, master, values, on_change=None, width=112, height=34,
                 bg=None, initial=None, font=None, align_width_to=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=width, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._values = list(values)
        self._index = 0
        if initial in self._values:
            self._index = self._values.index(initial)
        self._on_change = on_change
        self._dropdown_width, self._dropdown_height = width, height
        self._hover = False
        self._menu = None
        self._font = font or T.Fonts(master).body
        self._align_width_to = align_width_to

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._open)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    def _lock_natural(self):
        try:
            self.configure(width=self._dropdown_width)
            self.pack_propagate(False)
        except Exception:
            pass

    def pack(self, **kw):  # noqa: D102
        super().pack(**kw)
        self._lock_natural()

    def grid(self, **kw):  # noqa: D102
        super().grid(**kw)
        self._lock_natural()

    def _redraw(self):
        self.delete("all")
        # 锁成固定宽度：下拉框不需要跟着窗口拉伸
        w = self._dropdown_width
        h = self.winfo_height() or self._dropdown_height
        bg = T.HOVER if (self._hover or self._menu is not None) else T.ELEVATED
        icons.rounded_rect(self, 1, 1, w - 1, h - 1, T.RADIUS_SM,
                           fill=bg, outline=T.BORDER if not self._hover else T.ACCENT)
        self.create_text(12, h / 2, text=self.get(), fill=T.TEXT,
                         font=self._font, anchor="w")
        # 下拉箭头
        ax, ay = w - 14, h / 2
        self.create_polygon(ax - 5, ay - 2.5, ax + 5, ay - 2.5, ax, ay + 3.5,
                            fill=T.TEXT_2, outline=T.TEXT_2)

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _open(self, _e=None):
        if self._menu is not None:
            self._close()
            return
        self._menu = tk.Toplevel(self)
        self._menu.overrideredirect(True)
        self._menu.configure(bg=T.BORDER)
        try:
            self._menu.attributes("-topmost", True)
        except Exception:
            pass

        row_h = 30
        pad = 4
        width = max(self.winfo_width(), 120)
        for i, value in enumerate(self._values):
            active = (i == self._index)
            lbl = tk.Label(
                self._menu, text=value, anchor="w", padx=12,
                bg=T.SELECTED if active else T.PANEL,
                fg=T.TEXT if active else T.TEXT_2,
                font=self._font, cursor="hand2",
            )
            lbl.place(x=pad, y=pad + i * row_h, width=width - pad * 2,
                      height=row_h)
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=T.HOVER,
                                                             fg=T.TEXT))
            lbl.bind("<Leave>", lambda e, l=lbl, a=active: l.configure(
                bg=T.SELECTED if a else T.PANEL,
                fg=T.TEXT if a else T.TEXT_2))
            lbl.bind("<Button-1>", lambda e, idx=i: self._choose(idx))

        total_h = pad * 2 + row_h * len(self._values)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        # 防止超出屏幕底部
        if y + total_h > self.winfo_screenheight() - 12:
            y = self.winfo_rooty() - total_h - 2
        self._menu.geometry(f"{width}x{total_h}+{x}+{y}")

        try:
            self._menu.grab_set()
        except Exception:
            pass
        self._menu.bind("<FocusOut>", lambda e: self._close())
        self._menu.bind("<Escape>", lambda e: self._close())
        self._menu.focus_set()
        self._redraw()

    def _close(self):
        if self._menu is not None:
            try:
                self._menu.grab_release()
            except Exception:
                pass
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
        self._redraw()

    def _choose(self, index):
        self._index = index
        self._close()
        if self._on_change:
            try:
                self._on_change(self.get())
            except Exception as exc:
                print("[下拉框] 回调异常:", exc)

    # ---------------- 对外 ----------------
    def get(self):
        return self._values[self._index] if self._values else ""

    def set(self, value, notify=False):
        if value in self._values:
            self._index = self._values.index(value)
            self._redraw()
            if notify and self._on_change:
                self._on_change(self.get())


# ============================================================
# 平台 / 状态徽章
# ============================================================
class Badge(tk.Canvas):
    """小圆角标签，用于平台标识、状态等"""

    def __init__(self, master, text, color=None, bg=None, width=64, height=22,
                 font=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=width, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._text = text
        self._color = color or T.ACCENT
        # 注意：不能叫 self._w / self._h —— 那是 tkinter 内部存控件路径的属性
        self._badge_w, self._badge_h = width, height
        self._font = font
        self._draw()

    def _draw(self):
        self.delete("all")
        h = self._badge_h
        w = self.winfo_width() or self._badge_w
        t = 0.16
        fill = T.mix(self._bg, self._color, t)
        icons.rounded_rect(self, 0, 0, w - 1, h - 1, h / 2 * 0.6,
                           fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self._text, fill=self._color,
                         font=self._font or T.Fonts(self).tiny)

    def set_text(self, text, color=None):
        self._text = text
        if color:
            self._color = color
        self._draw()


# ============================================================
# Toast 轻提示
# ============================================================
class Toast(tk.Frame):
    """右下角浮层提示，自动淡出（Tk 无透明度动画，用延时销毁替代）"""

    _instance = None

    @classmethod
    def show(cls, master, message, kind="info", duration=2600):
        try:
            if cls._instance is not None and cls._instance.winfo_exists():
                cls._instance.destroy()
        except Exception:
            pass
        try:
            cls._instance = cls(master, message, kind, duration)
        except Exception as exc:
            print("[提示]", message, "(浮层创建失败:", exc, ")")

    def __init__(self, master, message, kind="info", duration=2600):
        super().__init__(master, bg=T.ELEVATED, highlightthickness=1,
                         highlightbackground=T.BORDER)
        color = {"info": T.ACCENT_TEXT, "ok": T.GREEN,
                 "warn": T.AMBER, "error": T.ROSE}.get(kind, T.ACCENT_TEXT)
        icon = {"info": "info", "ok": "check", "warn": "warning",
                "error": "warning"}.get(kind, "info")

        cv = tk.Canvas(self, bg=T.ELEVATED, highlightthickness=0, bd=0,
                       height=44)
        import tkinter.font as tkfont
        f = tkfont.Font(font=T.Fonts(master).body)
        w = min(520, f.measure(message) + 74)
        cv.configure(width=w)
        cv.pack()
        icons.rounded_rect(cv, 0, 0, w - 1, 43, T.RADIUS_SM,
                           fill=T.ELEVATED, outline=T.ELEVATED)
        icons.draw_icon(cv, icon, 22, 22, 16, color)
        cv.create_text(42, 22, text=message, fill=T.TEXT, font=f, anchor="w")

        self.place(relx=0.5, rely=1.0, anchor="s", y=-116)
        self.lift()
        self.after(duration, self._hide)

    def _hide(self):
        try:
            self.destroy()
        except Exception:
            pass


# ============================================================
# 开关（画成 iOS 那种滑块）
# ============================================================
class Switch(tk.Canvas):
    """自绘开关，用于设置页的「开 / 关」"""

    def __init__(self, master, value=True, on_change=None, bg=None,
                 width=46, height=24, tooltip=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=width, height=height, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        # 注意：不能叫 self._w / self._h —— 那是 tkinter 存控件路径的属性
        self._sw, self._sh = width, height
        self._on = bool(value)
        self._on_change = on_change
        self._hover = False
        self._enabled = True
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._redraw()
        if tooltip:
            Tooltip(self, tooltip)

    def _redraw(self):
        self.delete("all")
        w, h = self._sw, self._sh
        r = h / 2
        track = T.ACCENT if self._on else T.ELEVATED
        if not self._enabled:
            track = T.PANEL_ALT
        elif self._hover:
            track = T.ACCENT_HOVER if self._on else T.HOVER
        icons.rounded_rect(self, 1, 1, w - 1, h - 1, r, fill=track,
                           outline=track)
        knob_r = r - 3
        cx = (w - r) if self._on else r
        icons.circle(self, cx, h / 2, knob_r,
                     fill="#ffffff" if self._enabled else T.TEXT_3,
                     outline="")

    def _toggle(self, _e=None):
        if not self._enabled:
            return
        self._on = not self._on
        self._redraw()
        if self._on_change:
            try:
                self._on_change(self._on)
            except Exception as exc:
                print("[开关] 回调异常:", exc)

    def _enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _leave(self, _e=None):
        self._hover = False
        self._redraw()

    def get(self) -> bool:
        return self._on

    def set(self, value, notify=False):
        self._on = bool(value)
        self._redraw()
        if notify and self._on_change:
            self._on_change(self._on)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._redraw()


# ============================================================
# 悬浮提示
# ============================================================
class Tooltip:
    """鼠标停留时显示的小气泡"""

    def __init__(self, widget, text, delay=520):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() - 10
        except Exception:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.overrideredirect(True)
        try:
            self._tip.attributes("-topmost", True)
        except Exception:
            pass
        lbl = tk.Label(self._tip, text=self.text, bg=T.ELEVATED, fg=T.TEXT,
                       font=T.Fonts(self.widget).small, padx=10, pady=5)
        lbl.pack()
        self._tip.update_idletasks()
        w = self._tip.winfo_width()
        self._tip.geometry(f"+{x - w // 2}+{y - self._tip.winfo_height()}")

    def _hide(self, _e=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def update_text(self, text):
        """运行时改提示文字（例如播放模式切换后）"""
        self.text = text
        if self._tip is not None:
            self._hide()
            self._show()


# ============================================================
# 模态对话框
# ============================================================
class ModalDialog(tk.Toplevel):
    """深色模态对话框基类：居中、可拖动、ESC 关闭"""

    def __init__(self, master, title, width=420, height=210):
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.configure(bg=T.PANEL)
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        # 不能叫 self._w / self._h —— 那是 tkinter 内部存控件路径的属性
        self._dlg_w, self._dlg_h = width, height

        self.body = tk.Frame(self, bg=T.PANEL, padx=20, pady=18)
        self.body.pack(fill=tk.BOTH, expand=True)

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def show(self):
        """居中显示并等待关闭"""
        self.update_idletasks()
        try:
            px = self.master.winfo_rootx()
            py = self.master.winfo_rooty()
            pw = self.master.winfo_width()
            ph = self.master.winfo_height()
            x = px + max(0, (pw - self._dlg_w) // 2)
            y = py + max(0, (ph - self._dlg_h) // 3)
        except Exception:
            x = y = 200
        self.geometry(f"{self._dlg_w}x{self._dlg_h}+{x}+{y}")
        self.deiconify()
        try:
            self.grab_set()
        except Exception:
            pass
        self.focus_set()
        self.wait_window(self)
        return self.result

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class PromptDialog(ModalDialog):
    """单行文本输入对话框"""

    def __init__(self, master, title="请输入", label="", initial="",
                 ok_text="确定", placeholder=""):
        super().__init__(master, title, width=430, height=200)

        tk.Label(self.body, text=label, bg=T.PANEL, fg=T.TEXT_2,
                 font=T.Fonts(master).small, anchor="w").pack(fill=tk.X)

        wrap = tk.Frame(self.body, bg=T.ELEVATED,
                        highlightthickness=1, highlightbackground=T.BORDER)
        wrap.pack(fill=tk.X, pady=(8, 4))
        self.entry = tk.Entry(wrap, bg=T.ELEVATED, fg=T.TEXT,
                              insertbackground=T.ACCENT, relief=tk.FLAT,
                              font=T.Fonts(master).body, bd=0)
        self.entry.pack(fill=tk.X, padx=10, pady=8)
        self.entry.insert(0, initial)
        self.entry.select_range(0, tk.END)
        self.entry.bind("<Return>", lambda e: self._ok())
        self.entry.bind("<FocusIn>", lambda e: wrap.configure(
            highlightbackground=T.ACCENT))
        self.entry.bind("<FocusOut>", lambda e: wrap.configure(
            highlightbackground=T.BORDER))
        if placeholder:
            tk.Label(self.body, text=placeholder, bg=T.PANEL, fg=T.TEXT_3,
                     font=T.Fonts(master).tiny, anchor="w").pack(fill=tk.X)

        row = tk.Frame(self.body, bg=T.PANEL)
        row.pack(fill=tk.X, side=tk.BOTTOM, pady=(14, 0))
        PrimaryButton(row, ok_text, command=self._ok, bg=T.ACCENT,
                      fg=T.TEXT_ON_ACCENT, hover_bg=T.ACCENT_HOVER,
                      panel_bg=T.PANEL, min_width=92).pack(side=tk.RIGHT)
        PrimaryButton(row, "取消", command=self._cancel, bg=T.ELEVATED,
                      fg=T.TEXT_2, panel_bg=T.PANEL,
                      min_width=78).pack(side=tk.RIGHT, padx=(0, 8))

        self.after(60, self.entry.focus_set)

    def _ok(self):
        self.result = self.entry.get().strip()
        self._close()


class ChoiceDialog(ModalDialog):
    """列表选择对话框，返回选中项的值"""

    def __init__(self, master, title="请选择", label="", options=None,
                 ok_text="确定", allow_new=False, new_label="＋ 新建播放列表"):
        super().__init__(master, title, width=440, height=380)
        self._options = list(options or [])
        self._allow_new = allow_new
        self._new_label = new_label
        self._selected = None

        tk.Label(self.body, text=label, bg=T.PANEL, fg=T.TEXT_2,
                 font=T.Fonts(master).small, anchor="w").pack(fill=tk.X)

        list_wrap = tk.Frame(self.body, bg=T.PANEL)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.listbox = tk.Listbox(
            list_wrap, bg=T.ELEVATED, fg=T.TEXT, relief=tk.FLAT, bd=0,
            selectbackground=T.ACCENT, selectforeground=T.TEXT_ON_ACCENT,
            highlightthickness=1, highlightbackground=T.BORDER,
            highlightcolor=T.ACCENT, activestyle="none",
            font=T.Fonts(master).body,
        )
        sb = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL,
                           command=self.listbox.yview,
                           style="Modern.Vertical.TScrollbar")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for opt in self._options:
            self.listbox.insert(tk.END, opt["label"])
        if self._options:
            self.listbox.selection_set(0)
            self._selected = self._options[0]["value"]
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-1>", lambda e: self._ok())

        row = tk.Frame(self.body, bg=T.PANEL)
        row.pack(fill=tk.X, side=tk.BOTTOM, pady=(14, 0))
        PrimaryButton(row, ok_text, command=self._ok, bg=T.ACCENT,
                      fg=T.TEXT_ON_ACCENT, hover_bg=T.ACCENT_HOVER,
                      panel_bg=T.PANEL, min_width=92).pack(side=tk.RIGHT)
        PrimaryButton(row, "取消", command=self._cancel, bg=T.ELEVATED,
                      fg=T.TEXT_2, panel_bg=T.PANEL,
                      min_width=78).pack(side=tk.RIGHT, padx=(0, 8))
        if allow_new:
            PrimaryButton(row, "＋ 新建", command=self._new,
                          bg=T.ACCENT_SOFT, fg=T.ACCENT_TEXT,
                          panel_bg=T.PANEL, min_width=86).pack(side=tk.LEFT)

    def _on_select(self, _e=None):
        sel = self.listbox.curselection()
        if sel:
            self._selected = self._options[sel[0]]["value"]

    def _new(self):
        name = PromptDialog(self.master, "新建播放列表",
                            "给新播放列表起个名字：",
                            initial="我的歌单").show()
        if name:
            self.result = {"__new__": name}
            self._close()

    def _ok(self):
        self.result = self._selected
        self._close()


class ConfirmDialog(ModalDialog):
    """确认对话框"""

    def __init__(self, master, title="确认", message="", ok_text="确定",
                 danger=False):
        super().__init__(master, title, width=400, height=170)
        tk.Label(self.body, text=message, bg=T.PANEL, fg=T.TEXT,
                 font=T.Fonts(master).body, anchor="w",
                 justify=tk.LEFT, wraplength=350).pack(fill=tk.X, pady=(6, 0))
        row = tk.Frame(self.body, bg=T.PANEL)
        row.pack(fill=tk.X, side=tk.BOTTOM, pady=(14, 0))
        PrimaryButton(row, ok_text, command=self._ok,
                      bg=T.RED if danger else T.ACCENT,
                      fg=T.TEXT_ON_ACCENT,
                      hover_bg=T.darken(T.RED) if danger else T.ACCENT_HOVER,
                      panel_bg=T.PANEL, min_width=92).pack(side=tk.RIGHT)
        PrimaryButton(row, "取消", command=self._cancel, bg=T.ELEVATED,
                      fg=T.TEXT_2, panel_bg=T.PANEL,
                      min_width=78).pack(side=tk.RIGHT, padx=(0, 8))

    def _ok(self):
        self.result = True
        self._close()
