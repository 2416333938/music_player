"""现代深色设计系统 —— 配色、字体、ttk 主题

界面视觉规范集中在这里，改这一个文件即可整体换肤。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ============================================================
# 配色（深色 · 靛蓝强调色）
# ============================================================
BG            = "#0E0F15"   # 窗口底色
SIDEBAR       = "#141620"   # 侧边栏
SIDEBAR_HOVER = "#1D2030"
PANEL         = "#171A24"   # 卡片 / 面板
PANEL_ALT     = "#1B1F2B"
ELEVATED      = "#222636"   # 悬浮 / 输入框
PLAYBAR       = "#12141C"   # 底部播放条
BORDER        = "#252A38"
BORDER_SOFT   = "#1E2230"
HOVER         = "#1E2331"
SELECTED      = "#252C42"
ROW_ALT       = "#161924"

TEXT          = "#ECEFF7"   # 主文字
TEXT_2        = "#9CA3B8"   # 次级文字
TEXT_3        = "#666E85"   # 弱化文字
TEXT_ON_ACCENT = "#FFFFFF"

ACCENT        = "#6C5CE7"   # 主色（靛蓝）
ACCENT_HOVER  = "#7E70F0"
ACCENT_ACTIVE = "#5A4BD1"
ACCENT_SOFT   = "#2A2745"   # 主色的暗色底
ACCENT_TEXT   = "#A79BFF"   # 暗底上的主色文字

CYAN          = "#22D3EE"
GREEN         = "#34D399"
AMBER         = "#FBBF24"
ROSE          = "#FB7185"
RED           = "#EF4444"
BILI_PINK     = "#FB7299"

# 平台标识色
PLATFORM_COLORS = {
    "netease":  "#E64A4A",
    "qqmusic":  "#31C27C",
    "kugou":    "#2CA2F0",
    "qishui":   "#FF6A3D",
    "bilibili": BILI_PINK,
}
PLATFORM_NAMES = {
    "netease":  "网易云",
    "qqmusic":  "QQ音乐",
    "kugou":    "酷狗",
    "qishui":   "汽水音乐",
    "bilibili": "B站",
}
PLATFORM_KEYS = list(PLATFORM_NAMES.keys())


def platform_name(key: str) -> str:
    return PLATFORM_NAMES.get(key, key)


def platform_color(key: str) -> str:
    return PLATFORM_COLORS.get(key, TEXT_2)


# ============================================================
# 字体
# ============================================================
FONT_UI = "Microsoft YaHei UI"
FONT_LATIN = "Segoe UI"
FONT_MONO = "Consolas"

_FALLBACK_UI = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimHei")
_FALLBACK_LATIN = ("Segoe UI", "Microsoft YaHei UI", "Arial")


def pick_font(root: tk.Misc, candidates) -> str:
    """从候选字体里挑第一个系统可用的"""
    try:
        available = set(tkfont.families(root))
    except Exception:
        return candidates[0]
    for name in candidates:
        if name in available:
            return name
    return candidates[0]


class Fonts:
    """惰性创建的字体集合（必须在 Tk 根窗口建立之后实例化）"""

    def __init__(self, root: tk.Misc):
        ui = pick_font(root, _FALLBACK_UI)
        latin = pick_font(root, _FALLBACK_LATIN)

        self.h1 = (ui, 20, "bold")
        self.h2 = (ui, 16, "bold")
        self.h3 = (ui, 13, "bold")
        self.body = (ui, 11)
        self.body_bold = (ui, 11, "bold")
        self.small = (ui, 10)
        self.small_bold = (ui, 10, "bold")
        self.tiny = (ui, 9)
        self.brand = (latin, 17, "bold")
        self.counter = (latin, 19, "bold")
        self.icon_sm = (latin, 10)
        self.icon = (latin, 12)
        self.icon_lg = (latin, 15)


# ============================================================
# 尺寸
# ============================================================
SIDEBAR_W = 218
PLAYBAR_H = 92
RADIUS = 10
RADIUS_SM = 7
PAD = 14

TRACK_COLUMNS = (
    # (列 id, 标题, 宽度, 最小宽度, 对齐, 是否可拉伸, 权重)
    ("idx",      "#",         46,  46,  "center", False),
    ("title",    "标题",      330, 180, "w",      True),
    ("artist",   "歌手 / UP主", 200, 120, "w",     True),
    ("album",    "专辑 / BV号", 220, 120, "w",     True),
    ("platform", "平台",       84,  84,  "center", False),
    ("duration", "时长",       62,  62,  "center", False),
)


# ============================================================
# ttk 主题
# ============================================================
def apply_ttk_theme(root: tk.Misc):
    """把 ttk 控件（Treeview / Scrollbar / Entry / Combobox …）刷成深色现代风"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    fonts = Fonts(root)

    # ---- 全局 ----
    style.configure(".", background=BG, foreground=TEXT,
                    fieldbackground=ELEVATED, borderwidth=0,
                    focuscolor=ACCENT, font=fonts.body)

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Playbar.TFrame", background=PLAYBAR)
    style.configure("TLabel", background=BG, foreground=TEXT, font=fonts.body)
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_2,
                    font=fonts.small)
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=TEXT_2,
                    font=fonts.small)
    style.configure("SidebarMuted.TLabel", background=SIDEBAR, foreground=TEXT_3,
                    font=fonts.tiny)
    style.configure("H1.TLabel", background=BG, foreground=TEXT, font=fonts.h1)
    style.configure("H2.TLabel", background=BG, foreground=TEXT, font=fonts.h2)
    style.configure("H3.TLabel", background=BG, foreground=TEXT, font=fonts.h3)
    style.configure("PanelH3.TLabel", background=PANEL, foreground=TEXT,
                    font=fonts.h3)
    style.configure("Accent.TLabel", background=BG, foreground=ACCENT_TEXT,
                    font=fonts.body_bold)

    # ---- 分隔线 ----
    style.configure("TSeparator", background=BORDER)
    style.configure("Soft.TSeparator", background=BORDER_SOFT)

    # ---- 滚动条 ----
    style.configure(
        "Modern.Vertical.TScrollbar",
        background=ELEVATED, troughcolor=BG, bordercolor=BG,
        arrowcolor=TEXT_3, darkcolor=ELEVATED, lightcolor=ELEVATED,
        relief="flat", arrowsize=12, width=10,
    )
    style.map(
        "Modern.Vertical.TScrollbar",
        background=[("active", ACCENT), ("pressed", ACCENT_ACTIVE)],
    )
    style.configure(
        "Modern.Horizontal.TScrollbar",
        background=ELEVATED, troughcolor=BG, bordercolor=BG,
        arrowcolor=TEXT_3, darkcolor=ELEVATED, lightcolor=ELEVATED,
        relief="flat", arrowsize=12,
    )

    # ---- 输入框 ----
    style.configure(
        "Modern.TEntry",
        fieldbackground=ELEVATED, background=ELEVATED, foreground=TEXT,
        insertcolor=ACCENT, bordercolor=BORDER, lightcolor=BORDER,
        darkcolor=ELEVATED, borderwidth=1, relief="flat", padding=8,
    )
    style.map(
        "Modern.TEntry",
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        fieldbackground=[("disabled", PANEL)],
    )

    # ---- 下拉框 ----
    style.configure(
        "Modern.TCombobox",
        fieldbackground=ELEVATED, background=ELEVATED, foreground=TEXT,
        arrowcolor=TEXT_2, bordercolor=BORDER, lightcolor=ELEVATED,
        darkcolor=ELEVATED, borderwidth=1, relief="flat", padding=6,
    )
    style.map(
        "Modern.TCombobox",
        fieldbackground=[("readonly", ELEVATED), ("disabled", PANEL)],
        background=[("readonly", ELEVATED)],
        foreground=[("readonly", TEXT)],
        arrowcolor=[("active", ACCENT)],
        bordercolor=[("focus", ACCENT)],
    )

    # ---- 按钮 ----
    style.configure(
        "Modern.TButton",
        background=ELEVATED, foreground=TEXT, borderwidth=0,
        focusthickness=0, relief="flat", padding=(12, 7), font=fonts.body,
    )
    style.map(
        "Modern.TButton",
        background=[("pressed", ACCENT_ACTIVE), ("active", HOVER),
                    ("disabled", PANEL)],
        foreground=[("disabled", TEXT_3)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT, foreground=TEXT_ON_ACCENT, borderwidth=0,
        focusthickness=0, relief="flat", padding=(14, 7), font=fonts.body_bold,
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", ACCENT_ACTIVE), ("active", ACCENT_HOVER),
                    ("disabled", ACCENT_SOFT)],
        foreground=[("disabled", TEXT_3)],
    )
    style.configure(
        "Ghost.TButton",
        background=PANEL, foreground=TEXT_2, borderwidth=0,
        focusthickness=0, relief="flat", padding=(12, 7), font=fonts.body,
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", ACCENT_SOFT), ("active", HOVER)],
        foreground=[("active", TEXT)],
    )

    # ---- 复选框 ----
    style.configure(
        "Modern.TCheckbutton",
        background=PANEL, foreground=TEXT, focuscolor=PANEL,
        font=fonts.small, padding=3,
    )
    style.map(
        "Modern.TCheckbutton",
        background=[("active", PANEL)],
        foreground=[("disabled", TEXT_3)],
        indicatorcolor=[("selected", ACCENT), ("!selected", ELEVATED)],
    )

    # ---- 进度条 ----
    style.configure(
        "Modern.Horizontal.TProgressbar",
        troughcolor=ELEVATED, background=ACCENT, bordercolor=ELEVATED,
        lightcolor=ACCENT, darkcolor=ACCENT, thickness=6,
    )

    # ---- 曲目表 ----
    style.configure(
        "Tracks.Treeview",
        background=PANEL, fieldbackground=PANEL, foreground=TEXT,
        rowheight=42, borderwidth=0, relief="flat", font=fonts.body,
    )
    style.map(
        "Tracks.Treeview",
        background=[("selected", SELECTED)],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "Tracks.Treeview.Heading",
        background=PANEL, foreground=TEXT_3, relief="flat", borderwidth=0,
        font=fonts.small, padding=(8, 10),
    )
    style.map(
        "Tracks.Treeview.Heading",
        background=[("active", HOVER)],
        foreground=[("active", TEXT_2)],
    )
    # 去掉 Treeview 的虚线焦点框
    try:
        style.layout("Tracks.Treeview", [
            ("Treeview.treearea", {"sticky": "nswe"}),
        ])
    except Exception:
        pass

    # ---- 选项卡（登录对话框仍在用）----
    style.configure(
        "TNotebook", background=BG, borderwidth=0, tabmargins=(2, 6, 2, 0),
    )
    style.configure(
        "TNotebook.Tab", background=PANEL, foreground=TEXT_2,
        padding=(18, 9), borderwidth=0, font=fonts.body,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", ELEVATED), ("active", HOVER)],
        foreground=[("selected", TEXT)],
    )
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    borderwidth=1, relief="solid")
    style.configure("TLabelframe.Label", background=BG, foreground=TEXT_2,
                    font=fonts.small_bold)

    return style


