"""多平台音乐播放器 —— 现代深色界面

界面结构：
┌──────────┬──────────────────────────────────────────────┐
│ 侧边栏   │ 顶部：标题 + 工具条（搜索 / 平台 / 批量操作）│
│ 搜索     ├──────────────────────────────────────────────┤
│ 全部音乐 │                                              │
│ 我的歌单 │ 曲目列表（多选 / 右键菜单 / 拖拽加入歌单）   │
│ 下载管理 │                                              │
│ 账号登录 │                                              │
├──────────┴──────────────────────────────────────────────┤
│ 播放条：封面 · 曲名 · 播放控制 · 进度 · 音量 · 播放模式 │
└─────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox

def _base_dir() -> str:
    """源码运行取脚本目录，PyInstaller 打包后取解包目录"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import accounts as A                                     # noqa: E402
import cards as CARD                                     # noqa: E402
import cover as COVER                                    # noqa: E402
import feed as FEED                                      # noqa: E402
import icons                                            # noqa: E402
import theme as T                                       # noqa: E402
import tray                                             # noqa: E402
import updater                                          # noqa: E402
import widgets as W                                     # noqa: E402
from config import load_config, save_config             # noqa: E402
from config import config_path as _config_path          # noqa: E402
from downloader import (DownloadManager, default_download_dir,  # noqa: E402
                        STATUS_DONE, STATUS_FAILED, STATUS_RUNNING,
                        STATUS_WAITING, STATUS_TEXT)
from play_queue import (MODE_META, MODE_SHUFFLE, PlayQueue,  # noqa: E402
                        mode_from_config)
from player import MusicPlayer, find_ffmpeg, CACHE_DIR  # noqa: E402

CONFIG_PATH = _config_path()

APP_TITLE = "多平台音乐播放器"
APP_VERSION = "2.1"

VIEW_HOME = "home"
VIEW_SEARCH = "search"
VIEW_LIBRARY = "library"
VIEW_PLAYLIST = "playlist"
VIEW_DOWNLOAD = "download"
VIEW_ACCOUNTS = "accounts"
VIEW_LOCAL = "local"
VIEW_LOGIN = "login"

QUICK_KEYWORDS = ["热门推荐", "华语流行", "轻音乐", "纯音乐", "摇滚", "B站音乐"]


# ============================================================
# 小工具
# ============================================================
def human_size(num_bytes) -> str:
    try:
        value = float(num_bytes or 0)
    except Exception:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def human_speed(bytes_per_sec) -> str:
    return human_size(bytes_per_sec) + "/s"


class Marquee:
    """跑马灯：标题过长时来回滚动"""

    def __init__(self, label: tk.Label, max_px=320, interval=60):
        self.label = label
        self.max_px = max_px
        self.interval = interval
        self._text = ""
        self._offset = 0
        self._after = None
        self._direction = 1
        self._font = None
        self._need = False

    def set_text(self, text):
        self._text = text or ""
        self._offset = 0
        self._direction = 1
        self._measure()
        if self._after:
            try:
                self.label.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        if self._need:
            self.label.configure(text=self._text[self._offset:] + "   " +
                                      self._text[:self._offset])
            self._schedule()
        else:
            self.label.configure(text=self._text)

    def _measure(self):
        try:
            import tkinter.font as tkfont
            font = tkfont.Font(font=self.label.cget("font"))
            self._need = font.measure(self._text) > self.max_px
        except Exception:
            self._need = len(self._text) > 34

    def _schedule(self):
        try:
            self._after = self.label.after(self.interval, self._tick)
        except Exception:
            self._after = None

    def _tick(self):
        if not self._need or not self._text:
            return
        self._offset += self._direction
        limit = max(1, len(self._text) - 6)
        if self._offset >= limit:
            self._offset = limit
            self._direction = -1
            self.label.after(900, self._resume)
            return
        if self._offset <= 0:
            self._offset = 0
            self._direction = 1
            self.label.after(900, self._resume)
            return
        self._render()
        self._schedule()

    def _resume(self):
        self._direction = 1 if self._offset <= 0 else -1
        self._schedule()

    def _render(self):
        text = self._text
        try:
            self.label.configure(text=text[self._offset:] + "   " +
                                      text[:self._offset])
        except Exception:
            pass

    def stop(self):
        if self._after:
            try:
                self.label.after_cancel(self._after)
            except Exception:
                pass
            self._after = None


# ============================================================
# 侧边栏歌单行
# ============================================================
class PlaylistRow(tk.Canvas):
    """侧边栏里的一行歌单：图标 + 名字 + 数量 + 悬浮菜单按钮"""

    HEIGHT = 36

    def __init__(self, master, playlist, on_select=None, on_menu=None,
                 on_rename=None, active=False):
        super().__init__(master, height=self.HEIGHT, bg=T.SIDEBAR,
                         highlightthickness=0, bd=0, takefocus=0)
        self.playlist = playlist
        self.on_select = on_select
        self.on_menu = on_menu
        self.on_rename = on_rename
        self._active = active
        self._hover = False
        self._hover_menu = False
        self._drop = False          # 拖拽悬停高亮

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Double-Button-1>", self._on_double)
        self.bind("<Button-3>", self._on_right)
        self.bind("<Configure>", lambda e: self._redraw())
        self._menu_hit = (0, 0, 0, 0)
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 190
        h = self.HEIGHT
        if w <= 1:
            w = 190

        if self._active:
            bg = T.ACCENT_SOFT
        elif self._drop:
            bg = T.ACCENT_SOFT
        elif self._hover:
            bg = T.SIDEBAR_HOVER
        else:
            bg = T.SIDEBAR
        if bg != T.SIDEBAR:
            icons.rounded_rect(self, 6, 2, w - 6, h - 2, T.RADIUS_SM,
                               fill=bg,
                               outline=T.ACCENT if self._drop else bg)

        fg = T.TEXT if (self._active or self._hover) else T.TEXT_2
        icon_color = T.ACCENT_TEXT if self._active else T.TEXT_3
        icons.draw_icon(self, "list", 24, h / 2, 15, icon_color)

        count = str(len(self.playlist.get("tracks") or []))
        try:
            import tkinter.font as tkfont
            font = tkfont.Font(font=T.Fonts(self).small)
        except Exception:
            font = None
        avail = w - 44 - 30
        name = T.ellipsize(self.playlist.get("name", ""), font, avail) \
            if font else self.playlist.get("name", "")
        self.create_text(44, h / 2, text=name, fill=fg,
                         font=T.Fonts(self).small, anchor="w")
        self.create_text(w - 16, h / 2, text=count, fill=T.TEXT_3,
                         font=T.Fonts(self).tiny, anchor="e")

        # 悬浮时的「…」按钮
        if self._hover:
            mx = w - 34
            self._menu_hit = (mx - 11, h / 2 - 11, mx + 11, h / 2 + 11)
            if self._hover_menu:
                icons.circle(self, mx, h / 2, 11, fill=T.ELEVATED,
                             outline=T.ELEVATED)
            icons.draw_icon(self, "more", mx, h / 2, 13,
                            T.TEXT if self._hover_menu else T.TEXT_2)
        else:
            self._menu_hit = (-99, -99, -99, -99)

    def _in_menu(self, event):
        x1, y1, x2, y2 = self._menu_hit
        return x1 <= event.x <= x2 and y1 <= event.y <= y2

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._hover_menu = False
        self._redraw()

    def _on_click(self, event):
        if self._in_menu(event):
            if self.on_menu:
                self.on_menu(self.playlist, event.x_root, event.y_root)
            return
        if self.on_select:
            self.on_select(self.playlist)

    def _on_double(self, _e=None):
        if self.on_rename:
            self.on_rename(self.playlist)

    def _on_right(self, event):
        if self.on_menu:
            self.on_menu(self.playlist, event.x_root, event.y_root)


# ============================================================
# 下载任务行
# ============================================================
class DownloadRow(tk.Canvas):
    """下载管理里的一行任务"""

    HEIGHT = 62

    def __init__(self, master, task, on_retry=None, on_cancel=None,
                 on_remove=None, on_open=None):
        super().__init__(master, height=self.HEIGHT, bg=T.PANEL,
                         highlightthickness=0, bd=0, takefocus=0)
        self.task = task
        self.on_retry = on_retry
        self.on_cancel = on_cancel
        self.on_remove = on_remove
        self.on_open = on_open
        self._hover = False
        self._btn_zones = []
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.bind("<Button-3>", self._right)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    # ---------------- 绘制 ----------------
    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 600
        h = self.HEIGHT
        if w <= 1:
            w = 600

        bg = T.HOVER if self._hover else T.PANEL
        icons.rounded_rect(self, 0, 2, w - 1, h - 3, T.RADIUS_SM,
                           fill=bg, outline=bg)

        fonts = T.Fonts(self)
        task = self.task
        track = task.track
        status = task.status

        # 状态色
        color = {
            STATUS_DONE: T.GREEN,
            STATUS_FAILED: T.ROSE,
            STATUS_RUNNING: T.ACCENT_TEXT,
            STATUS_WAITING: T.TEXT_3,
        }.get(status, T.TEXT_3)

        # 左侧：状态圆环 / 图标
        cx, cy = 30, h / 2
        if status == STATUS_DONE:
            icons.draw_icon(self, "check", cx, cy, 20, T.GREEN)
        elif status == STATUS_FAILED:
            icons.draw_icon(self, "warning", cx, cy, 20, T.ROSE)
        else:
            ring = W.ProgressRing(self, size=30, bg=bg, color=color)
            ring.place(x=cx - 15, y=int(cy) - 15)
            ring.set_value(task.progress if status == STATUS_RUNNING else 0.02,
                           text="")
            self._btn_zones_ring = ring

        # 标题 / 副标题
        title = tray.track_title(track)
        artist = tray.track_artist(track)
        sub_parts = [T.platform_name(tray.track_platform(track))]
        if artist:
            sub_parts.append(artist)
        if status == STATUS_RUNNING:
            if task.total:
                sub_parts.append(
                    f"{human_size(task.received)} / {human_size(task.total)}")
            else:
                sub_parts.append(human_size(task.received))
            if task.speed:
                sub_parts.append(human_speed(task.speed))
        elif status == STATUS_DONE:
            sub_parts.append(human_size(os.path.getsize(task.path))
                             if task.path and os.path.exists(task.path)
                             else "")
        elif status == STATUS_FAILED and task.error:
            sub_parts.append(task.error)
        sub_parts = [p for p in sub_parts if p]

        import tkinter.font as tkfont
        try:
            f_title = tkfont.Font(font=fonts.body)
            f_sub = tkfont.Font(font=fonts.small)
        except Exception:
            f_title = f_sub = None

        avail = max(120, w - 78 - 210)
        self.create_text(58, cy - 11,
                         text=T.ellipsize(title, f_title, avail) if f_title else title,
                         fill=T.TEXT,
                         font=fonts.body, anchor="w")
        sub_text = "  ·  ".join(sub_parts)
        self.create_text(58, cy + 12,
                         text=T.ellipsize(sub_text, f_sub, avail) if f_sub else sub_text,
                         fill=color if status == STATUS_RUNNING else T.TEXT_3,
                         font=fonts.small, anchor="w")

        # 进度条（贴着卡片底部）
        if status == STATUS_RUNNING:
            bar_x1, bar_x2 = 58, max(120, w - 210)
            bar_y = h - 9
            icons.rounded_rect(self, bar_x1, bar_y - 3, bar_x2, bar_y + 3, 3,
                               fill=T.ELEVATED, outline=T.ELEVATED)
            fill_x = bar_x1 + (bar_x2 - bar_x1) * max(0.0, min(1.0, task.progress))
            if fill_x > bar_x1 + 3:
                icons.rounded_rect(self, bar_x1, bar_y - 3, fill_x, bar_y + 3,
                                   3, fill=T.ACCENT, outline=T.ACCENT)

        # 右侧按钮
        self._btn_zones = []
        bx = w - 22

        def add_button(icon_name, color_, callback, tip):
            nonlocal bx
            zone = (bx - 14, cy - 14, bx + 14, cy + 14)
            hit = any(zone[0] < z[2] and zone[2] > z[0] and
                      zone[1] < z[3] and zone[3] > z[1]
                      for z, _ in self._btn_zones)
            icons.draw_icon(self, icon_name, bx, cy, 16,
                            T.TEXT if hit else color_)
            self._btn_zones.append((zone, callback))
            bx -= 34

        if status in (STATUS_WAITING, STATUS_RUNNING):
            add_button("close", T.TEXT_2, self.on_cancel, "取消")
        else:
            add_button("trash", T.TEXT_2, self.on_remove, "移除记录")
            if status == STATUS_FAILED:
                add_button("refresh", T.AMBER, self.on_retry, "重试")
            if status == STATUS_DONE:
                add_button("folder", T.TEXT_2, self.on_open, "打开所在文件夹")

        # 状态文字
        self.create_text(bx - 6, cy, text=STATUS_TEXT.get(status, status),
                         fill=color, font=fonts.small, anchor="e")

    # ---------------- 交互 ----------------
    def _enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _click(self, event):
        for (x1, y1, x2, y2), callback in self._btn_zones:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                if callback:
                    callback(self.task)
                return

    def _right(self, event):
        menu = tk.Menu(self, tearoff=0, bg=T.ELEVATED, fg=T.TEXT,
                       activebackground=T.ACCENT,
                       activeforeground=T.TEXT_ON_ACCENT, bd=0)
        task = self.task
        if task.status == STATUS_DONE:
            menu.add_command(label="打开所在文件夹",
                             command=lambda: self.on_open and self.on_open(task))
            menu.add_command(label="播放该文件",
                             command=lambda: self.on_play and self.on_play(task))
        if task.status in (STATUS_FAILED,):
            menu.add_command(label="重试",
                             command=lambda: self.on_retry and self.on_retry(task))
        if task.status in (STATUS_WAITING, STATUS_RUNNING):
            menu.add_command(label="取消",
                             command=lambda: self.on_cancel and self.on_cancel(task))
        menu.add_separator()
        menu.add_command(label="移除记录",
                         command=lambda: self.on_remove and self.on_remove(task))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


