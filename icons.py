"""矢量图标 —— 全部用 Canvas 图元绘制，不依赖任何图标字体

这样在 Windows 上渲染稳定，且可以随主题任意换色。
每个 draw_icon() 都会把图元绑定到统一的 tag，方便整体重绘或删除。
"""
from __future__ import annotations

import tkinter as tk

_SMOOTH = 0.55  # 圆角/曲线平滑度


# ============================================================
# 基础图元
# ============================================================
def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """平滑圆角矩形（用平滑多边形近似，visual 上足够圆润）"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r, x2, y2 - r,
        x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1,
    ]
    kw.setdefault("smooth", True)
    kw.setdefault("splinesteps", 24)
    return canvas.create_polygon(pts, **kw)


def circle(canvas, cx, cy, r, **kw):
    return canvas.create_oval(cx - r, cy - r, cx + r, cy + r, **kw)


# ============================================================
# 图标绘制
# ============================================================
def _bbox(x, y, size):
    """返回以 (x,y) 为中心、边长 size 的正方形四边"""
    half = size / 2.0
    return x - half, y - half, x + half, y + half


def _line(canvas, pts, color, width, cap="round", tag=None, smooth=False):
    kw = dict(fill=color, width=width, capstyle=cap, joinstyle="round")
    if smooth:
        kw["smooth"] = True
        kw["splinesteps"] = 20
    if tag:
        kw["tags"] = tag
    return canvas.create_line(*pts, **kw)


def _flat(items):
    """把 (x1, y1, (x2, y2), [x3, y3]) 之类的写法统一成扁平坐标列表"""
    flat = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flat.extend(_flat(item))
        else:
            flat.append(item)
    return flat


def _method_name(fn) -> str:
    """取出 tkinter 控件方法 / 模块级绘制函数的名字

    注意：cv.create_line 是绑定方法，tk.Canvas.create_line 是普通函数，
    两者既不 == 也不 is，只能按名字判断。
    """
    return getattr(fn, "__name__", "") or ""


def _is_poly_or_line(fn) -> bool:
    return _method_name(fn) in ("create_line", "create_polygon")


def _is_arc(fn) -> bool:
    return _method_name(fn) == "create_arc"


def _is_helper(fn) -> bool:
    """rounded_rect / circle 是本模块的普通函数，需要显式传 canvas"""
    return _method_name(fn) in ("rounded_rect", "circle")


def draw_icon(canvas, name, x, y, size=16, color="#ffffff", width=None, tag=None):
    """在 (x, y) 处画一个 size×size 的图标，返回创建的图元 id 列表"""
    weight = width or max(1.6, size / 8.5)
    x1, y1, x2, y2 = _bbox(x, y, size)
    w, h = x2 - x1, y2 - y1
    ids = []

    def add(fn, *a, **kw):
        if tag:
            kw.setdefault("tags", tag)
        if a and _is_poly_or_line(fn):
            seq = a[0]
            if isinstance(seq, (list, tuple)):
                a = (tuple(_flat(seq)),) + tuple(a[1:])
            else:
                a = tuple(_flat(a))
        elif _is_arc(fn) and len(a) == 4:
            # create_arc 要的是 (x1, y1, x2, y2) 元组而不是 4 个位置参数
            a = ((a[0], a[1], a[2], a[3]),)
        if _is_helper(fn):
            # rounded_rect / circle 是本模块普通函数，canvas 要显式传
            item = fn(canvas, *a, **kw)
        else:
            # 绑定方法已经把 canvas 带在里面了，不能再传一次
            item = fn(*a, **kw)
        ids.append(item)
        return item

    # -------------------------------------------------- 播放 / 暂停 / 停止
    if name == "play":
        pad = w * 0.2
        add(canvas.create_polygon,
            x1 + pad, y1 + h * 0.10,
            x2 - pad * 0.6, y1 + h * 0.50,
            x1 + pad, y2 - h * 0.10,
            fill=color, outline=color, width=max(1.0, weight * 0.7),
            joinstyle="round")

    elif name == "pause":
        bw = w * 0.26
        gap = w * 0.16
        add(rounded_rect, x1 + w * 0.20, y1 + h * 0.14,
            x1 + w * 0.20 + bw, y2 - h * 0.14, bw * 0.34,
            fill=color, outline=color)
        add(rounded_rect, x2 - w * 0.20 - bw, y1 + h * 0.14,
            x2 - w * 0.20, y2 - h * 0.14, bw * 0.34,
            fill=color, outline=color)

    elif name == "stop":
        add(rounded_rect, x1 + w * 0.20, y1 + h * 0.20,
            x2 - w * 0.20, y2 - h * 0.20, w * 0.14,
            fill=color, outline=color)

    # -------------------------------------------------- 上一首 / 下一首
    elif name == "next":
        bar = max(1.6, w * 0.11)
        add(canvas.create_polygon,
            x1 + w * 0.12, y1 + h * 0.16,
            x1 + w * 0.60, y1 + h * 0.50,
            x1 + w * 0.12, y2 - h * 0.16,
            fill=color, outline=color, width=1, joinstyle="round")
        add(rounded_rect, x2 - w * 0.18 - bar, y1 + h * 0.16,
            x2 - w * 0.18, y2 - h * 0.16, bar * 0.4,
            fill=color, outline=color)

    elif name == "prev":
        bar = max(1.6, w * 0.11)
        add(canvas.create_polygon,
            x2 - w * 0.12, y1 + h * 0.16,
            x2 - w * 0.60, y1 + h * 0.50,
            x2 - w * 0.12, y2 - h * 0.16,
            fill=color, outline=color, width=1, joinstyle="round")
        add(rounded_rect, x1 + w * 0.18, y1 + h * 0.16,
            x1 + w * 0.18 + bar, y2 - h * 0.16, bar * 0.4,
            fill=color, outline=color)

    # -------------------------------------------------- 顺序播放
    elif name == "sequential":
        pts = [
            x1 + w * 0.10, y2 - h * 0.30,
            x2 - w * 0.28, y2 - h * 0.30,
            x2 - w * 0.28, y1 + h * 0.30,
            x2 - w * 0.30, y1 + h * 0.30,
        ]
        add(canvas.create_line, *pts, fill=color, width=weight,
            capstyle="round", joinstyle="round", smooth=True)
        # 右上箭头
        add(canvas.create_polygon,
            x2 - w * 0.42, y1 + h * 0.10,
            x2 - w * 0.02, y1 + h * 0.30,
            x2 - w * 0.42, y1 + h * 0.50,
            fill=color, outline=color, width=1, joinstyle="round")

    # -------------------------------------------------- 随机播放
    elif name == "shuffle":
        # 上：左→右曲线 + 箭头
        add(canvas.create_line,
            x1 + w * 0.06, y1 + h * 0.26,
            x1 + w * 0.40, y1 + h * 0.26,
            x2 - w * 0.40, y2 - h * 0.26,
            x2 - w * 0.18, y2 - h * 0.26,
            fill=color, width=weight, capstyle="round",
            joinstyle="round", smooth=True, splinesteps=20)
        # 下：左→右曲线 + 箭头
        add(canvas.create_line,
            x1 + w * 0.06, y2 - h * 0.26,
            x1 + w * 0.40, y2 - h * 0.26,
            x2 - w * 0.40, y1 + h * 0.26,
            x2 - w * 0.18, y1 + h * 0.26,
            fill=color, width=weight, capstyle="round",
            joinstyle="round", smooth=True, splinesteps=20)
        tw = w * 0.34
        add(canvas.create_polygon,
            x2 - tw, y1 + h * 0.06,
            x2 - w * 0.02, y1 + h * 0.26,
            x2 - tw, y1 + h * 0.46,
            fill=color, outline=color, width=1, joinstyle="round")
        add(canvas.create_polygon,
            x2 - tw, y2 - h * 0.06,
            x2 - w * 0.02, y2 - h * 0.26,
            x2 - tw, y2 - h * 0.46,
            fill=color, outline=color, width=1, joinstyle="round")

    # -------------------------------------------------- 单曲循环
    elif name == "repeat_one":
        r = w * 0.34
        add(canvas.create_arc,
            x1 + w * 0.16, y1 + h * 0.16, x2 - w * 0.16, y2 - h * 0.16,
            start=40, extent=280, style="arc",
            outline=color, width=weight)
        add(canvas.create_polygon,
            x2 - w * 0.34, y1 + h * 0.04,
            x2 - w * 0.06, y1 + h * 0.22,
            x2 - w * 0.34, y1 + h * 0.40,
            fill=color, outline=color, width=1, joinstyle="round")
        add(canvas.create_text,
            (x1 + x2) / 2, (y1 + y2) / 2 + h * 0.02,
            text="1", fill=color,
            font=("Segoe UI", max(7, int(size * 0.52)), "bold"))

    # -------------------------------------------------- 音量
    elif name == "volume":
        add(canvas.create_polygon,
            x1 + w * 0.06, y1 + h * 0.36,
            x1 + w * 0.26, y1 + h * 0.36,
            x1 + w * 0.50, y1 + h * 0.12,
            x1 + w * 0.50, y2 - h * 0.12,
            x1 + w * 0.26, y2 - h * 0.36,
            x1 + w * 0.06, y2 - h * 0.36,
            fill=color, outline=color, width=1, joinstyle="round")
        add(canvas.create_arc,
            x1 + w * 0.34, y1 + h * 0.26, x2 + w * 0.16, y2 - h * 0.26,
            start=-58, extent=116, style="arc",
            outline=color, width=max(1.2, weight * 0.8))
        add(canvas.create_arc,
            x1 + w * 0.48, y1 + h * 0.10, x2 + w * 0.34, y2 - h * 0.10,
            start=-52, extent=104, style="arc",
            outline=color, width=max(1.2, weight * 0.8))

    elif name == "volume_mute":
        add(canvas.create_polygon,
            x1 + w * 0.06, y1 + h * 0.36,
            x1 + w * 0.26, y1 + h * 0.36,
            x1 + w * 0.50, y1 + h * 0.12,
            x1 + w * 0.50, y2 - h * 0.12,
            x1 + w * 0.26, y2 - h * 0.36,
            x1 + w * 0.06, y2 - h * 0.36,
            fill=color, outline=color, width=1, joinstyle="round")
        add(canvas.create_line,
            x1 + w * 0.62, y1 + h * 0.32, x2, y2 - h * 0.32,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x2, y1 + h * 0.32, x1 + w * 0.62, y2 - h * 0.32,
            fill=color, width=weight, capstyle="round")

    # -------------------------------------------------- 通用符号
    elif name == "plus":
        add(canvas.create_line,
            (x1 + x2) / 2, y1 + h * 0.18, (x1 + x2) / 2, y2 - h * 0.18,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x1 + w * 0.18, (y1 + y2) / 2, x2 - w * 0.18, (y1 + y2) / 2,
            fill=color, width=weight, capstyle="round")

    elif name == "minus":
        add(canvas.create_line,
            x1 + w * 0.18, (y1 + y2) / 2, x2 - w * 0.18, (y1 + y2) / 2,
            fill=color, width=weight, capstyle="round")

    elif name == "close":
        add(canvas.create_line, x1 + w * 0.22, y1 + h * 0.22,
            x2 - w * 0.22, y2 - h * 0.22, fill=color, width=weight,
            capstyle="round")
        add(canvas.create_line, x2 - w * 0.22, y1 + h * 0.22,
            x1 + w * 0.22, y2 - h * 0.22, fill=color, width=weight,
            capstyle="round")

    elif name == "check":
        add(canvas.create_line,
            x1 + w * 0.14, y1 + h * 0.54,
            x1 + w * 0.38, y2 - h * 0.20,
            x2 - w * 0.12, y1 + h * 0.20,
            fill=color, width=weight, capstyle="round", joinstyle="round")

    elif name == "search":
        r = w * 0.30
        add(circle, x1 + w * 0.42, y1 + h * 0.42, r,
            outline=color, width=weight, fill="")
        add(canvas.create_line,
            x1 + w * 0.64, y1 + h * 0.64, x2 - w * 0.08, y2 - h * 0.08,
            fill=color, width=weight, capstyle="round")

    elif name == "download":
        add(canvas.create_line,
            (x1 + x2) / 2, y1 + h * 0.10, (x1 + x2) / 2, y2 - h * 0.36,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_polygon,
            (x1 + x2) / 2 - w * 0.22, y2 - h * 0.46,
            (x1 + x2) / 2 + w * 0.22, y2 - h * 0.46,
            (x1 + x2) / 2, y2 - h * 0.10,
            fill=color, outline=color, width=1, joinstyle="round")
        add(canvas.create_line,
            x1 + w * 0.14, y2 - h * 0.04, x2 - w * 0.14, y2 - h * 0.04,
            fill=color, width=weight, capstyle="round")

    elif name == "trash":
        add(canvas.create_line,
            x1 + w * 0.10, y1 + h * 0.22, x2 - w * 0.10, y1 + h * 0.22,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x1 + w * 0.36, y1 + h * 0.10, x1 + w * 0.64, y1 + h * 0.10,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x1 + w * 0.20, y1 + h * 0.24,
            x1 + w * 0.26, y2 - h * 0.10,
            x2 - w * 0.26, y2 - h * 0.10,
            x2 - w * 0.20, y1 + h * 0.24,
            fill=color, width=weight, capstyle="round", joinstyle="round")
        add(canvas.create_line,
            x1 + w * 0.42, y1 + h * 0.40, x1 + w * 0.42, y2 - h * 0.24,
            fill=color, width=max(1.1, weight * 0.7), capstyle="round")
        add(canvas.create_line,
            x2 - w * 0.42, y1 + h * 0.40, x2 - w * 0.42, y2 - h * 0.24,
            fill=color, width=max(1.1, weight * 0.7), capstyle="round")

    elif name == "music":
        add(canvas.create_line,
            x1 + w * 0.36, y1 + h * 0.70, x1 + w * 0.36, y1 + h * 0.24,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x2 - w * 0.30, y1 + h * 0.78, x2 - w * 0.30, y1 + h * 0.14,
            fill=color, width=weight, capstyle="round")
        add(canvas.create_line,
            x1 + w * 0.44, y1 + h * 0.14, x2 - w * 0.22, y1 + h * 0.04,
            fill=color, width=weight * 1.6, capstyle="butt")
        add(circle, x1 + w * 0.24, y1 + h * 0.76, w * 0.15,
            fill=color, outline=color)
        add(circle, x2 - w * 0.42, y1 + h * 0.84, w * 0.15,
            fill=color, outline=color)

    elif name == "list":
        for i, ty in enumerate((0.24, 0.50, 0.76)):
            add(circle, x1 + w * 0.18, y1 + h * ty, max(1.3, w * 0.07),
                fill=color, outline=color)
            add(canvas.create_line,
                x1 + w * 0.38, y1 + h * ty, x2 - w * 0.10, y1 + h * ty,
                fill=color, width=weight * 0.85, capstyle="round")

    elif name == "folder":
        add(rounded_rect, x1 + w * 0.06, y1 + h * 0.22,
            x2 - w * 0.06, y2 - h * 0.14, w * 0.10,
            fill="", outline=color, width=weight)
        add(canvas.create_line,
            x1 + w * 0.06, y1 + h * 0.42, x2 - w * 0.06, y1 + h * 0.42,
            fill=color, width=max(1.1, weight * 0.8), capstyle="round")

    elif name == "gear":
        cx, cy, r = (x1 + x2) / 2, (y1 + y2) / 2, w * 0.36
        import math
        # 8 个短齿：太长会变成太阳，这里控制在 0.92r~1.28r
        for i in range(8):
            a = math.radians(i * 45)
            add(canvas.create_line,
                cx + math.cos(a) * r * 0.86, cy + math.sin(a) * r * 0.86,
                cx + math.cos(a) * r * 1.26, cy + math.sin(a) * r * 1.26,
                fill=color, width=max(1.8, weight * 1.05), capstyle="round")
        add(circle, cx, cy, r, outline=color, width=weight, fill="")
        add(circle, cx, cy, r * 0.32, outline=color,
            width=max(1.2, weight * 0.8), fill="")

    elif name == "more":
        for tx in (0.24, 0.50, 0.76):
            add(circle, x1 + w * tx, (y1 + y2) / 2, max(1.4, w * 0.075),
                fill=color, outline=color)

    elif name == "refresh":
        add(canvas.create_arc,
            x1 + w * 0.16, y1 + h * 0.16, x2 - w * 0.16, y2 - h * 0.16,
            start=110, extent=290, style="arc",
            outline=color, width=weight)
        add(canvas.create_polygon,
            x2 - w * 0.42, y1 + h * 0.06,
            x2 - w * 0.06, y1 + h * 0.16,
            x2 - w * 0.30, y1 + h * 0.48,
            fill=color, outline=color, width=1, joinstyle="round")

    elif name == "chevron_right":
        add(canvas.create_line,
            x1 + w * 0.36, y1 + h * 0.16,
            x2 - w * 0.30, (y1 + y2) / 2,
            x1 + w * 0.36, y2 - h * 0.16,
            fill=color, width=weight, capstyle="round", joinstyle="round")

    elif name == "warning":
        add(canvas.create_polygon,
            (x1 + x2) / 2, y1 + h * 0.10,
            x2 - w * 0.04, y2 - h * 0.14,
            x1 + w * 0.04, y2 - h * 0.14,
            fill="", outline=color, width=weight * 0.9, joinstyle="round")
        add(canvas.create_line,
            (x1 + x2) / 2, y1 + h * 0.38,
            (x1 + x2) / 2, y1 + h * 0.64,
            fill=color, width=weight * 0.9, capstyle="round")
        add(circle, (x1 + x2) / 2, y1 + h * 0.78, max(1.2, w * 0.055),
            fill=color, outline=color)

    elif name == "info":
        add(circle, (x1 + x2) / 2, (y1 + y2) / 2, w * 0.44,
            outline=color, width=weight, fill="")
        add(circle, (x1 + x2) / 2, y1 + h * 0.30, max(1.2, w * 0.06),
            fill=color, outline=color)
        add(canvas.create_line,
            (x1 + x2) / 2, y1 + h * 0.46,
            (x1 + x2) / 2, y2 - h * 0.24,
            fill=color, width=weight, capstyle="round")

    return ids
