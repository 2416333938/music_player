"""
多平台音乐播放器 —— Tkinter GUI 完整版
支持：网易云 / QQ音乐 / 酷狗 / 汽水音乐 / B站音频
功能：跨平台搜索、播放、暂停/继续/停止、音量调节、GUI 登录（扫码/Cookie/手机号）
"""

import asyncio
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config import load_config, save_config
from platforms.netease import NeteaseClient
from platforms.qqmusic import QQMusicClient
from platforms.kugou import KugouClient
from platforms.qishui import QishuiClient
from platforms.bilibili import BilibiliClient
from player import MusicPlayer
from login_dialog import LoginDialog


# ============================================================
# 平台名称映射
# ============================================================
PLATFORM_NAMES = {
    "netease": "网易云",
    "qqmusic": "QQ音乐",
    "kugou": "酷狗",
    "qishui": "汽水音乐",
    "bilibili": "B站",
}

PLATFORM_KEYS = list(PLATFORM_NAMES.keys())


# ============================================================
# 工具函数
# ============================================================
def run_async(coro):
    """在独立事件循环中同步运行一个协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# 主界面
# ============================================================
class MusicAppGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🎵 多平台音乐播放器")
        self.root.geometry("1000x680")
        self.root.minsize(820, 540)

        # 数据
        self.cfg = load_config()
        self.player = MusicPlayer()
        self.clients = {}
        self._item_data = {}          # treeview iid -> (platform, item)
        self._search_token = 0        # 防止旧搜索覆盖新搜索

        self._init_clients()
        self._build_ui()
        self._apply_volume(self.volume_var.get())

    # ============================================================
    # 初始化客户端
    # ============================================================
    def _init_clients(self):
        """根据当前 cfg 实例化各平台客户端（登录成功后可重复调用热重载）"""
        self.clients.clear()

        # ---- 网易云 ----
        try:
            self.clients["netease"] = NeteaseClient(
                self.cfg.get("netease", {}).get("cookie") or None
            )
        except Exception as e:
            print("[网易云] 初始化失败:", e)

        # ---- QQ音乐 ----
        try:
            self.clients["qqmusic"] = QQMusicClient(
                self.cfg.get("qqmusic", {}).get("cookie") or None
            )
        except Exception as e:
            print("[QQ音乐] 初始化失败:", e)

        # ---- 酷狗 ----
        try:
            self.clients["kugou"] = KugouClient(
                self.cfg.get("kugou", {}).get("cookie") or None
            )
        except Exception as e:
            print("[酷狗] 初始化失败:", e)

        # ---- 汽水音乐 ----
        try:
            self.clients["qishui"] = QishuiClient(
                self.cfg.get("qishui", {}).get("cookie") or None
            )
        except Exception as e:
            print("[汽水音乐] 初始化失败:", e)

        # ---- B站 ----
        try:
            self.clients["bilibili"] = BilibiliClient(
                self.cfg.get("bilibili", {}).get("sessdata"),
                self.cfg.get("bilibili", {}).get("bili_jct"),
            )
        except Exception as e:
            print("[B站] 初始化失败:", e)

    # ============================================================
    # 构建界面
    # ============================================================
    def _build_ui(self):
        # 主题
        style = ttk.Style()
        for theme in ("clam", "vista", "default"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue

        # ---------------- 顶部搜索栏 ----------------
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="平台:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)

        self.platform_combo = ttk.Combobox(
            top,
            values=["全部"] + [PLATFORM_NAMES[k] for k in PLATFORM_KEYS],
            state="readonly",
            width=10,
            font=("Microsoft YaHei", 10),
        )
        self.platform_combo.current(0)
        self.platform_combo.pack(side=tk.LEFT, padx=(4, 10))
        self.platform_combo.bind("<<ComboboxSelected>>", lambda e: None)

        self.search_entry = ttk.Entry(top, font=("Microsoft YaHei", 11))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self.search_entry.bind("<Return>", lambda e: self.do_search())

        ttk.Button(top, text="🔍 搜索", command=self.do_search).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="⚙ 登录", command=self.open_login_dialog).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(top, text="🧹 清空", command=self.clear_results).pack(side=tk.LEFT)

        # ---------------- 结果列表 ----------------
        mid = ttk.Frame(self.root, padding=(10, 0))
        mid.pack(fill=tk.BOTH, expand=True)

        columns = ("platform", "title", "artist", "album")
        self.tree = ttk.Treeview(
            mid,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=16,
        )
        self.tree.heading("platform", text="平台")
        self.tree.heading("title", text="标题")
        self.tree.heading("artist", text="歌手 / UP主")
        self.tree.heading("album", text="专辑 / BV号")

        self.tree.column("platform", width=90, anchor=tk.CENTER, stretch=False)
        self.tree.column("title", width=420, anchor=tk.W)
        self.tree.column("artist", width=210, anchor=tk.W)
        self.tree.column("album", width=240, anchor=tk.W)

        vsb = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 斑马纹
        self.tree.tag_configure("odd", background="#f7f7f7")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("bili", foreground="#cc3366")

        self.tree.bind("<Double-1>", lambda e: self.play_selected())
        self.tree.bind("<Return>", lambda e: self.play_selected())

        # ---------------- 播放控制栏 ----------------
        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill=tk.X)

        ttk.Button(bottom, text="▶ 播放", width=9,
                   command=self.play_selected).pack(side=tk.LEFT)
        ttk.Button(bottom, text="⏸ 暂停", width=9,
                   command=self.player.pause).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="⏵ 继续", width=9,
                   command=self.player.resume).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="⏹ 停止", width=9,
                   command=self._stop).pack(side=tk.LEFT, padx=4)

        ttk.Label(bottom, text="音量:").pack(side=tk.LEFT, padx=(20, 4))
        self.volume_var = tk.DoubleVar(value=70)
        self.volume_scale = ttk.Scale(
            bottom,
            from_=0,
            to=100,
            variable=self.volume_var,
            orient=tk.HORIZONTAL,
            length=180,
            command=self._apply_volume,
        )
        self.volume_scale.pack(side=tk.LEFT)

        self.volume_label = ttk.Label(bottom, text="70%", width=5)
        self.volume_label.pack(side=tk.LEFT, padx=4)

        # ---------------- 当前播放信息 ----------------
        self.now_playing_var = tk.StringVar(value="")
        now_frame = ttk.Frame(self.root, padding=(12, 4))
        now_frame.pack(fill=tk.X, side=tk.BOTTOM, before=None)
        ttk.Label(
            now_frame,
            textvariable=self.now_playing_var,
            font=("Microsoft YaHei", 10, "bold"),
            foreground="#0066cc",
            anchor=tk.W,
        ).pack(fill=tk.X)

        # ---------------- 状态栏 ----------------
        self.status_var = tk.StringVar(value="就绪 —— 双击结果即可播放")
        ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=4,
        ).pack(fill=tk.X, side=tk.BOTTOM)

    # ============================================================
    # 音量
    # ============================================================
    def _apply_volume(self, val):
        try:
            v = float(val)
        except Exception:
            v = 70.0
        self.player.set_volume(v / 100.0)
        self.volume_label.config(text=f"{int(v)}%")

    # ============================================================
    # 搜索
    # ============================================================
    def do_search(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            messagebox.showinfo("提示", "请输入搜索关键词")
            return

        self.clear_results()
        self._search_token += 1
        token = self._search_token

        platform_name = self.platform_combo.get()
        self.status_var.set(f"正在搜索: {keyword} ...")

        threading.Thread(
            target=self._search_worker,
            args=(token, platform_name, keyword),
            daemon=True,
        ).start()

    def _search_worker(self, token, platform_name, keyword):
        wanted_map = {
            "全部": PLATFORM_KEYS,
            "网易云": ["netease"],
            "QQ音乐": ["qqmusic"],
            "酷狗": ["kugou"],
            "汽水音乐": ["qishui"],
            "B站": ["bilibili"],
        }
        wanted = wanted_map.get(platform_name, ["netease"])

        results = {}
        for p in wanted:
            if token != self._search_token:
                return  # 已被新搜索取代
            try:
                client = self.clients.get(p)
                if client is None:
                    results[p] = []
                    continue

                if p == "netease":
                    results[p] = client.search(keyword, 10)
                elif p == "qqmusic":
                    results[p] = run_async(client.search(keyword, 10))
                elif p == "kugou":
                    results[p] = client.search(keyword, 10)
                elif p == "qishui":
                    results[p] = client.search(keyword, 10)
                elif p == "bilibili":
                    results[p] = run_async(client.search_videos(keyword, 10))
            except Exception as e:
                print(f"[{p}] 搜索失败: {e}")
                results[p] = []

        if token != self._search_token:
            return
        self.root.after(0, self._display_results, results)

    def _display_results(self, results):
        total = 0
        for platform, items in results.items():
            for item in items:
                if platform == "bilibili":
                    title = item.get("title", "")
                    artist = item.get("author", "")
                    album = item.get("bvid", "")
                else:
                    title = item.get("name", "")
                    artist = item.get("artists", "")
                    album = item.get("album", "")

                tag = "odd" if total % 2 == 0 else "even"
                if platform == "bilibili":
                    tag = "bili"

                iid = self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        PLATFORM_NAMES.get(platform, platform),
                        title,
                        artist,
                        album,
                    ),
                    tags=(tag,),
                )
                self._item_data[iid] = (platform, item)
                total += 1

        self.status_var.set(f"✅ 搜索完成，共 {total} 条结果")

    def clear_results(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._item_data.clear()

    # ============================================================
    # 播放
    # ============================================================
    def play_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一首歌曲 / 视频")
            return

        iid = sel[0]
        if iid not in self._item_data:
            return

        platform, item = self._item_data[iid]
        title = item.get("name") or item.get("title") or "未知"
        self.now_playing_var.set(f"🎵 加载中: {title}")
        self.status_var.set("正在获取播放地址...")

        threading.Thread(
            target=self._play_worker,
            args=(platform, item),
            daemon=True,
        ).start()

    def _play_worker(self, platform, item):
        try:
            url = None
            client = self.clients.get(platform)

            if client is None:
                self._ui(lambda: self.status_var.set("❌ 该平台客户端未初始化"))
                return

            if platform == "netease":
                url = client.get_play_url(item["id"])
            elif platform == "qqmusic":
                url = run_async(client.get_play_url(item["mid"]))
            elif platform == "kugou":
                url = client.get_play_url(item["hash"])
            elif platform == "qishui":
                url = client.get_play_url(item["id"])
            elif platform == "bilibili":
                url = run_async(client.get_audio_url(item["bvid"]))

            if not url:
                self._ui(lambda: self.status_var.set(
                    "❌ 无法获取播放地址（可能需要在「⚙ 登录」中登录）"))
                self._ui(lambda: self.now_playing_var.set(""))
                return

            title = item.get("name") or item.get("title") or "未知"
            artist = item.get("artists") or item.get("author") or ""
            display = (f"🎵 正在播放: {title} - {artist}"
                       if artist else f"🎵 正在播放: {title}")

            self._ui(lambda: self.now_playing_var.set(display))
            self._ui(lambda: self.status_var.set("⬇ 正在缓冲..."))

            self.player.play_url(url, on_state_change=self._on_player_state)

        except Exception as e:
            err = str(e)
            self._ui(lambda: self.status_var.set(f"❌ 播放失败: {err}"))

    def _on_player_state(self, state):
        def update():
            if state == "downloading":
                self.status_var.set("⬇ 正在缓冲...")
            elif state == "playing":
                self.status_var.set("▶ 播放中")
            elif state == "finished":
                self.status_var.set("⏹ 播放结束")
                self.now_playing_var.set("")
            elif isinstance(state, str) and state.startswith("error:"):
                self.status_var.set(f"❌ {state[6:]}")
                self.now_playing_var.set("")
        self._ui(update)

    def _stop(self):
        self.player.stop()
        self.now_playing_var.set("")
        self.status_var.set("已停止")

    def _ui(self, fn):
        """把函数派发到 UI 线程执行"""
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    # ============================================================
    # 登录
    # ============================================================
    def open_login_dialog(self):
        LoginDialog(self.root, self.cfg, on_success=self._on_login_success)

    def _on_login_success(self, platform):
        """登录成功后热重载客户端"""
        self._init_clients()
        name = PLATFORM_NAMES.get(platform, platform)
        self.status_var.set(f"✅ {name} 登录成功，客户端已刷新")

    # ============================================================
    # 退出清理
    # ============================================================
    def on_close(self):
        try:
            self.player.stop()
        except Exception:
            pass
        self.root.destroy()


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    app = MusicAppGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()