# ============================================================
# 小工具：颜色运算
# ============================================================
def _clamp(v: int) -> int:
    return 0 if v < 0 else (255 if v > 255 else int(v))


def hex_to_rgb(color: str):
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(_clamp(c) for c in rgb)


def mix(c1: str, c2: str, t: float) -> str:
    """按比例混合两种颜色，t=0 返回 c1，t=1 返回 c2"""
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def lighten(color: str, amount: float = 0.12) -> str:
    return mix(color, "#ffffff", amount)


def darken(color: str, amount: float = 0.12) -> str:
    return mix(color, "#000000", amount)


def with_alpha_over(color: str, bg: str, alpha: float) -> str:
    """把半透明色叠加到不透明底色上，得到模拟透明效果的颜色"""
    return mix(bg, color, alpha)


# ============================================================
# 文字排版小工具
# ============================================================
def ellipsize(text: str, font: tkfont.Font, max_px: int) -> str:
    """按像素宽度截断文字并加省略号"""
    text = text or ""
    if max_px <= 0 or font.measure(text) <= max_px:
        return text
    ell = "…"
    ell_w = font.measure(ell)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid]) + ell_w <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def format_time(seconds) -> str:
    """秒 → mm:ss / h:mm:ss"""
    try:
        total = int(seconds or 0)
    except Exception:
        return "--:--"
    if total <= 0:
        return "--:--"
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
