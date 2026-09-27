"""首页卡片控件：封面卡片、横向卡片行、歌单/曲目网格

布局参考网易云音乐 PC 端：
- 顶部分类卡片（每日推荐 / 播客 / 心动模式 …）用横向一排
- 下面「推荐歌单」用网格，每张卡片是 封面 + 播放量 + 标题
"""
from __future__ import annotations

import tkinter as tk

import cover as C
import icons
import theme as T
import widgets as W


class CoverArt(tk.Canvas):
    """一块封面：先画兜底图，真实封面下好后自动替换"""

    def __init__(self, master, size=168, url="", seed="", radius=10,
                 bg=None, cache=None, badge="", on_open=None):
        self._bg = bg or T.PANEL
        super().__init__(master, width=size, height=size, bg=self._bg,
                         highlightthickness=0, bd=0, takefocus=0)
        self._size = size
        self._url = url or ""
        self._seed = seed or "cover"
        self._radius = radius
        self._cache = cache
        self._badge = badge
        self._on_open = on_open
        self._photo = None
        self._is_real = False
        self._hover = False

        self.bind("<Configure>", lambda e: self._redraw())
        if on_open is not None:
            self.bind("<Button-1>", lambda e: self._on_open())
        self._redraw()

    # ---------------- 绘制 ----------------
    def _redraw(self):
        self.delete("all")
        s = self._size
        photo = None
        if self._cache is not None:
            photo, self._is_real = self._cache.get(self._url, self._seed, s)
        if photo is not None:
            self._photo = photo
            self.create_image(0, 0, image=photo, anchor="nw")
        else:
            # 没有 PIL 时退化成纯色块 + 音符
            icons.rounded_rect(self, 0, 0, s - 1, s - 1, self._radius,
                               fill=T.ELEVATED, outline=T.ELEVATED)
            icons.draw_icon(self, "music", s / 2, s / 2, s * 0.34, T.TEXT_3)

        # 左上角播放量角标
        if self._badge:
            bar_h = 22
            width = self._badge_width() + 34
            icons.rounded_rect(self, 8, 8, 8 + width, 8 + bar_h, bar_h / 2,
                               fill=T.mix(self._bg, "#000000", 0.55),
                               outline="")
            icons.draw_icon(self, "play", 20, 8 + bar_h / 2, 10, "#ffffff")
            self.create_text(31, 8 + bar_h / 2, text=self._badge,
                             fill="#ffffff", font=T.Fonts(self).tiny,
                             anchor="w")

        if self._hover and self._on_open is not None:
            icons.rounded_rect(self, 0, 0, s - 1, s - 1, self._radius,
                               fill="", outline=T.ACCENT, width=2)

    def _badge_width(self):
        try:
            import tkinter.font as tkfont
            return tkfont.Font(font=T.Fonts(self).tiny).measure(self._badge)
        except Exception:
            return len(self._badge) * 7

    def bind_hover(self, on_enter=None, on_leave=None):
        def enter(_e=None):
            self._hover = True
            self._redraw()
            if on_enter:
                on_enter()

        def leave(_e=None):
            self._hover = False
            self._redraw()
            if on_leave:
                on_leave()

        self.bind("<Enter>", enter)
        self.bind("<Leave>", leave)

    def refresh(self):
        """真实封面下好之后调用，重新取图"""
        if self._cache is not None:
            self._cache.invalidate(self._url)
        self._redraw()

    def set_source(self, url, seed=""):
        self._url = url or ""
        if seed:
            self._seed = seed
        self._redraw()


class BigCard(tk.Frame):
    """首页卡片：大封面 + 标题（+ 副标题），可点击"""

    def __init__(self, master, title, subtitle="", url="", seed="",
                 badge="", size=150, command=None, cache=None, bg=None,
                 tag=None, badge_color=None):
        self._bg = bg or T.PANEL
        super().__init__(master, bg=self._bg)
        self.command = command

        self.art = CoverArt(self, size=size, url=url, seed=seed or title,
                            cache=cache, badge=badge)
        self.art.pack()

        self.title_label = tk.Label(
            self, text=title, bg=self._bg, fg=T.TEXT, font=T.Fonts(self).small,
            wraplength=size, justify=tk.LEFT, anchor="w")
        self.title_label.pack(fill=tk.X, pady=(7, 0))

        self.sub_label = None
        if subtitle:
            self.sub_label = tk.Label(
                self, text=subtitle, bg=self._bg, fg=T.TEXT_3,
                font=T.Fonts(self).tiny, wraplength=size, justify=tk.LEFT,
                anchor="w")
            self.sub_label.pack(fill=tk.X, pady=(1, 0))

        self.tag = None
        if tag:
            self.tag = tk.Label(self, text=tag, bg=self._bg,
                                fg=badge_color or T.ACCENT_TEXT,
                                font=T.Fonts(self).tiny, anchor="w")
            self.tag.pack(fill=tk.X, pady=(2, 0))

        for widget in (self, self.art, self.title_label) + \
                ((self.sub_label,) if self.sub_label else ()):
            widget.bind("<Button-1>", self._clicked, add="+")
            widget.bind("<Enter>", self._enter, add="+")
            widget.bind("<Leave>", self._leave, add="+")
        self.art.bind_hover(on_enter=self._enter, on_leave=self._leave)
        self.configure(cursor="hand2")

    def _clicked(self, _e=None):
        if self.command:
            try:
                self.command()
            except Exception as exc:
                print("[卡片] 点击回调异常:", exc)

    def _enter(self, _e=None):
        try:
            self.title_label.configure(fg=T.ACCENT_TEXT)
        except Exception:
            pass

    def _leave(self, _e=None):
        try:
            self.title_label.configure(fg=T.TEXT)
        except Exception:
            pass


class CardRow(tk.Frame):
    """横向一排卡片（超出宽度可横向滚动）"""

    def __init__(self, master, bg=None, height=232, gap=16):
        self._bg = bg or T.BG
        super().__init__(master, bg=self._bg)
        self._gap = gap
        self._height = height
        self.cards = []

        self.canvas = tk.Canvas(self, bg=self._bg, height=height,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.X)
        self.inner = tk.Frame(self.canvas, bg=self._bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)

    def _on_inner(self, _e=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, height=event.height)

    def _on_wheel(self, event):
        delta = -1 * (event.delta // 120) if abs(event.delta) >= 120 else \
            (-1 if event.delta > 0 else 1)
        try:
            self.canvas.xview_scroll(delta, "units")
        except Exception:
            pass

    def add(self, card):
        card.pack(in_=self.inner, side=tk.LEFT, padx=(0, self._gap))
        self.cards.append(card)
        card.bind("<MouseWheel>", self._on_wheel, add="+")
        return card

    def clear(self):
        for card in self.cards:
            card.destroy()
        self.cards = []


def make_badge_count(value) -> str:
    """播放量：1.2万 / 4529 / 26.5万，模仿网易云的写法"""
    try:
        number = int(value)
    except Exception:
        return str(value or "")
    if number >= 100000000:
        return f"{number / 100000000:.1f}亿"
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return str(number)