# ============================================================
# 主应用
# ============================================================
class PlayerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"🎵 {APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1280x820")
        self.root.minsize(1060, 660)
        self.root.configure(bg=T.BG)
        try:
            self.root.tk.call("tk", "scaling", 1.0)
        except Exception:
            pass

        self.fonts = T.Fonts(root)
        T.apply_ttk_theme(root)

        # ---------------- 数据层 ----------------
        self.cfg = load_config()
        app_cfg = self.cfg.setdefault("app", {})
        app_cfg.setdefault("download_dir", default_download_dir())
        app_cfg.setdefault("play_mode", "sequential")
        app_cfg.setdefault("volume", 0.7)

        self.store = tray.PlaylistStore()
        self.accounts = A.AccountStore(self.cfg, save=self._persist_config)
        self.player = MusicPlayer()
        self.player.set_volume(float(app_cfg.get("volume") or 0.7))
        self.queue = PlayQueue(
            self.player, clients={}, mode=mode_from_config(self.cfg),
            on_track=self._on_track_changed,
            on_state=self._on_player_state,
            on_mode=self._on_mode_changed,
            on_queue=self._on_queue_changed,
            on_error=self._on_play_error,
        )
        self.downloads = DownloadManager(
            resolve=self.resolve_url,
            on_change=self._on_downloads_changed,
            directory=app_cfg.get("download_dir"),
            max_workers=2, store=self.store,
        )

        self.clients = {}
        self._item_data = {}            # tree iid -> (track, position)
        self._search_token = 0
        self._search_results = []
        self._view = VIEW_HOME
        self._current_track = None
        self._current_index = -1
        self._pause_icon_state = False
        self._loading_pulse = 0
        self._ui_ready = False
        self._alive = True
        self._ui_queue = queue.Queue()      # 工作线程 → UI 线程的回调队列
        self._download_rows = {}
        self._playlist_rows = []
        self._login_dialog = None
        self._login_intent = None       # (platform, "new"/"auto")
        self._library = {}
        self._library_cache = {}
        self._library_cache_tracks = []
        self._playlist_tracks = []
        self._local_cache = {}
        self._local_tracks_cache = []
        self._drag_tree = None
        self._drag_start = (0, 0)
        self._dragging = False
        self._last_volume = 0.7

        # 首页 / 封面
        self.app_cfg = app_cfg
        self.version = APP_VERSION
        self.config_file = CONFIG_PATH
        self.playlist_file = tray.PLAYLIST_FILE
        self.cache_dir = os.path.dirname(CACHE_DIR)
        self.cover_loader = COVER.CoverLoader(max_workers=3)
        self.cover_cache = COVER.CoverCache(self.cover_loader)
        self._cover_arts = []           # 需要在封面下好后重绘的控件
        self.feed_cache = FEED.FeedCache()
        self.play_history = self._load_history()
        self._stations = []
        self._stations_loaded = False
        self._settings_dialog = None

        # 浏览历史（前进 / 后退）
        self._nav_stack = []
        self._nav_pos = -1

        self._init_clients()

        # ---------------- 界面 ----------------
        self._build_ui()
        self._refresh_playlists()
        self._refresh_library()
        self._refresh_downloads()
        self._refresh_accounts()
        self._update_mode_button()
        self._update_volume_icon()
        self._switch_view(VIEW_HOME)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<space>", self._on_space)
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<Control-n>", lambda e: self._create_playlist())
        self.root.bind("<Delete>", lambda e: self._delete_selected_tracks())
        self.root.bind("<Escape>", lambda e: self._stop())

        self._ui_ready = True
        self._tick_ui()
        self._refresh_home()
        if not self.player.mixer_ok:
            self.root.after(600, lambda: W.Toast.show(
                self.root, "音频设备不可用，播放会没有声音", "warn", 4000))
        elif find_ffmpeg() is None:
            # ffmpeg 只用于兜底转码，缺了不影响播放 mp3
            self.root.after(1800, lambda: W.Toast.show(
                self.root,
                "未找到 ffmpeg：把 ffmpeg.exe 放到程序根目录即可播放 flac/m4a 等格式",
                "info", 5600))

        # 自动检查更新（按设置里的间隔，默认每 24 小时）
        if updater.should_check(self.app_cfg):
            self.root.after(2600, self._maybe_check_update)

    # ==================================================
    # 平台客户端
    # ==================================================
    def _init_clients(self):
        """（重新）实例化各平台客户端

        凭据统一从「当前账号」取（见 accounts.AccountStore），
        所以切换账号后调一次这个函数就完成了热切换。
        """
        clients = {}
        active = {}

        def safe(key, factory):
            try:
                clients[key] = factory()
                account = self.accounts.current(key)
                active[key] = account.get("label", "") if account else ""
            except Exception as exc:
                print(f"[{T.platform_name(key)}] 初始化失败: {exc}")
                active[key] = ""

        def netease():
            from platforms.netease import NeteaseClient
            return NeteaseClient(**self.accounts.client_kwargs("netease"))

        def qqmusic():
            from platforms.qqmusic import QQMusicClient
            return QQMusicClient(**self.accounts.client_kwargs("qqmusic"))

        def kugou():
            from platforms.kugou import KugouClient
            return KugouClient(**self.accounts.client_kwargs("kugou"))

        def qishui():
            from platforms.qishui import QishuiClient
            return QishuiClient(**self.accounts.client_kwargs("qishui"))

        def bilibili():
            from platforms.bilibili import BilibiliClient
            return BilibiliClient(**self.accounts.client_kwargs("bilibili"))

        safe("netease", netease)
        safe("qqmusic", qqmusic)
        safe("kugou", kugou)
        safe("qishui", qishui)
        safe("bilibili", bilibili)

        self.clients = clients
        self.active_accounts = active
        self.queue.set_clients(clients)

    # ==================================================
    # 界面搭建（三大块：顶部搜索栏 / 左侧导航 / 底部播放条）
    # ==================================================
    def _build_ui(self):
        self.main = tk.Frame(self.root, bg=T.BG)
        self.main.pack(fill=tk.BOTH, expand=True)

        self._build_topbar()

        middle = tk.Frame(self.main, bg=T.BG)
        middle.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(middle, bg=T.SIDEBAR, width=T.SIDEBAR_W)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        self.content = tk.Frame(middle, bg=T.BG)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_sidebar()
        self._build_content()
        self._build_playbar()

    # ---------------- 顶部搜索栏 ----------------
    def _build_topbar(self):
        bar = tk.Frame(self.main, bg=T.PANEL, height=58)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Frame(bar, bg=T.BORDER_SOFT, height=1).place(x=0, rely=1.0,
                                                        relwidth=1.0)

        # 左侧：logo
        brand = tk.Frame(bar, bg=T.PANEL)
        brand.pack(side=tk.LEFT, padx=(16, 10))
        logo = tk.Canvas(brand, width=30, height=30, bg=T.PANEL,
                         highlightthickness=0, bd=0)
        logo.pack(side=tk.LEFT, pady=14)
        icons.rounded_rect(logo, 0, 0, 29, 29, 9,
                           fill=T.ACCENT, outline=T.ACCENT)
        icons.draw_icon(logo, "music", 15, 15, 17, "#ffffff")
        tk.Label(brand, text="音乐播放器", bg=T.PANEL, fg=T.TEXT,
                 font=self.fonts.h3).pack(side=tk.LEFT, padx=(8, 0))

        # 右侧：账号 + 设置
        right = tk.Frame(bar, bg=T.PANEL)
        right.pack(side=tk.RIGHT, padx=(0, 16))

        W.IconButton(right, "gear", command=self.open_settings, size=32,
                     icon_size=16, bg=T.PANEL, hover_bg=T.ELEVATED,
                     fg=T.TEXT_2, tooltip="设置（含自动更新）").pack(
            side=tk.RIGHT, padx=(6, 0))
        W.IconButton(right, "download", command=lambda:
                     self._switch_view(VIEW_DOWNLOAD), size=32, icon_size=16,
                     bg=T.PANEL, hover_bg=T.ELEVATED, fg=T.TEXT_2,
                     tooltip="下载管理").pack(side=tk.RIGHT, padx=(6, 0))

        self.top_account = tk.Frame(right, bg=T.ELEVATED, cursor="hand2")
        self.top_account.pack(side=tk.RIGHT, padx=(10, 0))
        acct_inner = tk.Frame(self.top_account, bg=T.ELEVATED)
        acct_inner.pack(padx=12, pady=6)
        dot = tk.Canvas(acct_inner, width=18, height=18, bg=T.ELEVATED,
                        highlightthickness=0, bd=0)
        dot.pack(side=tk.LEFT)
        icons.circle(dot, 9, 9, 6, fill=T.ACCENT, outline=T.ACCENT)
        self.top_account_label = tk.Label(acct_inner, text="未登录",
                                          bg=T.ELEVATED, fg=T.TEXT,
                                          font=self.fonts.small)
        self.top_account_label.pack(side=tk.LEFT, padx=(6, 0))
        for widget in (self.top_account, acct_inner, dot,
                       self.top_account_label):
            widget.bind("<Button-1>",
                        lambda e: self._switch_view(VIEW_ACCOUNTS))
        self._bind_hover(self.top_account, T.ELEVATED, T.HOVER)

        # 中间：后退 / 前进 / 搜索框
        center = tk.Frame(bar, bg=T.PANEL)
        center.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 10))

        self.back_btn = W.IconButton(
            center, "prev", command=lambda: self._nav_back(), size=30,
            icon_size=13, bg=T.PANEL, hover_bg=T.ELEVATED, fg=T.TEXT_2,
            tooltip="后退")
        self.back_btn.pack(side=tk.LEFT)
        self.forward_btn = W.IconButton(
            center, "next", command=lambda: self._nav_forward(), size=30,
            icon_size=13, bg=T.PANEL, hover_bg=T.ELEVATED, fg=T.TEXT_2,
            tooltip="前进")
        self.forward_btn.pack(side=tk.LEFT, padx=(2, 10))

        search_wrap = tk.Frame(center, bg=T.ELEVATED, highlightthickness=1,
                               highlightbackground=T.BORDER)
        search_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_scope_btn = tk.Canvas(search_wrap, width=26, height=26,
                                          bg=T.ELEVATED,
                                          highlightthickness=0, bd=0,
                                          cursor="hand2")
        self.search_scope_btn.pack(side=tk.LEFT, padx=(8, 0), pady=7)
        icons.draw_icon(self.search_scope_btn, "search", 13, 13, 15, T.TEXT_2)
        self.search_scope_btn.bind("<Button-1>",
                                   lambda e: self._open_scope_menu(e))

        self.search_entry = tk.Entry(
            search_wrap, bg=T.ELEVATED, fg=T.TEXT,
            insertbackground=T.ACCENT, relief=tk.FLAT, bd=0,
            font=self.fonts.body)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
                               padx=(6, 8), pady=9)
        self.search_entry.bind("<Return>", lambda e: self.do_search())
        self.search_entry.bind("<FocusIn>", lambda e: (
            search_wrap.configure(highlightbackground=T.ACCENT),
            self._show_search_hint()))
        self.search_entry.bind("<FocusOut>", lambda e: (
            search_wrap.configure(highlightbackground=T.BORDER),
            self._hide_search_hint()))

        self.search_scope_label = tk.Label(
            search_wrap, text="全部", bg=T.ELEVATED, fg=T.ACCENT_TEXT,
            font=self.fonts.tiny, cursor="hand2")
        self.search_scope_label.pack(side=tk.LEFT, padx=(0, 6))
        self.search_scope_label.bind("<Button-1>",
                                     lambda e: self._open_scope_menu(e))

        self.search_go = W.PrimaryButton(
            center, "搜索", icon="search", command=self.do_search,
            bg=T.ACCENT, fg=T.TEXT_ON_ACCENT, hover_bg=T.ACCENT_HOVER,
            panel_bg=T.PANEL, min_width=92, height=34)
        self.search_go.pack(side=tk.LEFT, padx=(10, 0))

        # 搜索建议浮层（点搜索框时出现的快捷词）
        self._search_hint = None
        self._search_scope = "全部"

    def _show_search_hint(self):
        if self._search_hint is not None:
            return
        try:
            hint = tk.Frame(self.content, bg=T.PANEL, highlightthickness=1,
                            highlightbackground=T.BORDER)
            hint.place(x=0, y=0, relwidth=1.0)
            row = tk.Frame(hint, bg=T.PANEL)
            row.pack(fill=tk.X, padx=12, pady=8)
            tk.Label(row, text="试试：", bg=T.PANEL, fg=T.TEXT_3,
                     font=self.fonts.tiny).pack(side=tk.LEFT)
            for keyword in QUICK_KEYWORDS:
                chip = tk.Label(row, text=keyword, bg=T.ELEVATED,
                                fg=T.TEXT_2, font=self.fonts.tiny, padx=10,
                                pady=3, cursor="hand2")
                chip.pack(side=tk.LEFT, padx=3)
                chip.bind("<Enter>", lambda e, c=chip: c.configure(
                    bg=T.ACCENT_SOFT, fg=T.ACCENT_TEXT))
                chip.bind("<Leave>", lambda e, c=chip: c.configure(
                    bg=T.ELEVATED, fg=T.TEXT_2))
                chip.bind("<Button-1>",
                          lambda e, k=keyword: self._quick_search(k))
            self._search_hint = hint
        except Exception as exc:
            print("[搜索] 提示浮层创建失败:", exc)

    def _hide_search_hint(self):
        if self._search_hint is not None:
            try:
                self._search_hint.destroy()
            except Exception:
                pass
            self._search_hint = None

    def _open_scope_menu(self, event):
        """选择搜索范围（全部 / 各平台）"""
        menu = tk.Menu(self.root, tearoff=0, bg=T.ELEVATED, fg=T.TEXT,
                       activebackground=T.ACCENT,
                       activeforeground=T.TEXT_ON_ACCENT, bd=0)
        options = ["全部"] + [T.platform_name(k) for k in T.PLATFORM_KEYS]
        for label in options:
            menu.add_command(label=label,
                             command=lambda v=label: self._set_scope(v))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_scope(self, label):
        self._search_scope = label
        self.search_scope_label.configure(text=label)
        if hasattr(self, "platform_select"):
            self.platform_select.set(label)

    # ---------------- 侧边栏 ----------------
    def _build_sidebar(self):
        # 导航
        self.nav_buttons = {}
        nav_items = [
            (VIEW_HOME, "发现音乐", "music"),
            (VIEW_SEARCH, "搜索", "search"),
            (VIEW_LIBRARY, "全部音乐", "list"),
            (VIEW_LOCAL, "本地音乐", "folder"),
        ]
        for key, label, icon in nav_items:
            self.nav_buttons[key] = self._make_nav_button(label, icon, key)

        tk.Frame(self.sidebar, bg=T.BORDER_SOFT, height=1).pack(
            fill=tk.X, padx=14, pady=(12, 0))

        # 我的音乐
        head = tk.Frame(self.sidebar, bg=T.SIDEBAR)
        head.pack(fill=tk.X, padx=16, pady=(10, 2))
        tk.Label(head, text="我的音乐", bg=T.SIDEBAR, fg=T.TEXT_3,
                 font=self.fonts.tiny).pack(side=tk.LEFT)

        mine = tk.Frame(self.sidebar, bg=T.SIDEBAR)
        mine.pack(fill=tk.X)
        self._mine_rows = []
        for key, label, icon in (
                (VIEW_DOWNLOAD, "下载管理", "download"),
                (VIEW_ACCOUNTS, "账号管理", "gear")):
            self.nav_buttons[key] = self._make_nav_button(label, icon, key,
                                                          parent=mine,
                                                          small=True)

        # 歌单区
        header = tk.Frame(self.sidebar, bg=T.SIDEBAR)
        header.pack(fill=tk.X, padx=16, pady=(12, 4))
        tk.Label(header, text="创建的歌单", bg=T.SIDEBAR, fg=T.TEXT_3,
                 font=self.fonts.tiny).pack(side=tk.LEFT)
        self.new_playlist_btn = W.IconButton(
            header, "plus", command=self._create_playlist, size=22,
            icon_size=12, bg=T.SIDEBAR, hover_bg=T.SIDEBAR_HOVER,
            fg=T.TEXT_2, tooltip="新建播放列表 (Ctrl+N)")
        self.new_playlist_btn.pack(side=tk.RIGHT)

        self.playlist_box = tk.Frame(self.sidebar, bg=T.SIDEBAR)
        self.playlist_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 8))

        # 底部：账号状态（点一下进账号管理）
        tk.Frame(self.sidebar, bg=T.BORDER_SOFT, height=1).pack(
            fill=tk.X, padx=14, pady=(4, 8))

        bottom = tk.Frame(self.sidebar, bg=T.SIDEBAR)
        bottom.pack(fill=tk.X, padx=10, pady=(0, 14))
        self.login_btn = tk.Frame(bottom, bg=T.SIDEBAR_HOVER, cursor="hand2")
        self.login_btn.pack(fill=tk.X)
        inner = tk.Frame(self.login_btn, bg=T.SIDEBAR_HOVER)
        inner.pack(fill=tk.X, padx=10, pady=(8, 8))
        row1 = tk.Frame(inner, bg=T.SIDEBAR_HOVER)
        row1.pack(fill=tk.X)
        login_canvas = tk.Canvas(row1, width=18, height=18,
                                 bg=T.SIDEBAR_HOVER, highlightthickness=0,
                                 bd=0)
        login_canvas.pack(side=tk.LEFT)
        self.login_icon = login_canvas
        self.login_label = tk.Label(row1, text="账号管理", bg=T.SIDEBAR_HOVER,
                                    fg=T.TEXT, font=self.fonts.small)
        self.login_label.pack(side=tk.LEFT, padx=(8, 0))
        # 每个平台的登录状态小圆点
        self.account_dots = tk.Frame(row1, bg=T.SIDEBAR_HOVER)
        self.account_dots.pack(side=tk.RIGHT)

        self.login_status = tk.Label(inner, text="未登录任何平台",
                                     bg=T.SIDEBAR_HOVER, fg=T.TEXT_3,
                                     font=self.fonts.tiny, anchor="w",
                                     wraplength=T.SIDEBAR_W - 46,
                                     justify=tk.LEFT)
        self.login_status.pack(fill=tk.X, pady=(3, 0))

        for widget in (self.login_btn, inner, row1, login_canvas,
                       self.login_label, self.login_status, self.account_dots):
            widget.bind("<Button-1>", lambda e: self._switch_view(VIEW_ACCOUNTS))
        self._bind_hover(self.login_btn, T.SIDEBAR_HOVER, T.ELEVATED)

    def _bind_hover(self, widget, normal, hover):
        def enter(_e=None):
            for child in [widget] + list(widget.winfo_children()):
                try:
                    child.configure(bg=hover)
                except Exception:
                    pass

        def leave(_e=None):
            for child in [widget] + list(widget.winfo_children()):
                try:
                    child.configure(bg=normal)
                except Exception:
                    pass

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")

    def _make_nav_button(self, label, icon, key, parent=None, small=False):
        parent = parent or self.sidebar
        height = 32 if small else 38
        frame = tk.Frame(parent, bg=T.SIDEBAR, cursor="hand2")
        frame.pack(fill=tk.X, padx=8, pady=(1 if small else 2))

        canvas = tk.Canvas(frame, height=height, bg=T.SIDEBAR,
                           highlightthickness=0, bd=0)
        canvas.pack(fill=tk.X)

        font = self.fonts.small if small else self.fonts.body
        icon_x = 20
        text_x = 42
        icon_size = 15 if small else 17

        def draw(hover=False, active=False):
            canvas.delete("all")
            w = canvas.winfo_width() or (T.SIDEBAR_W - 16)
            h = height
            if active:
                bg = T.ACCENT_SOFT
            elif hover:
                bg = T.SIDEBAR_HOVER
            else:
                bg = T.SIDEBAR
            if bg != T.SIDEBAR:
                icons.rounded_rect(canvas, 0, 1, w - 1, h - 1, T.RADIUS_SM,
                                   fill=bg, outline=bg)
            fg = T.TEXT if (active or hover) else T.TEXT_2
            icon_color = T.ACCENT_TEXT if active else (
                T.TEXT if hover else T.TEXT_3)
            icons.draw_icon(canvas, icon, icon_x, h / 2, icon_size, icon_color)
            # 选中态左侧高亮条
            if active:
                icons.rounded_rect(canvas, 1, h / 2 - 8, 4, h / 2 + 8, 1.5,
                                   fill=T.ACCENT, outline=T.ACCENT)
            canvas.create_text(text_x, h / 2, text=label, fill=fg,
                               font=font, anchor="w")

        state = {"hover": False, "active": False}

        def redraw(_e=None):
            draw(state["hover"], state["active"])

        def enter(_e=None):
            state["hover"] = True
            redraw()

        def leave(_e=None):
            state["hover"] = False
            redraw()

        canvas.bind("<Enter>", enter)
        canvas.bind("<Leave>", leave)
        canvas.bind("<Button-1>", lambda e: self._switch_view(key))
        canvas.bind("<Configure>", redraw)

        canvas._set_active = lambda active: (
            state.__setitem__("active", active), redraw())
        return canvas

    # ---------------- 内容区 ----------------
    def _build_content(self):
        # 顶部标题栏
        header = tk.Frame(self.content, bg=T.BG)
        header.pack(fill=tk.X, padx=24, pady=(18, 6))

        self.view_title = tk.Label(header, text="搜索", bg=T.BG, fg=T.TEXT,
                                   font=self.fonts.h1)
        self.view_title.pack(side=tk.LEFT)
        self.view_subtitle = tk.Label(header, text="", bg=T.BG, fg=T.TEXT_3,
                                      font=self.fonts.small)
        self.view_subtitle.pack(side=tk.LEFT, padx=(12, 0), pady=(6, 0))

        self.header_actions = tk.Frame(header, bg=T.BG)
        self.header_actions.pack(side=tk.RIGHT)

        self.container = tk.Frame(self.content, bg=T.BG)
        self.container.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 12))

        self.views = {}
        self.views[VIEW_HOME] = self._build_home_view()
        self.views[VIEW_SEARCH] = self._build_search_view()
        self.views[VIEW_LIBRARY] = self._build_library_view()
        self.views[VIEW_LOCAL] = self._build_local_view()
        self.views[VIEW_PLAYLIST] = self._build_playlist_view()
        self.views[VIEW_DOWNLOAD] = self._build_download_view()
        self.views[VIEW_ACCOUNTS] = self._build_accounts_view()

    # ---- 首页（发现音乐）----
    def _build_home_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        self.home_scroll = W.ScrollFrame(view, bg=T.BG)
        self.home_scroll.pack(fill=tk.BOTH, expand=True)
        self.home_body = self.home_scroll.body
        self.home_body.configure(bg=T.BG)

        # 顶部一排分类卡片
        self._home_section_title(self.home_body, "推荐", "每天都不一样")
        self.category_row = CARD.CardRow(self.home_body, bg=T.BG,
                                         height=196, gap=14)
        self.category_row.pack(fill=tk.X, pady=(0, 4))
        self._build_category_cards()

        # 推荐歌单（横向一排）
        self.station_title = self._home_section_title(
            self.home_body, "推荐歌单", "来自五个平台的实时搜索")
        self.station_row = CARD.CardRow(self.home_body, bg=T.BG,
                                       height=214, gap=16)
        self.station_row.pack(fill=tk.X, pady=(0, 4))

        # 猜你喜欢（网格）
        self.grid_title = self._home_section_title(
            self.home_body, "猜你喜欢", "根据你的音乐库挑选")
        self.home_grid = tk.Frame(self.home_body, bg=T.BG)
        self.home_grid.pack(fill=tk.X)

        self.home_hint = tk.Label(
            self.home_body,
            text="提示：先搜索几首歌，或者登录账号，这里的内容会更贴近你的口味。",
            bg=T.BG, fg=T.TEXT_3, font=self.fonts.tiny, anchor="w",
            justify=tk.LEFT)
        self.home_hint.pack(fill=tk.X, pady=(18, 24))
        return view

    def _home_section_title(self, parent, title, hint=""):
        row = tk.Frame(parent, bg=T.BG)
        row.pack(fill=tk.X, pady=(18, 10))
        tk.Label(row, text=title, bg=T.BG, fg=T.TEXT,
                 font=self.fonts.h3).pack(side=tk.LEFT)
        chevron = tk.Canvas(row, width=16, height=16, bg=T.BG,
                            highlightthickness=0, bd=0)
        chevron.pack(side=tk.LEFT, padx=(2, 0))
        icons.draw_icon(chevron, "chevron_right", 8, 8, 12, T.TEXT_3)
        if hint:
            tk.Label(row, text=hint, bg=T.BG, fg=T.TEXT_3,
                     font=self.fonts.tiny).pack(side=tk.LEFT, padx=(10, 0))
        return row

    def _build_category_cards(self):
        """首页顶部那几个大卡片"""
        self.category_row.clear()
        library = self._library_tracks()
        history = self.play_history
        for spec in FEED.CATEGORY_CARDS:
            count = 0
            if spec["key"] == "daily":
                count = len(FEED.build_daily(library, history))
            elif spec["key"] == "guess":
                count = len(FEED.build_guess(library, history, None))
            elif spec["key"] == "recent":
                count = len(history)
            elif spec["key"] == "bili":
                count = sum(1 for t in library if t.get("platform") == "bilibili")
            elif spec["key"] == "instrumental":
                count = sum(1 for t in library
                            if "纯音乐" in (t.get("title") or "")
                            or "钢琴" in (t.get("title") or ""))

            subtitle = spec["subtitle"]
            if count:
                subtitle = f"{count} 首 · {spec['subtitle']}"

            card = CARD.BigCard(
                self.category_row.inner, title=spec["title"],
                subtitle=subtitle, seed=f"category::{spec['key']}",
                size=140, cache=self.cover_cache, bg=T.BG,
                command=lambda k=spec["key"]: self._open_category(k))
            self.category_row.add(card)

    # ---- 搜索视图 ----
    def _build_search_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        toolbar = tk.Frame(view, bg=T.BG)
        toolbar.pack(fill=tk.X, pady=(4, 10))

        tk.Label(toolbar, text="搜索范围", bg=T.BG, fg=T.TEXT_3,
                 font=self.fonts.small).pack(side=tk.LEFT, padx=(2, 8))
        self.platform_select = W.Dropdown(
            toolbar, ["全部"] + [T.platform_name(k) for k in T.PLATFORM_KEYS],
            width=118, bg=T.BG, initial=self._search_scope,
            on_change=self._on_platform_change)
        self.platform_select.pack(side=tk.LEFT)

        W.PrimaryButton(toolbar, "重新搜索", icon="search",
                        command=self.do_search, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.BG,
                        min_width=114).pack(side=tk.LEFT, padx=(10, 0))
        W.PrimaryButton(toolbar, "清空结果", icon="close",
                        command=self.clear_results, bg=T.ELEVATED,
                        fg=T.TEXT_2, panel_bg=T.BG,
                        min_width=110).pack(side=tk.LEFT, padx=(8, 0))

        W.PrimaryButton(toolbar, "播放全部", icon="play",
                        command=lambda: self._play_list(self._search_results,
                                                        "搜索结果"),
                        bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                        hover_bg=T.ACCENT_HOVER, panel_bg=T.BG,
                        min_width=112).pack(side=tk.RIGHT)
        W.PrimaryButton(toolbar, "批量下载", icon="download",
                        command=lambda: self._download_tracks(
                            self._search_results, ""),
                        bg=T.ELEVATED, fg=T.TEXT, panel_bg=T.BG,
                        min_width=112).pack(side=tk.RIGHT, padx=(0, 8))

        # 列表
        list_wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                             highlightbackground=T.BORDER)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        self.search_tree = self._make_tree(list_wrap)
        self.search_empty = tk.Label(
            list_wrap, text="在上面输入关键词，回车即可跨平台搜索",
            bg=T.PANEL, fg=T.TEXT_3, font=self.fonts.body)
        self.search_tree.bind("<Map>", lambda e: None)
        return view

    def _on_platform_change(self, label):
        self._search_scope = label
        try:
            self.search_scope_label.configure(text=label)
        except Exception:
            pass

    def _make_chip(self, parent, keyword):
        chip = tk.Label(parent, text=keyword, bg=T.ELEVATED, fg=T.TEXT_2,
                        font=self.fonts.tiny, padx=10, pady=4, cursor="hand2")
        chip.pack(side=tk.LEFT, padx=3)

        def enter(_e=None):
            chip.configure(bg=T.ACCENT_SOFT, fg=T.ACCENT_TEXT)

        def leave(_e=None):
            chip.configure(bg=T.ELEVATED, fg=T.TEXT_2)

        chip.bind("<Enter>", enter)
        chip.bind("<Leave>", leave)
        chip.bind("<Button-1>", lambda e: self._quick_search(keyword))
        return chip

    def _quick_search(self, keyword):
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, keyword)
        self._hide_search_hint()
        self.do_search()

    # ---- 全部音乐 / 歌单视图 ----
    def _build_library_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        bar = tk.Frame(view, bg=T.BG)
        bar.pack(fill=tk.X, pady=(6, 10))

        self.library_filter = W.Dropdown(
            bar, ["全部平台"] + [T.platform_name(k) for k in T.PLATFORM_KEYS],
            width=122, bg=T.BG, on_change=lambda v: self._refresh_library())
        self.library_filter.pack(side=tk.LEFT)

        W.PrimaryButton(bar, "播放全部", icon="play",
                        command=lambda: self._play_list(self._library_tracks(),
                                                        "全部音乐"),
                        bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                        hover_bg=T.ACCENT_HOVER, panel_bg=T.BG,
                        min_width=112).pack(side=tk.LEFT, padx=(10, 0))
        W.PrimaryButton(bar, "随机播放", icon="shuffle",
                        command=self._shuffle_play_library, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.BG,
                        min_width=112).pack(side=tk.LEFT, padx=(8, 0))
        W.PrimaryButton(bar, "批量下载", icon="download",
                        command=lambda: self._download_tracks(
                            self._library_tracks(), ""),
                        bg=T.ELEVATED, fg=T.TEXT, panel_bg=T.BG,
                        min_width=112).pack(side=tk.LEFT, padx=(8, 0))

        list_wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                             highlightbackground=T.BORDER)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        self.library_tree = self._make_tree(list_wrap)
        return view

    def _build_playlist_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        # 歌单头部信息
        self.pl_header = tk.Frame(view, bg=T.BG)
        self.pl_header.pack(fill=tk.X, pady=(2, 8))

        self.pl_cover_art = CARD.CoverArt(
            self.pl_header, size=92, seed="playlist", radius=12,
            bg=T.BG, cache=self.cover_cache)
        self.pl_cover_art.pack(side=tk.LEFT)

        info = tk.Frame(self.pl_header, bg=T.BG)
        info.pack(side=tk.LEFT, padx=(16, 0), fill=tk.BOTH, expand=True)
        self.pl_name = tk.Label(info, text="", bg=T.BG, fg=T.TEXT,
                                font=(self.fonts.h1[0], 19, "bold"), anchor="w")
        self.pl_name.pack(anchor="w")
        self.pl_meta = tk.Label(info, text="", bg=T.BG, fg=T.TEXT_3,
                                font=self.fonts.small, anchor="w")
        self.pl_meta.pack(anchor="w", pady=(4, 8))

        buttons = tk.Frame(info, bg=T.BG)
        buttons.pack(anchor="w")
        W.PrimaryButton(buttons, "播放", icon="play",
                        command=self._play_active_playlist, bg=T.ACCENT,
                        fg=T.TEXT_ON_ACCENT, hover_bg=T.ACCENT_HOVER,
                        panel_bg=T.BG, min_width=92, height=32).pack(
            side=tk.LEFT)
        W.PrimaryButton(buttons, "随机", icon="shuffle",
                        command=lambda: self._play_active_playlist(shuffle=True),
                        bg=T.ELEVATED, fg=T.TEXT, panel_bg=T.BG,
                        min_width=88, height=32).pack(side=tk.LEFT, padx=6)
        W.PrimaryButton(buttons, "下载歌单", icon="download",
                        command=self._download_active_playlist, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.BG, min_width=112,
                        height=32).pack(side=tk.LEFT, padx=(0, 6))
        W.PrimaryButton(buttons, "移除选中", icon="minus",
                        command=self._remove_selected_from_playlist,
                        bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=T.BG,
                        min_width=112, height=32).pack(side=tk.LEFT)

        list_wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                             highlightbackground=T.BORDER)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        self.playlist_tree = self._make_tree(list_wrap)
        return view

    # ---- 本地音乐视图 ----
    def _build_local_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        bar = tk.Frame(view, bg=T.BG)
        bar.pack(fill=tk.X, pady=(4, 10))

        self.local_summary = tk.Label(bar, text="", bg=T.BG, fg=T.TEXT_3,
                                      font=self.fonts.small, anchor="w")
        self.local_summary.pack(side=tk.LEFT)

        W.PrimaryButton(bar, "打开下载目录", icon="folder",
                        command=self._open_download_dir, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.BG,
                        min_width=130).pack(side=tk.RIGHT)
        W.PrimaryButton(bar, "播放全部", icon="play",
                        command=lambda: self._play_list(
                            self._local_tracks(), "本地音乐"),
                        bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                        hover_bg=T.ACCENT_HOVER, panel_bg=T.BG,
                        min_width=112).pack(side=tk.RIGHT, padx=(0, 8))
        W.PrimaryButton(bar, "扫描目录", icon="refresh",
                        command=self._scan_local, bg=T.ELEVATED,
                        fg=T.TEXT_2, panel_bg=T.BG,
                        min_width=104).pack(side=tk.RIGHT, padx=(0, 8))
        W.PrimaryButton(bar, "修复文件", icon="warning",
                        command=self._repair_local, bg=T.ELEVATED,
                        fg=T.AMBER, panel_bg=T.BG,
                        min_width=104,
                        tooltip="扫描并修复早期版本写坏标签的音频").pack(
            side=tk.RIGHT, padx=(0, 8))

        list_wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                             highlightbackground=T.BORDER)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        self.local_tree = self._make_tree(list_wrap)
        return view

    # ---- 下载视图 ----
    def _build_download_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        bar = tk.Frame(view, bg=T.BG)
        bar.pack(fill=tk.X, pady=(6, 10))

        self.dl_dir_label = tk.Label(
            bar, text="", bg=T.BG, fg=T.TEXT_3, font=self.fonts.small,
            anchor="w")
        self.dl_dir_label.pack(side=tk.LEFT)

        W.PrimaryButton(bar, "打开文件夹", icon="folder",
                        command=self._open_download_dir, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.BG,
                        min_width=118).pack(side=tk.RIGHT)
        W.PrimaryButton(bar, "更换目录", icon="gear",
                        command=self._choose_download_dir, bg=T.ELEVATED,
                        fg=T.TEXT_2, panel_bg=T.BG,
                        min_width=104).pack(side=tk.RIGHT, padx=(0, 8))
        W.PrimaryButton(bar, "清空已完成", icon="trash",
                        command=self._clear_finished_downloads, bg=T.ELEVATED,
                        fg=T.TEXT_2, panel_bg=T.BG,
                        min_width=118).pack(side=tk.RIGHT, padx=(0, 8))

        self.dl_summary = tk.Label(view, text="", bg=T.BG, fg=T.TEXT_2,
                                   font=self.fonts.small, anchor="w")
        self.dl_summary.pack(fill=tk.X, pady=(0, 8))

        wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                        highlightbackground=T.BORDER)
        wrap.pack(fill=tk.BOTH, expand=True)

        self.dl_scroll = W.ScrollFrame(wrap, bg=T.PANEL)
        self.dl_scroll.pack(fill=tk.BOTH, expand=True)
        self.dl_inner = self.dl_scroll.body

        self.dl_empty = tk.Label(
            self.dl_inner,
            text="还没有下载任务\n\n在搜索结果或歌单里点「下载」即可加入队列",
            bg=T.PANEL, fg=T.TEXT_3, font=self.fonts.body, justify=tk.CENTER)
        self.dl_empty.pack(pady=60)
        return view

    # ---- 账号管理视图 ----
    def _build_accounts_view(self):
        view = tk.Frame(self.container, bg=T.BG)

        # 顶部工具条
        bar = tk.Frame(view, bg=T.BG)
        bar.pack(fill=tk.X, pady=(6, 6))

        self.acct_summary = tk.Label(bar, text="", bg=T.BG, fg=T.TEXT_2,
                                     font=self.fonts.small, anchor="w")
        self.acct_summary.pack(side=tk.LEFT)

        W.PrimaryButton(bar, "添加账号", icon="plus",
                        command=lambda: self.open_login(mode="new"),
                        bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                        hover_bg=T.ACCENT_HOVER, panel_bg=T.BG,
                        min_width=112).pack(side=tk.RIGHT)

        hint = tk.Label(
            view,
            text="一个平台可以保存多个账号，点「切换」即可让播放器改用那个账号"
                 "（切换后立即生效，无需重启）。凭据只存在本机的 config.json 里。",
            bg=T.BG, fg=T.TEXT_3, font=self.fonts.tiny, anchor="w",
            justify=tk.LEFT)
        hint.pack(fill=tk.X, pady=(0, 10))

        wrap = tk.Frame(view, bg=T.PANEL, highlightthickness=1,
                        highlightbackground=T.BORDER)
        wrap.pack(fill=tk.BOTH, expand=True)
        self.acct_scroll = W.ScrollFrame(wrap, bg=T.PANEL)
        self.acct_scroll.pack(fill=tk.BOTH, expand=True)
        self.acct_inner = self.acct_scroll.body
        return view

    # ==================================================
    # 账号管理：渲染与操作
    # ==================================================
    def _refresh_accounts(self):
        """重画账号管理页 + 侧边栏状态"""
        if not self._alive:
            return
        self._refresh_account_status()
        inner = getattr(self, "acct_inner", None)
        if inner is None:
            return
        try:
            for child in inner.winfo_children():
                child.destroy()
            counts = self.accounts.counts()
            logged = self.accounts.logged_in_platforms()
            total = sum(item["total"] for item in counts.values())
            self.acct_summary.configure(
                text=f"共 {total} 个账号 · 已登录 {len(logged)}/5 个平台")

            for platform in T.PLATFORM_KEYS:
                self._build_platform_section(inner, platform, counts[platform])
            inner.update_idletasks()
            self.acct_scroll.canvas.configure(
                scrollregion=self.acct_scroll.canvas.bbox("all"))
        except Exception as exc:
            print("[账号] 刷新失败:", exc)

    def _build_platform_section(self, parent, platform, info):
        fonts = self.fonts
        color = T.platform_color(platform)

        section = tk.Frame(parent, bg=T.PANEL)
        section.pack(fill=tk.X, padx=10, pady=(10, 4))

        # ---- 平台标题行 ----
        head = tk.Frame(section, bg=T.PANEL)
        head.pack(fill=tk.X)

        dot = tk.Canvas(head, width=16, height=16, bg=T.PANEL,
                        highlightthickness=0, bd=0)
        dot.pack(side=tk.LEFT)
        icons.circle(dot, 8, 8, 5, fill=color, outline=color)

        tk.Label(head, text=T.platform_name(platform), bg=T.PANEL, fg=T.TEXT,
                 font=fonts.body_bold).pack(side=tk.LEFT, padx=(6, 0))

        if info["total"]:
            tk.Label(head, text=f"{info['total']} 个账号", bg=T.PANEL,
                     fg=T.TEXT_3, font=fonts.tiny).pack(side=tk.LEFT,
                                                        padx=(10, 0))
        if info["logged_in"]:
            tk.Label(head, text=f"当前：{info['label']}", bg=T.PANEL,
                     fg=T.GREEN, font=fonts.small).pack(side=tk.LEFT,
                                                        padx=(10, 0))
        else:
            tk.Label(head, text="未登录", bg=T.PANEL, fg=T.TEXT_3,
                     font=fonts.small).pack(side=tk.LEFT, padx=(10, 0))

        W.PrimaryButton(head, "添加账号", icon="plus",
                        command=lambda p=platform: self.open_login(p, "new"),
                        bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=T.PANEL,
                        min_width=104, height=28,
                        font=fonts.tiny).pack(side=tk.RIGHT)

        # ---- 账号列表 ----
        accounts = self.accounts.accounts(platform)
        current_id = self.accounts.current_id(platform)

        if not accounts:
            empty = tk.Frame(section, bg=T.PANEL_ALT)
            empty.pack(fill=tk.X, pady=(6, 0))
            tk.Label(empty,
                     text="还没有保存这个平台的账号。点右上角「添加账号」，"
                          "用扫码或 Cookie 登录一次即可保存。",
                     bg=T.PANEL_ALT, fg=T.TEXT_3, font=fonts.tiny,
                     anchor="w", justify=tk.LEFT, wraplength=760,
                     padx=12, pady=10).pack(fill=tk.X)
        else:
            for account in accounts:
                self._build_account_card(section, platform, account,
                                         account.get("id") == current_id)

        tk.Frame(parent, bg=T.BORDER_SOFT, height=1).pack(
            fill=tk.X, padx=10, pady=(8, 0))

    def _build_account_card(self, parent, platform, account, is_current):
        fonts = self.fonts
        account_id = account.get("id")

        card_bg = T.ACCENT_SOFT if is_current else T.PANEL_ALT
        card = tk.Frame(parent, bg=card_bg, highlightthickness=1,
                        highlightbackground=T.ACCENT if is_current else T.BORDER)
        card.pack(fill=tk.X, pady=(6, 0))

        left = tk.Frame(card, bg=card_bg)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=9)

        name_row = tk.Frame(left, bg=card_bg)
        name_row.pack(fill=tk.X)
        tk.Label(name_row, text=account.get("label") or "未命名",
                 bg=card_bg, fg=T.TEXT, font=fonts.body_bold).pack(side=tk.LEFT)
        if is_current:
            badge = tk.Label(name_row, text=" 使用中 ", bg=T.ACCENT,
                             fg=T.TEXT_ON_ACCENT, font=fonts.tiny,
                             padx=4)
            badge.pack(side=tk.LEFT, padx=(8, 0))

        method = A.METHOD_LABELS.get(account.get("method") or "",
                                     account.get("method") or "已保存")
        last_used = account.get("last_used") or account.get("created_at") or 0
        when = time.strftime("%Y-%m-%d %H:%M",
                             time.localtime(last_used)) if last_used else "—"
        meta = f"{method} · 最近使用 {when} · {A.cred_preview(platform, account.get('cred') or {})}"
        tk.Label(left, text=meta, bg=card_bg, fg=T.TEXT_3, font=fonts.tiny,
                 anchor="w", justify=tk.LEFT, wraplength=560).pack(
            fill=tk.X, pady=(3, 0))

        # ---- 右侧按钮 ----
        actions = tk.Frame(card, bg=card_bg)
        actions.pack(side=tk.RIGHT, padx=(0, 10))

        if is_current:
            W.PrimaryButton(actions, "退出登录", icon="close",
                            command=lambda p=platform: self._logout_account(p),
                            bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=card_bg,
                            min_width=100, height=30,
                            font=fonts.tiny).pack(side=tk.RIGHT, padx=3)
            W.PrimaryButton(actions, "重新登录", icon="refresh",
                            command=lambda p=platform: self.open_login(p),
                            bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=card_bg,
                            min_width=100, height=30,
                            font=fonts.tiny).pack(side=tk.RIGHT, padx=3)
        else:
            W.PrimaryButton(actions, "切换到此账号", icon="check",
                            command=lambda p=platform, a=account_id:
                                self._switch_account(p, a),
                            bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                            hover_bg=T.ACCENT_HOVER, panel_bg=card_bg,
                            min_width=124, height=30,
                            font=fonts.tiny).pack(side=tk.RIGHT, padx=3)
            W.PrimaryButton(actions, "重新登录", icon="refresh",
                            command=lambda p=platform: self.open_login(p),
                            bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=card_bg,
                            min_width=100, height=30,
                            font=fonts.tiny).pack(side=tk.RIGHT, padx=3)

        W.IconButton(actions, "trash", size=30, icon_size=15,
                     bg=card_bg, hover_bg=T.HOVER, fg=T.TEXT_3,
                     tooltip="删除这个账号",
                     command=lambda p=platform, a=account_id:
                         self._delete_account(p, a)).pack(side=tk.RIGHT,
                                                          padx=(3, 0))
        W.IconButton(actions, "gear", size=30, icon_size=15,
                     bg=card_bg, hover_bg=T.HOVER, fg=T.TEXT_3,
                     tooltip="重命名",
                     command=lambda p=platform, a=account_id:
                         self._rename_account(p, a)).pack(side=tk.RIGHT,
                                                          padx=(3, 0))

    def _refresh_account_status(self):
        """侧边栏底部：登录概况 + 每平台状态点"""
        try:
            counts = self.accounts.counts()
            self.login_status.configure(text=self.accounts.summary_text())
            self.login_icon.delete("all")
            icons.draw_icon(self.login_icon, "gear", 9, 9, 16,
                            T.ACCENT_TEXT)
            for child in self.account_dots.winfo_children():
                child.destroy()
            for platform in T.PLATFORM_KEYS:
                info = counts[platform]
                canvas = tk.Canvas(self.account_dots, width=14, height=14,
                                   bg=T.SIDEBAR_HOVER, highlightthickness=0,
                                   bd=0)
                canvas.pack(side=tk.LEFT)
                color = T.platform_color(platform) if info["logged_in"] \
                    else T.BORDER
                icons.circle(canvas, 7, 7, 4, fill=color, outline=color)
                W.Tooltip(canvas, f"{T.platform_name(platform)}："
                                  + (info["label"] if info["logged_in"]
                                     else "未登录"))
        except Exception as exc:
            print("[账号] 侧边栏状态刷新失败:", exc)

    # ---------------- 账号操作 ----------------
    def _switch_account(self, platform, account_id):
        if not self.accounts.set_current(platform, account_id):
            W.Toast.show(self.root, "切换失败：账号不存在", "error")
            return
        self._persist_config()
        self._init_clients()
        self._refresh_accounts()
        account = self.accounts.get(platform, account_id)
        name = T.platform_name(platform)
        label = account.get("label", "") if account else ""
        W.Toast.show(self.root, f"已切换到 {name}：{label}", "ok", 2600)

    def _logout_account(self, platform):
        account = self.accounts.current(platform)
        if account is None:
            W.Toast.show(self.root, "这个平台本来就没登录", "info")
            return
        name = T.platform_name(platform)
        if not W.ConfirmDialog(
                self.root, "退出登录",
                f"退出 {name} 的「{account.get('label')}」？\n"
                f"账号记录会保留在列表里，随时可以再切回来。",
                ok_text="退出登录").show():
            return
        self.accounts.clear_current(platform)
        self._persist_config()
        self._init_clients()
        self._refresh_accounts()
        W.Toast.show(self.root, f"已退出 {name}", "ok")

    def _rename_account(self, platform, account_id):
        account = self.accounts.get(platform, account_id)
        if account is None:
            return
        label = W.PromptDialog(
            self.root, "重命名账号",
            f"{T.platform_name(platform)} 的这个账号叫什么？",
            initial=account.get("label", ""), ok_text="保存").show()
        if not label or label == account.get("label"):
            return
        if self.accounts.rename(platform, account_id, label):
            self._persist_config()
            self._refresh_accounts()
            W.Toast.show(self.root, "已重命名", "ok")

    def _delete_account(self, platform, account_id):
        account = self.accounts.get(platform, account_id)
        if account is None:
            return
        name = T.platform_name(platform)
        is_current = self.accounts.current_id(platform) == account_id
        message = (f"删除 {name} 的「{account.get('label')}」？\n"
                   "只删除本地保存的登录凭据，不影响你的平台账号。")
        if is_current and len(self.accounts.accounts(platform)) > 1:
            message += "\n删除后会切到列表里的下一个账号。"
        if not W.ConfirmDialog(self.root, "删除账号", message,
                               ok_text="删除", danger=True).show():
            return
        self.accounts.remove(platform, account_id)
        self._persist_config()
        self._init_clients()
        self._refresh_accounts()
        W.Toast.show(self.root, f"已删除 {name} 的账号", "ok")

    def _persist_config(self):
        try:
            save_config(self.cfg)
        except Exception as exc:
            print("[账号] 保存配置失败:", exc)

    # ---------------- 登录对话框对接 ----------------
    def _login_save_options(self, platform):
        """告诉登录对话框：这次登录是新增还是更新已有账号"""
        account = self.accounts.current(platform)
        total = len(self.accounts.accounts(platform))
        if account:
            return {
                "mode": "update",
                "label": account.get("label", ""),
                "placeholder": f"登录成功后会覆盖「{account.get('label')}」的凭据，"
                               f"该平台已保存 {total} 个账号",
                "confirm_text": "更新当前账号",
            }
        return {
            "mode": "new",
            "label": "",
            "placeholder": f"该平台已保存 {total} 个账号；留空会自动命名",
            "confirm_text": "保存账号",
        }

    def _save_account_credential(self, platform, cred, method, label):
        """登录成功后落盘成账号，返回 (label, created)"""
        intent = getattr(self, "_login_intent", None)
        if intent and intent[0] != platform:
            intent = None

        current = self.accounts.current(platform)
        prefer_id = ""
        if intent and intent[1] == "update" and current is not None:
            prefer_id = current.get("id", "")
        # 没有指定意图时，默认「覆盖当前账号」，避免同一个账号重复堆积
        elif intent is None and current is not None:
            prefer_id = current.get("id", "")

        created = True
        if not label:
            existing = self.accounts.get(platform, prefer_id) if prefer_id \
                else self.accounts.find_by_cred(platform, cred)
            label = (existing or {}).get("label") or \
                self.accounts._default_label(platform)

        account, created = self.accounts.add(
            platform, cred, label=label, method=method, make_current=True,
            prefer_id=prefer_id)
        self._login_intent = None
        self._persist_config()
        self._init_clients()
        self._ui(self._refresh_accounts)
        return (account.get("label", "") if account else label, created)

    # ---- 通用曲目表格 ----
    def _make_tree(self, parent):
        columns = [c[0] for c in T.TRACK_COLUMNS]
        tree = tk.ttk.Treeview(parent, columns=columns, show="headings",
                               style="Tracks.Treeview", selectmode="extended")
        for col_id, title, width, minwidth, anchor, stretch in \
                [(c[0], c[1], c[2], c[3], c[4], c[5])
                 for c in T.TRACK_COLUMNS]:
            tree.heading(col_id, text=title, anchor="w" if anchor == "w" else "center")
            tree.column(col_id, width=width, minwidth=minwidth,
                        anchor=anchor, stretch=stretch)

        vsb = tk.ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview,
                               style="Modern.Vertical.TScrollbar")
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        tree.tag_configure("odd", background=T.ROW_ALT)
        tree.tag_configure("even", background=T.PANEL)
        tree.tag_configure("playing", background=T.ACCENT_SOFT,
                           foreground=T.TEXT)
        tree.tag_configure("downloaded", foreground=T.GREEN)
        tree.tag_configure("local", foreground=T.TEXT)

        tree.bind("<Double-1>", lambda e: self._play_tree_selection(tree))
        tree.bind("<Return>", lambda e: self._play_tree_selection(tree))
        tree.bind("<Button-3>", lambda e: self._tree_context_menu(e, tree))

        # 拖拽到侧边栏歌单
        tree.bind("<ButtonPress-1>", lambda e: self._tree_press(e, tree), add="+")
        tree.bind("<B1-Motion>", self._tree_drag_motion, add="+")
        tree.bind("<ButtonRelease-1>", self._tree_drag_release, add="+")
        return tree

    # ---------------- 播放条 ----------------
    def _build_playbar(self):
        bar = tk.Frame(self.root, bg=T.PLAYBAR, height=T.PLAYBAR_H)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        bar.pack_propagate(False)
        tk.Frame(bar, bg=T.BORDER_SOFT, height=1).place(x=0, y=0,
                                                        relwidth=1.0)

        # ---- 左：封面 + 信息 ----
        left = tk.Frame(bar, bg=T.PLAYBAR, width=330)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(18, 0), pady=12)
        left.pack_propagate(False)

        self.cover = tk.Canvas(left, width=58, height=58, bg=T.PLAYBAR,
                               highlightthickness=0, bd=0)
        self.cover.pack(side=tk.LEFT)
        self._draw_cover(idle=True)

        info = tk.Frame(left, bg=T.PLAYBAR)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        self.now_title = tk.Label(info, text="未在播放", bg=T.PLAYBAR,
                                  fg=T.TEXT, font=self.fonts.body_bold,
                                  anchor="w")
        self.now_title.pack(fill=tk.X, pady=(8, 0))
        self.now_artist = tk.Label(info, text="从左侧搜索开始你的音乐", bg=T.PLAYBAR,
                                   fg=T.TEXT_3, font=self.fonts.small,
                                   anchor="w")
        self.now_artist.pack(fill=tk.X, pady=(2, 0))
        self.marquee = Marquee(self.now_title, max_px=230)

        # ---- 右：音量 + 播放模式 ----
        right = tk.Frame(bar, bg=T.PLAYBAR, width=230)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 20), pady=12)
        right.pack_propagate(False)

        right_inner = tk.Frame(right, bg=T.PLAYBAR)
        right_inner.pack(expand=True)

        self.mode_btn = W.IconButton(
            right_inner, "sequential", command=self._cycle_mode, size=32,
            icon_size=17, bg=T.PLAYBAR, hover_bg=T.ELEVATED,
            fg=T.TEXT_2)
        self.mode_btn.pack(side=tk.LEFT)
        self._mode_tip = W.Tooltip(self.mode_btn, "播放模式：顺序播放")

        self.mute_btn = W.IconButton(
            right_inner, "volume", command=self._toggle_mute, size=30,
            icon_size=16, bg=T.PLAYBAR, hover_bg=T.ELEVATED, fg=T.TEXT_2,
            tooltip="静音")
        self.mute_btn.pack(side=tk.LEFT, padx=(6, 2))

        self.volume_slider = W.VolumeSlider(
            right_inner, on_change=self._on_volume_change, bg=T.PLAYBAR,
            width=104, initial=self.player.get_volume())
        self.volume_slider.pack(side=tk.LEFT, padx=(2, 0))

        # ---- 中：控制 + 进度 ----
        center = tk.Frame(bar, bg=T.PLAYBAR)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)

        controls = tk.Frame(center, bg=T.PLAYBAR)
        controls.pack(pady=(12, 0))

        self.shuffle_btn = W.IconButton(
            controls, "shuffle", command=self._toggle_shuffle, size=32,
            icon_size=16, bg=T.PLAYBAR, hover_bg=T.ELEVATED, fg=T.TEXT_3,
            tooltip="随机播放开关")
        self.shuffle_btn.pack(side=tk.LEFT, padx=2)

        self.prev_btn = W.IconButton(
            controls, "prev", command=lambda: self.queue.previous(), size=34,
            icon_size=17, bg=T.PLAYBAR, hover_bg=T.ELEVATED, fg=T.TEXT,
            tooltip="上一首")
        self.prev_btn.pack(side=tk.LEFT, padx=2)

        self.play_btn = W.IconButton(
            controls, "play", command=self._toggle_play, size=44,
            icon_size=20, variant="solid", bg=T.PLAYBAR,
            active_bg=T.ACCENT, hover_bg=T.ACCENT_HOVER, tooltip="播放 / 暂停")
        self.play_btn.pack(side=tk.LEFT, padx=6)

        self.next_btn = W.IconButton(
            controls, "next", command=lambda: self.queue.next(), size=34,
            icon_size=17, bg=T.PLAYBAR, hover_bg=T.ELEVATED, fg=T.TEXT,
            tooltip="下一首")
        self.next_btn.pack(side=tk.LEFT, padx=2)

        self.stop_btn = W.IconButton(
            controls, "stop", command=self._stop, size=32, icon_size=15,
            bg=T.PLAYBAR, hover_bg=T.ELEVATED, fg=T.TEXT_3, tooltip="停止")
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        progress = tk.Frame(center, bg=T.PLAYBAR)
        progress.pack(fill=tk.X, padx=8, pady=(6, 0))
        self.time_now = tk.Label(progress, text="0:00", bg=T.PLAYBAR,
                                 fg=T.TEXT_3, font=self.fonts.tiny, width=5,
                                 anchor="e")
        self.time_now.pack(side=tk.LEFT)
        self.seekbar = W.SeekBar(progress, on_seek=self._on_seek,
                                 bg=T.PLAYBAR)
        self.seekbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.time_total = tk.Label(progress, text="--:--", bg=T.PLAYBAR,
                                   fg=T.TEXT_3, font=self.fonts.tiny, width=5,
                                   anchor="w")
        self.time_total.pack(side=tk.LEFT)

        # 状态提示（播放条右上角）
        self.status_label = tk.Label(bar, text="就绪", bg=T.PLAYBAR,
                                     fg=T.TEXT_3, font=self.fonts.tiny)
        self.status_label.place(relx=1.0, x=-20, y=6, anchor="ne")

    def _draw_cover(self, idle=False, pressed=None):
        """画封面占位（渐变感 + 音符图标）"""
        self.cover.delete("all")
        size = 58
        if idle:
            base = T.ELEVATED
            icons.rounded_rect(self.cover, 0, 0, size - 1, size - 1, 14,
                               fill=base, outline=base)
            icons.draw_icon(self.cover, "music", size / 2, size / 2, 24,
                            T.TEXT_3)
            return
        colors = [T.ACCENT, T.CYAN, T.ACCENT_TEXT]
        import math
        for i in range(size):
            ratio = i / float(size)
            color = T.mix(colors[pressed % len(colors)],
                          colors[(pressed + 1) % len(colors)], ratio)
            self.cover.create_line(0, i, size, i, fill=color)
        mask = T.ACCENT_SOFT
        icons.rounded_rect(self.cover, 0, 0, size - 1, size - 1, 14,
                           fill="", outline=mask)
        icons.draw_icon(self.cover, "music", size / 2, size / 2, 26,
                        "#ffffff")

    # ==================================================
    # 视图切换
    # ==================================================
    def _switch_view(self, key, record=True):
        if key == VIEW_LOGIN:
            self.open_login()
            return
        if key not in self.views:
            key = VIEW_HOME
        self._view = key
        self._hide_search_hint()
        for name, view in self.views.items():
            if name == key:
                view.pack(fill=tk.BOTH, expand=True)
            else:
                view.pack_forget()
        for name, button in self.nav_buttons.items():
            button._set_active(name == key)

        titles = {
            VIEW_HOME: ("发现音乐", "推荐歌单 · 每日推荐 · 猜你喜欢"),
            VIEW_SEARCH: ("搜索", "跨平台检索，回车即可播放"),
            VIEW_LIBRARY: ("全部音乐", "所有出现过的曲目，随搜随存"),
            VIEW_LOCAL: ("本地音乐", "已经下载到本机的音频文件"),
            VIEW_PLAYLIST: ("播放列表", ""),
            VIEW_DOWNLOAD: ("下载管理", "批量下载队列与进度"),
            VIEW_ACCOUNTS: ("账号管理", "每个平台可保存多个账号，随时切换"),
        }
        title, subtitle = titles.get(key, ("", ""))
        if key == VIEW_PLAYLIST:
            pl = self.store.get(self.store.active_id)
            title = pl["name"] if pl else "播放列表"
            subtitle = "双击播放 · 右键更多操作"
        if key == VIEW_HOME:
            self._refresh_home()
        elif key == VIEW_PLAYLIST:
            self._refresh_playlist_view()
        elif key == VIEW_LIBRARY:
            self._refresh_library()
        elif key == VIEW_LOCAL:
            self._scan_local()
        elif key == VIEW_DOWNLOAD:
            self._refresh_downloads()
        elif key == VIEW_ACCOUNTS:
            self._refresh_accounts()
        self.view_title.configure(text=title)
        self.view_subtitle.configure(text=subtitle)
        if record:
            self._push_nav(key)

    # ==================================================
    # 首页（发现音乐）
    # ==================================================
    def _load_history(self):
        """播放历史（用于每日推荐 / 猜你喜欢）"""
        raw = self.cfg.get("history")
        if not isinstance(raw, list):
            return []
        tracks = []
        for item in raw:
            if (isinstance(item, dict) and item.get("id")
                    and item.get("platform")):
                tracks.append(item)
        return tracks[:300]

    def _remember_play(self, track):
        """把播过的曲目记到历史里（去重放最前）"""
        if not track or not track.get("id"):
            return
        key = tray.track_key(track)
        self.play_history = [t for t in self.play_history
                             if tray.track_key(t) != key]
        self.play_history.insert(0, dict(track))
        del self.play_history[300:]
        self.cfg["history"] = self.play_history
        self._save_config_soon()

    # ---------------- 分类内容 ----------------
    def _open_category(self, key):
        library = self._library_tracks()
        if key == "daily":
            tracks = FEED.build_daily(library, self.play_history)
            source = "每日推荐 · " + FEED.daily_title()
        elif key == "guess":
            tracks = FEED.build_guess(library, self.play_history, None)
            source = "猜你喜欢"
        elif key == "recent":
            tracks = FEED.build_recent(self.play_history)
            source = "最近播放"
        elif key == "bili":
            tracks = [t for t in library if t.get("platform") == "bilibili"]
            source = "B站精选"
        elif key == "instrumental":
            tracks = [t for t in library
                      if "纯音乐" in (t.get("title") or "")
                      or "钢琴" in (t.get("title") or "")
                      or "钢琴" in (t.get("album") or "")]
            source = "纯音乐"
        else:
            tracks, source = [], key

        if not tracks:
            W.Toast.show(self.root,
                         "这个分类还没有内容 —— 先去搜索一些歌，"
                         "或者登录账号后让推荐更准", "info", 3600)
            return
        self._show_track_list(source, tracks,
                              f"{len(tracks)} 首 · 来自你的音乐库")

    def _show_track_list(self, title, tracks, subtitle=""):
        """把一批曲目塞进「搜索」视图展示（复用同一张表）"""
        self._search_results = list(tracks)
        self._fill_tree(self.search_tree, self._search_results)
        self._switch_view(VIEW_SEARCH, record=False)
        self.view_title.configure(text=title)
        self.view_subtitle.configure(text=subtitle
                                     or f"{len(tracks)} 首曲目")
        W.Toast.show(self.root, f"{title}：{len(tracks)} 首，双击播放",
                     "ok", 2200)

    def _open_station(self, station):
        tracks = self.feed_cache.get_any("station::" + station["key"]) or []
        if not tracks:
            tracks = self._fetch_station_now(station)
        if not tracks:
            W.Toast.show(self.root, f"「{station['title']}」暂时取不到内容",
                         "warn")
            return
        self._show_track_list(station["title"], tracks,
                              f"{len(tracks)} 首 · {station.get('hint', '')}")

    def _fetch_station_now(self, station):
        tracks = FEED.fetch_station(station, self.clients, self._run_async)
        if tracks:
            self.feed_cache.put("station::" + station["key"], tracks)
            self.feed_cache.save()
        return tracks

    # ---------------- 首页渲染 ----------------
    def _refresh_home(self):
        if not self._ui_ready or not self._alive:
            return
        try:
            self._build_category_cards()
            self._refresh_home_grid()
            if not self._stations_loaded:
                self._stations_loaded = True
                self._load_stations()
        except Exception as exc:
            print("[首页] 刷新失败:", exc)

    def _refresh_home_grid(self):
        """猜你喜欢网格"""
        for child in self.home_grid.winfo_children():
            child.destroy()
        tracks = FEED.build_guess(self._library_tracks(), self.play_history,
                                  None, limit=10)
        if not tracks:
            tracks = self._library_tracks()[:10]
        if not tracks:
            tk.Label(self.home_grid,
                     text="还没有曲目。搜索几首歌之后，这里会出现"
                          "根据你的口味挑选的内容。",
                     bg=T.BG, fg=T.TEXT_3, font=self.fonts.small,
                     anchor="w").pack(fill=tk.X, pady=(0, 8))
            return

        columns = 5
        for index, track in enumerate(tracks[:columns * 2]):
            row, col = divmod(index, columns)
            if col == 0:
                row_frame = tk.Frame(self.home_grid, bg=T.BG)
                row_frame.pack(fill=tk.X, pady=(0, 12))
            card = CARD.BigCard(
                row_frame, title=tray.track_title(track),
                subtitle=tray.track_artist(track) or
                T.platform_name(tray.track_platform(track)),
                url=track.get("cover") or "",
                seed=f"{tray.track_title(track)}{tray.track_artist(track)}",
                size=150, cache=self.cover_cache, bg=T.BG,
                command=lambda t=track: self._play_from_home(t))
            card.pack(side=tk.LEFT, padx=(0, 16))

    def _play_from_home(self, track):
        items = self._library_tracks() or [track]
        try:
            start = items.index(track)
        except ValueError:
            start = 0
        self._play_list(items, "猜你喜欢", start)

    def _load_stations(self):
        """后台抓推荐歌单（有缓存就先用缓存）"""
        stations = FEED.FEED_STATIONS
        self._stations = stations

        cached_any = False
        for station in stations:
            tracks = self.feed_cache.get("station::" + station["key"])
            if tracks:
                self._render_station(station, tracks)
                cached_any = True
            else:
                stale = self.feed_cache.get_any("station::" + station["key"])
                if stale:
                    self._render_station(station, stale)
                    cached_any = True
        if cached_any:
            return
        threading.Thread(target=self._stations_worker, daemon=True,
                         name="feed-stations").start()

    def _stations_worker(self):
        """首次启动时联网抓一批（顺序抓，避免把接口打爆）"""
        for station in self._stations:
            if not self._alive:
                return
            cached = self.feed_cache.get("station::" + station["key"])
            if cached:
                continue
            tracks = FEED.fetch_station(station, self.clients,
                                        self._run_async, limit=18)
            if tracks:
                self.feed_cache.put("station::" + station["key"], tracks)
                self.feed_cache.save()
                self._ui(lambda s=station, t=tracks: self._render_station(s, t))

    def _render_station(self, station, tracks):
        if not self._alive:
            return
        try:
            for card in self.station_row.cards:
                if getattr(card, "station_key", None) == station["key"]:
                    return
            card = CARD.BigCard(
                self.station_row.inner, title=station["title"],
                subtitle=f"{len(tracks)} 首 · {station.get('hint', '')}",
                url=FEED.station_cover(tracks),
                seed=station["title"] + station["key"],
                badge=CARD.make_badge_count(FEED.fake_play_count(
                    station["title"])),
                size=148, cache=self.cover_cache, bg=T.BG,
                command=lambda s=station: self._open_station(s))
            card.station_key = station["key"]
            self.station_row.add(card)
        except Exception as exc:
            print("[首页] 渲染推荐歌单失败:", exc)

    # ==================================================
    # 本地音乐
    # ==================================================
    def _repair_local(self):
        """扫描并修复被早期版本写坏标签的音频文件"""
        directory = self.downloads.directory
        if not directory or not os.path.isdir(directory):
            W.Toast.show(self.root, "下载目录不存在", "warn")
            return
        if not W.ConfirmDialog(
                self.root, "修复音频文件",
                f"将扫描 {directory}，把早期版本误写 ID3 标签而损坏的文件"
                f"（B站 fMP4 音频）恢复成正确的 .m4a。\n\n"
                f"原文件会改名成 .broken 保留，确认没问题后可以自己删。",
                ok_text="开始修复").show():
            return

        W.Toast.show(self.root, "正在扫描并修复…", "info", 2600)
        self.view_subtitle.configure(text="正在扫描文件…")

        def worker():
            try:
                import repair
                result = repair.scan_and_repair(directory)
                self._ui(lambda: self._after_repair(result))
            except Exception as exc:
                import traceback
                traceback.print_exc()
                self._ui(lambda: W.Toast.show(
                    self.root, f"修复出错：{exc}", "error", 4200))
        threading.Thread(target=worker, daemon=True,
                         name="repair-scan").start()

    def _after_repair(self, result):
        fixed = result.get("fixed") or []
        failed = result.get("failed") or []
        scanned = result.get("scanned") or 0
        self._scan_local()
        if fixed:
            message = f"已修复 {len(fixed)} 个文件"
            if failed:
                message += f"，{len(failed)} 个失败"
            W.Toast.show(self.root, message, "ok", 4600)
        elif failed:
            W.Toast.show(self.root,
                         f"有 {len(failed)} 个文件修复失败（可能被占用或权限不足）",
                         "warn", 4600)
        else:
            W.Toast.show(self.root,
                         f"扫描了 {scanned} 个文件，都很正常，不需要修复",
                         "ok", 3600)

    def _local_tracks(self):
        """从下载目录里扫出来的本地文件"""
        return list(getattr(self, "_local_tracks_cache", []))

    def _scan_local(self):
        """扫描下载目录 + 歌单里已标记的本地文件"""
        found = {}
        directory = self.downloads.directory
        exts = (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac", ".opus")
        try:
            for root, _dirs, files in os.walk(directory):
                for name in files:
                    if not name.lower().endswith(exts):
                        continue
                    path = os.path.join(root, name)
                    key = "local::" + name
                    found[key] = {
                        "platform": "local", "id": path,
                        "title": os.path.splitext(name)[0],
                        "artists": "", "album": os.path.basename(root),
                        "duration": 0, "local_path": path,
                        "added_at": int(os.path.getmtime(path))
                        if os.path.exists(path) else 0,
                    }
        except Exception as exc:
            print("[本地音乐] 扫描失败:", exc)

        # 歌单里标记过 local_path 的也一起算上
        for playlist in self.store.playlists:
            for track in playlist.get("tracks", []):
                if tray.track_has_local(track):
                    path = track.get("local_path")
                    found.setdefault("local::" + os.path.basename(path),
                                     dict(track))

        self._local_tracks_cache = sorted(
            found.values(), key=lambda t: t.get("added_at") or 0,
            reverse=True)
        self._local_cache = {}
        for iid in self.local_tree.get_children():
            self.local_tree.delete(iid)
        for position, track in enumerate(self._local_tracks_cache):
            iid = self._insert_track(self.local_tree, track, position)
            self._local_cache[iid] = track
        if hasattr(self, "local_summary"):
            size = len(self._local_tracks_cache)
            self.local_summary.configure(
                text=f"{directory}　共 {size} 个音频文件")
        if self._view == VIEW_LOCAL:
            self.view_subtitle.configure(
                text=f"{len(self._local_tracks_cache)} 个文件")

    # ==================================================
    # 浏览历史（前进 / 后退）
    # ==================================================
    def _push_nav(self, key):
        if self._nav_pos >= 0 and self._nav_pos < len(self._nav_stack):
            if self._nav_stack[self._nav_pos] == key:
                return
        self._nav_stack = self._nav_stack[: self._nav_pos + 1]
        self._nav_stack.append(key)
        if len(self._nav_stack) > 40:
            self._nav_stack.pop(0)
        self._nav_pos = len(self._nav_stack) - 1

    def _nav_back(self):
        if self._nav_pos > 0:
            self._nav_pos -= 1
            self._switch_view(self._nav_stack[self._nav_pos], record=False)

    def _nav_forward(self):
        if self._nav_pos < len(self._nav_stack) - 1:
            self._nav_pos += 1
            self._switch_view(self._nav_stack[self._nav_pos], record=False)

    # ==================================================
    # 设置 / 更新
    # ==================================================
    def open_settings(self):
        try:
            from settings_dialog import SettingsDialog
        except Exception as exc:
            W.Toast.show(self.root, f"设置模块加载失败: {exc}", "error")
            return
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.lift()
                return
            except Exception:
                self._settings_dialog = None
        try:
            self._settings_dialog = SettingsDialog(self.root, self)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            W.Toast.show(self.root, f"打开设置失败: {exc}", "error")

    def _maybe_check_update(self):
        """启动时按间隔自动检查更新"""
        if not updater.should_check(self.app_cfg):
            return
        source = (self.app_cfg.get("update_source") or "").strip()
        if not source:
            return

        def done(info):
            self.app_cfg = updater.mark_checked(self.app_cfg)
            self._save_config_soon()
            if info.has_update:
                self._ui(lambda: self._notify_update(info))

        updater.check_async(self.version, source,
                            enabled=bool(self.app_cfg.get("auto_update", True)),
                            callback=done)

    def _notify_update(self, info):
        if not self._alive:
            return
        W.Toast.show(self.root,
                     f"发现新版本 {info.latest}（当前 {self.version}），"
                     f"点顶部齿轮 → 设置 里可更新", "info", 6000)

    # ==================================================
    # 搜索
    # ==================================================
    def do_search(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            W.Toast.show(self.root, "请输入搜索关键词", "warn")
            return
        self.clear_results()
        self._search_token += 1
        token = self._search_token
        platform_label = self.platform_select.get()
        self.view_subtitle.configure(text=f"正在搜索「{keyword}」…")
        threading.Thread(target=self._search_worker,
                         args=(token, platform_label, keyword),
                         daemon=True, name="search").start()

    def _search_worker(self, token, platform_label, keyword):
        mapping = {"全部": T.PLATFORM_KEYS}
        for key in T.PLATFORM_KEYS:
            mapping[T.platform_name(key)] = [key]
        wanted = mapping.get(platform_label, T.PLATFORM_KEYS)

        results = {}
        errors = {}
        for platform in wanted:
            if token != self._search_token:
                return
            client = self.clients.get(platform)
            if client is None:
                results[platform] = []
                errors[platform] = "客户端未初始化"
                continue
            try:
                if platform == "netease":
                    raw = client.search(keyword, 12)
                elif platform == "qqmusic":
                    raw = self._run_async(client.search(keyword, 12))
                elif platform == "kugou":
                    raw = client.search(keyword, 12)
                elif platform == "qishui":
                    raw = client.search(keyword, 12)
                elif platform == "bilibili":
                    raw = self._run_async(client.search_videos(keyword, 12))
                else:
                    raw = []
                results[platform] = [tray.make_track(platform, item)
                                     for item in (raw or [])]
            except Exception as exc:
                print(f"[{platform}] 搜索失败: {exc}")
                results[platform] = []
                errors[platform] = str(exc)

        if token != self._search_token:
            return          # 已被更新的搜索取代
        self._ui(lambda: self._display_results(results, errors, keyword))

    @staticmethod
    def _run_async(coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _display_results(self, results, errors, keyword):
        total = 0
        self._search_results = []
        for platform in T.PLATFORM_KEYS:
            for track in results.get(platform, []):
                self._search_results.append(track)
                total += 1

        self._fill_tree(self.search_tree, self._search_results)
        self._add_to_library(self._search_results)

        failed = [T.platform_name(k) for k, v in errors.items() if v]
        subtitle = f"「{keyword}」共 {total} 条结果"
        if failed:
            subtitle += f" · {', '.join(failed)} 暂无结果"
        self.view_subtitle.configure(text=subtitle)
        if total == 0:
            W.Toast.show(self.root, "没有搜到结果，换个关键词或检查登录状态", "warn")
        else:
            W.Toast.show(self.root, f"搜索完成，共 {total} 条结果", "ok")

    def clear_results(self):
        self._search_results = []
        self._fill_tree(self.search_tree, [])
        self.view_subtitle.configure(text="")

    # ==================================================
    # 曲目表格
    # ==================================================
    def _fill_tree(self, tree, tracks, highlight_key=None):
        for iid in tree.get_children():
            tree.delete(iid)
        if tree is self.search_tree:
            self._item_data.clear()

        for position, track in enumerate(tracks):
            iid = self._insert_track(tree, track, position,
                                     highlight_key=highlight_key)
            if tree is self.search_tree:
                self._item_data[iid] = (track, position)

    def _insert_track(self, tree, track, position, highlight_key=None):
        key = tray.track_key(track)
        tags = []
        if highlight_key and key == highlight_key:
            tags.append("playing")
        else:
            tags.append("odd" if position % 2 else "even")
        if tray.track_has_local(track):
            tags.append("downloaded")

        duration = track.get("duration") or 0
        values = (
            position + 1,
            tray.track_title(track),
            tray.track_artist(track) or "—",
            track.get("album") or "—",
            T.platform_name(tray.track_platform(track)),
            T.format_time(duration) if duration else "--:--",
        )
        return tree.insert("", tk.END, values=values, tags=tuple(tags))

    def _tree_tracks(self, tree):
        """按当前显示顺序取出曲目"""
        if tree is self.search_tree:
            return list(self._search_results)
        if tree is self.library_tree:
            return self._tree_order(tree, self._library_cache)
        if tree is self.playlist_tree:
            return self._playlist_tracks
        if tree is self.local_tree:
            return list(self._local_tracks_cache)
        return []

    @staticmethod
    def _tree_order(tree, cache):
        result = []
        for iid in tree.get_children():
            item = cache.get(iid)
            if item:
                result.append(item)
        return result

    def _selected_tracks(self, tree):
        tracks = self._tree_tracks(tree)
        result = []
        for iid in tree.selection():
            try:
                index = tree.index(iid)
            except Exception:
                continue
            if 0 <= index < len(tracks):
                result.append(tracks[index])
        return result

    # ==================================================
    # 播放
    # ==================================================
    def _play_tree_selection(self, tree):
        tracks = self._tree_tracks(tree)
        if not tracks:
            W.Toast.show(self.root, "列表是空的", "warn")
            return
        selection = tree.selection()
        start = tree.index(selection[0]) if selection else 0
        source = {self.search_tree: "搜索结果",
                  self.library_tree: "全部音乐",
                  self.playlist_tree: self._active_playlist_name()}.get(tree, "")
        self._play_list(tracks, source, start)

    def _play_list(self, tracks, source="", start=0, shuffle=False):
        if not tracks:
            W.Toast.show(self.root, "没有可播放的曲目", "warn")
            return
        if shuffle:
            self.queue.set_mode(MODE_SHUFFLE)
            self._update_mode_button()
        self.queue.load(tracks, start_index=start, source_name=source)

    def _toggle_play(self):
        if self._current_track is None:
            # 没在播 → 播放当前视图的第一首
            tree = self._visible_tree()
            if tree is not None:
                tracks = self._tree_tracks(tree)
                if tracks:
                    self._play_list(tracks, self._view_source_name())
                    return
            W.Toast.show(self.root, "先在列表里选一首歌吧", "info")
            return
        state = self.player.get_state()
        if state["playing"]:
            self.queue.toggle_pause()
        elif state["paused"]:
            self.queue.resume()
        else:
            self.queue.play_at(self._current_index, reason="resume")

    def _visible_tree(self):
        return {
            VIEW_SEARCH: self.search_tree,
            VIEW_LIBRARY: self.library_tree,
            VIEW_PLAYLIST: self.playlist_tree,
        }.get(self._view)

    def _view_source_name(self):
        return {
            VIEW_SEARCH: "搜索结果",
            VIEW_LIBRARY: "全部音乐",
            VIEW_PLAYLIST: self._active_playlist_name(),
        }.get(self._view, "")

    def _stop(self):
        self.queue.stop(reason="user")
        self._current_track = None
        self._current_index = -1
        self.now_title.configure(text="未在播放")
        self.now_artist.configure(text="从左侧搜索开始你的音乐")
        self.marquee.set_text("未在播放")
        self._draw_cover(idle=True)
        self.seekbar.set_pos(0, enabled=False)
        self.time_now.configure(text="0:00")
        self.time_total.configure(text="--:--")
        self.status_label.configure(text="已停止")
        self._refresh_playing_tags()

    def _on_seek(self, ratio):
        self.player.seek_ratio(ratio)

    # ==================================================
    # 播放队列回调（可能来自其它线程 → 一律派发到 UI 线程）
    # ==================================================
    def _on_track_changed(self, index, track, reason):
        def apply():
            self._current_track = track
            self._current_index = index
            if track is None:
                return
            self.now_title.configure(text=tray.track_title(track))
            self.marquee.set_text(tray.track_title(track))
            artist = tray.track_artist(track)
            platform = T.platform_name(tray.track_platform(track))
            self.now_artist.configure(
                text=f"{artist} · {platform}" if artist else platform)
            self._draw_cover(pressed=index)
            self.status_label.configure(text="正在获取播放地址…")
            self._remember_play(track)
            self._refresh_playing_tags()
        self._ui(apply)

    def _on_player_state(self, state):
        def apply():
            if state == "loading" or state == "downloading":
                self.status_label.configure(text="正在缓冲…")
                self.play_btn.set_icon("pause")
                self._pause_icon_state = False
            elif isinstance(state, str) and state.startswith("downloading:"):
                percent = state.split(":", 1)[1]
                self.status_label.configure(text=f"正在缓冲 {percent}%")
            elif state == "playing":
                self.status_label.configure(text="播放中")
                self.play_btn.set_icon("pause")
                self._pause_icon_state = False
            elif state == "paused":
                self.status_label.configure(text="已暂停")
                self.play_btn.set_icon("play")
                self._pause_icon_state = True
            elif state == "stopped":
                self.status_label.configure(text="已停止")
                self.play_btn.set_icon("play")
                self._pause_icon_state = True
            elif state == "ended":
                self.status_label.configure(text="播放结束")
                self.play_btn.set_icon("play")
                self._pause_icon_state = True
                self.seekbar.set_pos(0)
                self.time_now.configure(text="0:00")
            elif state == "idle":
                self.status_label.configure(text="已停止")
            elif state == "finished":
                self.status_label.configure(text="播放结束")
                self.play_btn.set_icon("play")
                self._pause_icon_state = True
            elif isinstance(state, str) and state.startswith("error:"):
                message = state[6:]
                self.status_label.configure(text="播放失败")
                W.Toast.show(self.root, message, "error", 4200)
        self._ui(apply)

    def _on_play_error(self, message):
        def apply():
            self.status_label.configure(text="播放失败")
            W.Toast.show(self.root, message, "error", 4200)
        self._ui(apply)

    def _on_mode_changed(self, mode):
        def apply():
            self._update_mode_button()
            W.Toast.show(self.root, "播放模式：" + MODE_META[mode]["label"],
                         "info", 1600)
        self._ui(apply)

    def _on_queue_changed(self):
        self._ui(self._refresh_playing_tags)

    def _refresh_playing_tags(self):
        """给正在播放的那一行打上高亮标记"""
        if self._current_track is None:
            return
        key = tray.track_key(self._current_track)
        for tree, tracks in ((self.search_tree, self._search_results),
                             (self.library_tree, getattr(self, "_library_cache_tracks", [])),
                             (self.playlist_tree, getattr(self, "_playlist_tracks", []))):
            playing_iid = None
            for position, iid in enumerate(tree.get_children()):
                if position >= len(tracks):
                    break
                tags = list(tree.item(iid, "tags"))
                tags = [t for t in tags if t != "playing"]
                if tray.track_key(tracks[position]) == key:
                    tags.append("playing")
                    playing_iid = iid
                tree.item(iid, tags=tuple(tags))
            if playing_iid:
                try:
                    tree.see(playing_iid)
                except Exception:
                    pass
        self._refresh_playlist_rows()

    # ==================================================
    # 播放模式 / 音量
    # ==================================================
    def _cycle_mode(self):
        self.queue.cycle_mode()
        cfg = self.cfg.setdefault("app", {})
        cfg["play_mode"] = self.queue.mode
        save_config(self.cfg)

    def _toggle_shuffle(self):
        if self.queue.mode == MODE_SHUFFLE:
            self.queue.set_mode("sequential")
        else:
            self.queue.set_mode(MODE_SHUFFLE)
        self.cfg.setdefault("app", {})["play_mode"] = self.queue.mode
        save_config(self.cfg)
        self._update_mode_button()

    def _update_mode_button(self):
        mode = self.queue.mode
        meta = MODE_META[mode]
        self.mode_btn.set_icon(meta["icon"],
                               T.ACCENT_TEXT if mode != "sequential" else T.TEXT_2)
        if getattr(self, "_mode_tip", None) is not None:
            self._mode_tip.update_text(f"播放模式：{meta['label']}（点击切换）")
        if hasattr(self, "shuffle_btn"):
            active = mode == MODE_SHUFFLE
            self.shuffle_btn.set_colors(
                fg=T.ACCENT_TEXT if active else T.TEXT_3)
        # 没在播放时，状态栏显示当前模式说明
        if not self.player.get_state()["playing"]:
            self.status_label.configure(text=meta["hint"])

    def _on_volume_change(self, value):
        self.player.set_volume(value)
        self.cfg.setdefault("app", {})["volume"] = round(value, 3)
        self._update_volume_icon()
        self._save_config_soon()

    def _update_volume_icon(self):
        volume = self.player.get_volume()
        icon = "volume_mute" if volume <= 0.001 else "volume"
        self.mute_btn.set_icon(icon, T.TEXT_3 if volume <= 0.001 else T.TEXT_2)

    def _toggle_mute(self):
        volume = self.player.get_volume()
        if volume > 0.001:
            self._last_volume = volume
            self.player.set_volume(0.0)
            self.volume_slider.set_value(0.0)
        else:
            self.player.set_volume(getattr(self, "_last_volume", 0.7))
            self.volume_slider.set_value(self.player.get_volume())
        self._update_volume_icon()

    _save_after_id = None

    def _save_config_soon(self):
        if self._save_after_id:
            try:
                self.root.after_cancel(self._save_after_id)
            except Exception:
                pass
        self._save_after_id = self.root.after(900, lambda: save_config(self.cfg))

    # ==================================================
    # 定时刷新
    # ==================================================
    def _tick_ui(self):
        if not self._alive:
            return
        try:
            # 窗口被外部销毁（比如被别的代码 destroy 掉）时自己停下来，
            # 否则 after 回调会一直报 invalid command name
            if not self.root.winfo_exists():
                self._alive = False
                return
        except Exception:
            self._alive = False
            return
        try:
            self._drain_ui_queue()
            self._drain_covers()
            state = self.player.get_state()
            if state["playing"]:
                position = state["position"]
                duration = state["duration"]
                self.time_now.configure(text=T.format_time(position))
                self.time_total.configure(text=T.format_time(duration))
                self.seekbar.set_pos(position / duration if duration > 0 else 0,
                                     enabled=duration > 0)
            elif state["paused"]:
                self.seekbar.set_pos(
                    state["position"] / state["duration"]
                    if state["duration"] > 0 else 0, enabled=True)

            if state["loading"]:
                self._loading_pulse = (self._loading_pulse + 1) % 3
                self._draw_cover(pressed=self._loading_pulse)
        except Exception as exc:
            print("[UI] 刷新异常:", exc)
        finally:
            if self._alive:
                try:
                    self.root.after(250, self._tick_ui)
                except Exception:
                    self._alive = False

    def _drain_covers(self):
        """把下载好的封面转成图片并重绘对应控件"""
        try:
            count = self.cover_cache.drain()
        except Exception:
            return
        if not count:
            return
        if self._view == VIEW_HOME:
            self._refresh_home_covers()

    def _refresh_home_covers(self):
        """首页卡片封面下好后重画一遍"""
        try:
            for card in list(self.category_row.cards) + \
                    list(self.station_row.cards):
                art = getattr(card, "art", None)
                if art is not None:
                    art._redraw()
            for row in self.home_grid.winfo_children():
                for card in row.winfo_children():
                    art = getattr(card, "art", None)
                    if art is not None:
                        art._redraw()
        except Exception as exc:
            print("[首页] 封面刷新失败:", exc)

    def _on_downloads_changed(self):
        self._ui(self._refresh_downloads)

    # ==================================================
    # 下载
    # ==================================================
    def resolve_url(self, track):
        """给下载器用的直链解析（在工作线程里执行）"""
        from play_queue import resolve_play_url
        url = resolve_play_url(track.get("platform"), track, self.clients)
        if not url:
            raise RuntimeError("该平台没有返回可下载的地址")
        return url

    def _download_tracks(self, tracks, playlist_id=""):
        if not tracks:
            W.Toast.show(self.root, "没有可下载的曲目", "warn")
            return
        created = self.downloads.enqueue(tracks, playlist_id=playlist_id)
        if not created:
            W.Toast.show(self.root, "这些曲目已经在下载队列里了", "info")
            return
        W.Toast.show(self.root,
                     f"已加入 {len(created)} 首到下载队列", "ok")
        self._switch_view(VIEW_DOWNLOAD)

    def _download_active_playlist(self):
        pl = self.store.get(self.store.active_id)
        if not pl or not pl["tracks"]:
            W.Toast.show(self.root, "这个歌单还是空的", "warn")
            return
        self._download_tracks(pl["tracks"], playlist_id=pl["id"])

    def _choose_download_dir(self):
        path = filedialog.askdirectory(title="选择下载目录",
                                       initialdir=self.downloads.directory)
        if not path:
            return
        if self.downloads.set_directory(path):
            self.cfg.setdefault("app", {})["download_dir"] = path
            save_config(self.cfg)
            self._refresh_downloads()
            W.Toast.show(self.root, "下载目录已更新", "ok")
        else:
            W.Toast.show(self.root, "该目录不可用", "error")

    def _open_download_dir(self):
        path = self.downloads.directory
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(path)          # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            W.Toast.show(self.root, f"打开目录失败: {exc}", "error")

    def _open_task_folder(self, task):
        if not task.path:
            return
        folder = os.path.dirname(task.path)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(task.path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", task.path])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            self._open_download_dir()

    def _play_task(self, task):
        """播放某个已下载完成的文件"""
        if not (task.path and os.path.exists(task.path)):
            W.Toast.show(self.root, "文件不存在或已被移动", "warn")
            return
        track = dict(task.track)
        track["local_path"] = task.path
        # 队列为空时才新建队列，避免打断当前正在播放的歌单
        items = self.queue.items or [track]
        self.queue.play_track(track, items=items, source_name="下载文件")

    def _clear_finished_downloads(self):
        self.downloads.clear_finished()
        self._refresh_downloads()

    def _refresh_downloads(self):
        if not self._ui_ready or not self._alive:
            return
        try:
            self.dl_dir_label.configure(text=f"保存到：{self.downloads.directory}")
            stats = self.downloads.stats()
            summary = (f"共 {stats['total']} 项 · 完成 {stats['done']} · "
                       f"进行中 {stats['pending']} · 失败 {stats['failed']}")
            self.dl_summary.configure(text=summary)

            tasks = self.downloads.tasks
            existing = set(self._download_rows.keys())
            current = {t.uid for t in tasks}

            for uid in existing - current:
                row = self._download_rows.pop(uid, None)
                if row is not None:
                    row.destroy()

            if self.dl_empty.winfo_exists():
                if tasks:
                    self.dl_empty.pack_forget()
                else:
                    self.dl_empty.pack(pady=60)

            for index, task in enumerate(tasks):
                row = self._download_rows.get(task.uid)
                if row is None:
                    row = DownloadRow(
                        self.dl_inner, task,
                        on_retry=self._retry_download,
                        on_cancel=self._cancel_download,
                        on_remove=self._remove_download,
                        on_open=self._open_task_folder)
                    row.on_play = self._play_task
                    row.pack(fill=tk.X, padx=8, pady=(6 if index == 0 else 2, 2))
                    row._index = index
                    self._download_rows[task.uid] = row
                else:
                    row._redraw()
        except Exception as exc:
            print("[下载] 刷新失败:", exc)

    def _retry_download(self, task):
        self.downloads.retry(task)

    def _cancel_download(self, task):
        self.downloads.cancel(task)

    def _remove_download(self, task):
        self.downloads.remove(task)

    # ==================================================
    # 播放列表
    # ==================================================
    def _refresh_playlists(self):
        for row in self._playlist_rows:
            row.destroy()
        self._playlist_rows = []

        playlists = self.store.playlists
        active = self.store.active_id
        if not playlists:
            hint = tk.Label(self.playlist_box,
                            text="还没有歌单\n点右上角 ＋ 新建",
                            bg=T.SIDEBAR, fg=T.TEXT_3,
                            font=self.fonts.tiny, justify=tk.LEFT)
            hint.pack(anchor="w", padx=12, pady=6)
            self._playlist_rows.append(hint)
            return

        for playlist in playlists:
            row = PlaylistRow(
                self.playlist_box, playlist,
                on_select=self._select_playlist,
                on_menu=self._playlist_menu,
                on_rename=self._rename_playlist,
                active=(playlist["id"] == active))
            row.pack(fill=tk.X, padx=4, pady=2)
            self._playlist_rows.append(row)

    def _refresh_playlist_rows(self):
        for row in self._playlist_rows:
            if isinstance(row, PlaylistRow):
                row._redraw()

    def _active_playlist(self):
        return self.store.get(self.store.active_id)

    def _active_playlist_name(self):
        pl = self._active_playlist()
        return pl["name"] if pl else "播放列表"

    def _select_playlist(self, playlist):
        self.store.set_active(playlist["id"])
        self._refresh_playlists()
        self._refresh_playlist_view()
        self._switch_view(VIEW_PLAYLIST)

    def _create_playlist(self, tracks=None):
        name = W.PromptDialog(self.root, "新建播放列表",
                              "给这个播放列表起个名字：",
                              initial="我的歌单",
                              placeholder="回车确认，ESC 取消",
                              ok_text="创建").show()
        if not name:
            return None
        playlist = self.store.create(name, tracks)
        self.store.set_active(playlist["id"])
        self._refresh_playlists()
        self._refresh_playlist_view()
        self._switch_view(VIEW_PLAYLIST)
        W.Toast.show(self.root, f"已创建「{playlist['name']}」", "ok")
        return playlist

    def _rename_playlist(self, playlist):
        name = W.PromptDialog(self.root, "重命名播放列表",
                              "新的名字：", initial=playlist["name"],
                              ok_text="保存").show()
        if not name or name == playlist["name"]:
            return
        if self.store.rename(playlist["id"], name):
            self._refresh_playlists()
            self._refresh_playlist_view()
            W.Toast.show(self.root, "已重命名", "ok")
        else:
            W.Toast.show(self.root, "这个名字已经被占用了", "warn")

    def _delete_playlist(self, playlist):
        count = len(playlist.get("tracks") or [])
        if not W.ConfirmDialog(
                self.root, "删除播放列表",
                f"确定要删除「{playlist['name']}」吗？\n"
                f"其中 {count} 首曲目会从该列表移除（本地文件不受影响）。",
                ok_text="删除", danger=True).show():
            return
        self.store.delete(playlist["id"])
        self._refresh_playlists()
        if self._view == VIEW_PLAYLIST:
            self._switch_view(VIEW_LIBRARY)
        W.Toast.show(self.root, "已删除", "ok")

    def _playlist_menu(self, playlist, x, y):
        menu = tk.Menu(self.root, tearoff=0, bg=T.ELEVATED, fg=T.TEXT,
                       activebackground=T.ACCENT,
                       activeforeground=T.TEXT_ON_ACCENT, bd=0)
        menu.add_command(label="▶  播放", command=lambda: (
            self._select_playlist(playlist),
            self.root.after(60, self._play_active_playlist)))
        menu.add_command(label="🔀  随机播放", command=lambda: (
            self._select_playlist(playlist),
            self.root.after(60,
                            lambda: self._play_active_playlist(shuffle=True))))
        menu.add_separator()
        menu.add_command(label="✎  重命名",
                         command=lambda: self._rename_playlist(playlist))
        menu.add_command(label="⧉  创建副本",
                         command=lambda: self._duplicate_playlist(playlist))
        menu.add_command(label="⬇  下载整个歌单",
                         command=lambda: self._download_playlist(playlist))
        menu.add_command(label="⇩  导出 M3U",
                         command=lambda: self._export_playlist(playlist))
        menu.add_separator()
        menu.add_command(label="🗑  删除",
                         command=lambda: self._delete_playlist(playlist))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _duplicate_playlist(self, playlist):
        copy = self.store.duplicate(playlist["id"])
        if copy:
            self._refresh_playlists()
            W.Toast.show(self.root, f"已创建「{copy['name']}」", "ok")

    def _download_playlist(self, playlist):
        if not playlist.get("tracks"):
            W.Toast.show(self.root, "这个歌单还是空的", "warn")
            return
        self._download_tracks(playlist["tracks"], playlist_id=playlist["id"])

    def _export_playlist(self, playlist):
        path = filedialog.asksaveasfilename(
            title="导出播放列表", defaultextension=".m3u",
            initialfile=tray.safe_filename(playlist["name"]) + ".m3u",
            filetypes=[("M3U 播放列表", "*.m3u"), ("所有文件", "*.*")])
        if not path:
            return
        if self.store.export_m3u(playlist["id"], path):
            W.Toast.show(self.root, "已导出播放列表", "ok")
        else:
            W.Toast.show(self.root, "导出失败", "error")

    def _refresh_playlist_view(self):
        pl = self._active_playlist()
        if pl is None:
            self._playlist_tracks = []
            self._fill_tree(self.playlist_tree, [])
            self.pl_name.configure(text="播放列表")
            self.pl_meta.configure(text="还没有选中任何歌单")
            return
        self._playlist_tracks = pl["tracks"]
        self._fill_tree(self.playlist_tree, self._playlist_tracks,
                        highlight_key=tray.track_key(self._current_track)
                        if self._current_track else None)
        self.pl_name.configure(text=pl["name"])
        total = len(pl["tracks"])
        local = sum(1 for t in pl["tracks"] if tray.track_has_local(t))
        self.pl_meta.configure(
            text=f"{total} 首曲目 · 已下载 {local} 首 · 双击任意一行开始播放")
        if self._view == VIEW_PLAYLIST:
            self.view_title.configure(text=pl["name"])
            self.view_subtitle.configure(text=f"{total} 首")

    def _play_active_playlist(self, shuffle=False):
        pl = self._active_playlist()
        if pl is None or not pl["tracks"]:
            W.Toast.show(self.root, "这个歌单还是空的", "warn")
            return
        self._play_list(pl["tracks"], pl["name"], 0, shuffle=shuffle)

    def _remove_selected_from_playlist(self):
        pl = self._active_playlist()
        if pl is None:
            return
        selected = self._selected_tracks(self.playlist_tree)
        if not selected:
            W.Toast.show(self.root, "先选中要移除的曲目", "warn")
            return
        keys = [tray.track_key(t) for t in selected]
        removed = self.store.remove_tracks(pl["id"], keys)
        self._refresh_playlist_view()
        self._refresh_playlists()
        W.Toast.show(self.root, f"已移除 {removed} 首", "ok")

    # ==================================================
    # 全部音乐（曲目缓存）
    # ==================================================
    def _add_to_library(self, tracks):
        if not tracks:
            return
        if not hasattr(self, "_library"):
            self._library = {}
        for track in tracks:
            self._library.setdefault(tray.track_key(track), track)
        self._refresh_library()

    def _library_tracks(self):
        tracks = list(getattr(self, "_library", {}).values())
        platform_filter = self.library_filter.get() if hasattr(
            self, "library_filter") else "全部平台"
        if platform_filter and platform_filter != "全部平台":
            key = None
            for k in T.PLATFORM_KEYS:
                if T.platform_name(k) == platform_filter:
                    key = k
            if key:
                tracks = [t for t in tracks if t.get("platform") == key]
        tracks.sort(key=lambda t: t.get("added_at") or 0, reverse=True)
        return tracks

    def _refresh_library(self):
        if not self._ui_ready or not self._alive:
            return
        tracks = self._library_tracks()
        self._library_cache = {}
        for iid in self.library_tree.get_children():
            self.library_tree.delete(iid)
        for position, track in enumerate(tracks):
            iid = self._insert_track(self.library_tree, track, position,
                                     highlight_key=tray.track_key(
                                         self._current_track)
                                     if self._current_track else None)
            self._library_cache[iid] = track
        self._library_cache_tracks = tracks
        if self._view == VIEW_LIBRARY:
            self.view_subtitle.configure(text=f"{len(tracks)} 首曲目")

    def _shuffle_play_library(self):
        tracks = self._library_tracks()
        if not tracks:
            W.Toast.show(self.root, "还没有任何曲目", "warn")
            return
        import random
        random.shuffle(tracks)
        self._play_list(tracks, "全部音乐（随机）")

    # ==================================================
    # 表格右键菜单 / 拖拽
    # ==================================================
    def _tree_context_menu(self, event, tree):
        iid = tree.identify_row(event.y)
        if iid:
            if iid not in tree.selection():
                tree.selection_set(iid)
        tracks = self._selected_tracks(tree)
        if not tracks:
            return
        tracks = list(tracks)

        menu = tk.Menu(self.root, tearoff=0, bg=T.ELEVATED, fg=T.TEXT,
                       activebackground=T.ACCENT,
                       activeforeground=T.TEXT_ON_ACCENT, bd=0)
        menu.add_command(
            label=f"▶  播放选中的 {len(tracks)} 首",
            command=lambda: self._play_list(
                tracks, self._view_source_name(),
                self._first_selected_index(tree)))
        menu.add_command(label="🔀  随机播放选中的曲目",
                         command=lambda: self._play_list(
                             tracks, self._view_source_name(), 0, shuffle=True))
        menu.add_separator()

        add_menu = tk.Menu(menu, tearoff=0, bg=T.ELEVATED, fg=T.TEXT,
                           activebackground=T.ACCENT,
                           activeforeground=T.TEXT_ON_ACCENT, bd=0)
        for playlist in self.store.playlists:
            add_menu.add_command(
                label=playlist["name"],
                command=lambda p=playlist: self._add_tracks_to_playlist(
                    p["id"], tracks))
        add_menu.add_separator()
        add_menu.add_command(label="＋ 新建播放列表并加入",
                             command=lambda: self._create_playlist(tracks))
        menu.add_cascade(label="＋  加入播放列表", menu=add_menu)

        menu.add_command(label="⬇  下载选中的曲目",
                         command=lambda: self._download_tracks(tracks, ""))
        if tree is self.playlist_tree:
            menu.add_separator()
            menu.add_command(
                label="✖  从本歌单移除",
                command=self._remove_selected_from_playlist)
            menu.add_command(label="↑  上移", command=lambda: self._move_selected(-1))
            menu.add_command(label="↓  下移", command=lambda: self._move_selected(1))
        menu.add_separator()
        menu.add_command(label="⧉  复制「歌手 - 歌名」",
                         command=lambda: self._copy_track_text(tracks[0]))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _first_selected_index(self, tree):
        selection = tree.selection()
        if not selection:
            return 0
        try:
            return tree.index(selection[0])
        except Exception:
            return 0

    def _add_tracks_to_playlist(self, playlist_id, tracks):
        added, skipped = self.store.add_tracks(playlist_id, tracks)
        playlist = self.store.get(playlist_id)
        name = playlist["name"] if playlist else "歌单"
        if added:
            message = f"已把 {added} 首加入「{name}」"
            if skipped:
                message += f"，{skipped} 首已存在"
            W.Toast.show(self.root, message, "ok")
        else:
            W.Toast.show(self.root, f"这些曲目都已经在「{name}」里了", "info")
        self._refresh_playlists()
        if self._view == VIEW_PLAYLIST:
            self._refresh_playlist_view()

    def _copy_track_text(self, track):
        text = f"{tray.track_artist(track)} - {tray.track_title(track)}" \
            if tray.track_artist(track) else tray.track_title(track)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            W.Toast.show(self.root, "已复制到剪贴板", "ok", 1400)
        except Exception:
            pass

    def _delete_selected_tracks(self):
        """Delete 键：在歌单里移除选中曲目"""
        if self._view == VIEW_PLAYLIST:
            self._remove_selected_from_playlist()

    def _move_selected(self, delta):
        pl = self._active_playlist()
        if pl is None:
            return
        selection = self.playlist_tree.selection()
        if not selection:
            return
        index = self.playlist_tree.index(selection[0])
        new_index = self.store.move_track(pl["id"], index, delta)
        self._refresh_playlist_view()
        children = self.playlist_tree.get_children()
        if 0 <= new_index < len(children):
            self.playlist_tree.selection_set(children[new_index])
            self.playlist_tree.see(children[new_index])

    # ---------------- 拖拽加入歌单 ----------------
    def _tree_press(self, event, tree):
        self._drag_tree = tree
        self._drag_start = (event.x, event.y)

    def _tree_drag_motion(self, event):
        if self._drag_tree is None:
            return
        start = self._drag_start
        if abs(event.x - start[0]) < 14 and abs(event.y - start[1]) < 8:
            return
        self._dragging = True
        self._highlight_drop_target(event.x_root, event.y_root)

    def _highlight_drop_target(self, x_root, y_root):
        target = self._playlist_at(x_root, y_root)
        target_id = target["id"] if target else None
        if target_id == getattr(self, "_drop_target_id", None):
            return
        self._drop_target_id = target_id
        for row in self._playlist_rows:
            if isinstance(row, PlaylistRow):
                drop = target is not None and row.playlist is target
                if row._drop == drop and not drop:
                    continue
                row._drop = drop
                row._redraw()

    def _playlist_at(self, x_root, y_root):
        for row in self._playlist_rows:
            if not isinstance(row, PlaylistRow):
                continue
            try:
                x1 = row.winfo_rootx()
                y1 = row.winfo_rooty()
                if x1 <= x_root <= x1 + row.winfo_width() and \
                        y1 <= y_root <= y1 + row.winfo_height():
                    return row.playlist
            except Exception:
                continue
        return None

    def _tree_drag_release(self, event):
        tree = self._drag_tree
        dragging = self._dragging
        self._drag_tree = None
        self._dragging = False
        self._drop_target_id = None
        for row in self._playlist_rows:
            if isinstance(row, PlaylistRow):
                row._drop = False
                row._hover = False
                row._redraw()
        if not dragging or tree is None:
            return
        target = self._playlist_at(event.x_root, event.y_root)
        if target is None:
            return
        tracks = self._selected_tracks(tree)
        if tracks:
            self._add_tracks_to_playlist(target["id"], list(tracks))

    # ==================================================
    # 登录
    # ==================================================
    def open_login(self, platform=None, mode="auto"):
        """打开登录窗口

        platform 指定时直接跳到该平台页；
        mode="new" 时把这次登录明确当作新增账号（覆盖当前账号的凭据）。
        """
        try:
            from login_dialog import LoginDialog
        except Exception as exc:
            W.Toast.show(self.root, f"登录模块加载失败: {exc}", "error")
            return
        try:
            dialog = LoginDialog(self.root, self.cfg,
                                 on_success=self._on_login_success,
                                 save_handler=self._save_account_credential,
                                 accounts=self.accounts)
            self._login_dialog = dialog
            if platform:
                # 记录这次登录的意图，保存时按它决定新增还是覆盖
                self._login_intent = (platform, mode)
                for index, (key, _label) in enumerate(LoginDialog.PLATFORMS):
                    if key == platform:
                        try:
                            dialog.notebook.select(index)
                            dialog._current_platform = platform
                            dialog._refresh_current_label()
                        except Exception:
                            pass
                        break
            else:
                self._login_intent = None
        except Exception as exc:
            import traceback
            traceback.print_exc()
            W.Toast.show(self.root, f"打开登录窗口失败: {exc}", "error")

    def _on_login_success(self, platform):
        """登录对话框保存完账号后回调（此时凭据已入库、客户端已重建）"""
        def apply():
            self._refresh_accounts()
            account = self.accounts.current(platform)
            name = T.platform_name(platform)
            label = account.get("label", "") if account else ""
            W.Toast.show(self.root, f"{name} 已登录：{label}", "ok", 2800)
        self._ui(apply)

    # ==================================================
    # 键盘 / 生命周期
    # ==================================================
    def _on_space(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Entry, tk.Text)):
            return
        self._toggle_play()

    def _focus_search(self):
        self._switch_view(VIEW_SEARCH)
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)

    def _ui(self, fn):
        """把回调从工作线程安全地交给 UI 线程

        这里用队列而不是 root.after()：tkinter 的 after 从子线程调用时，
        如果主线程还没进入 mainloop 就会报 "main thread is not in main loop"。
        主线程的 _tick_ui 每 250ms 排空一次队列，响应足够快。
        """
        try:
            self._ui_queue.put(fn)
        except Exception:
            pass

    def _drain_ui_queue(self, limit=60):
        for _ in range(limit):
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            except Exception:
                return
            if not self._alive:
                return
            try:
                fn()
            except Exception as exc:
                import traceback
                print("[UI] 回调异常:", exc)
                traceback.print_exc()

    def on_close(self):
        self._alive = False
        try:
            self.queue.stop()
        except Exception:
            pass
        try:
            self.marquee.stop()
        except Exception:
            pass
        try:
            cfg = self.cfg.setdefault("app", {})
            cfg["volume"] = round(self.player.get_volume(), 3)
            cfg["play_mode"] = self.queue.mode
            save_config(self.cfg)
            self.store.save()
            self.feed_cache.save()
        except Exception:
            pass
        try:
            self.player.shutdown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    try:
        app = PlayerApp(root)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        try:
            messagebox.showerror("启动失败", f"程序启动出错：\n{exc}")
        except Exception:
            pass
        raise
    root.mainloop()
    return app


if __name__ == "__main__":
    main()
