"""设置对话框

包含：
- 通用：下载目录、音量、播放模式
- 自动更新：开关、检查间隔、更新源、立即检查、下载/安装
- 关于：版本号、数据文件位置
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import icons
import theme as T
import updater
import widgets as W


class SettingsDialog(tk.Toplevel):
    """设置窗口（非模态，方便边看边改）"""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.cfg = app.cfg
        self.app_cfg = self.cfg.setdefault("app", {})
        self.title("设置")
        self.configure(bg=T.BG)
        self.geometry("620x660")
        self.minsize(580, 560)
        self.transient(master)

        T.apply_ttk_theme(self)
        self.fonts = T.Fonts(self)
        self._update_info = None

        self._build()
        self._refresh_update_status()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())

    # ==================================================
    # 布局
    # ==================================================
    def _build(self):
        header = tk.Frame(self, bg=T.BG)
        header.pack(fill=tk.X, padx=22, pady=(18, 8))
        tk.Label(header, text="设置", bg=T.BG, fg=T.TEXT,
                 font=self.fonts.h1).pack(side=tk.LEFT)
        W.IconButton(header, "close", command=self._close, size=30,
                     icon_size=14, bg=T.BG, hover_bg=T.HOVER,
                     fg=T.TEXT_2, tooltip="关闭").pack(side=tk.RIGHT)

        body = W.ScrollFrame(self, bg=T.BG)
        body.pack(fill=tk.BOTH, expand=True, padx=(22, 10), pady=(0, 16))
        panel = body.body
        panel.configure(bg=T.BG)

        self._section(panel, "通用")
        self._row_general_download(panel)
        self._row_general_volume(panel)
        self._row_general_mode(panel)

        self._section(panel, "自动更新")
        self._row_auto_update(panel)
        self._row_update_interval(panel)
        self._row_update_source(panel)
        self._row_update_action(panel)

        self._section(panel, "数据与关于")
        self._row_about(panel)

    def _section(self, parent, title):
        wrap = tk.Frame(parent, bg=T.BG)
        wrap.pack(fill=tk.X, pady=(16, 6))
        tk.Label(wrap, text=title, bg=T.BG, fg=T.ACCENT_TEXT,
                 font=self.fonts.small_bold).pack(side=tk.LEFT)
        line = tk.Frame(wrap, bg=T.BORDER_SOFT, height=1)
        line.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0),
                  pady=(7, 0))

    def _card(self, parent):
        card = tk.Frame(parent, bg=T.PANEL, highlightthickness=1,
                        highlightbackground=T.BORDER)
        card.pack(fill=tk.X, pady=(0, 8))
        inner = tk.Frame(card, bg=T.PANEL, padx=14, pady=12)
        inner.pack(fill=tk.X)
        return inner

    def _split_row(self, parent, title, hint="", wrap=430):
        """一行设置：左边标题+说明，右边控件；返回右侧放置控件的容器"""
        row = tk.Frame(parent, bg=T.PANEL)
        row.pack(fill=tk.X)
        row.columnconfigure(0, weight=1)

        left = tk.Frame(row, bg=T.PANEL)
        left.grid(row=0, column=0, sticky="w")
        tk.Label(left, text=title, bg=T.PANEL, fg=T.TEXT,
                 font=self.fonts.body, anchor="w").pack(fill=tk.X)
        if hint:
            tk.Label(left, text=hint, bg=T.PANEL, fg=T.TEXT_3,
                     font=self.fonts.tiny, anchor="w", justify=tk.LEFT,
                     wraplength=wrap).pack(fill=tk.X, pady=(2, 0))

        right = tk.Frame(row, bg=T.PANEL)
        right.grid(row=0, column=1, sticky="e", padx=(14, 0))
        return row, right

    def _label_block(self, parent, title, hint="", wrap=430):
        """只放标题和说明的一行"""
        row = tk.Frame(parent, bg=T.PANEL)
        row.pack(fill=tk.X)
        tk.Label(row, text=title, bg=T.PANEL, fg=T.TEXT,
                 font=self.fonts.body, anchor="w").pack(fill=tk.X)
        if hint:
            tk.Label(row, text=hint, bg=T.PANEL, fg=T.TEXT_3,
                     font=self.fonts.tiny, anchor="w", justify=tk.LEFT,
                     wraplength=wrap).pack(fill=tk.X, pady=(2, 0))
        return row

    # ---------------- 通用 ----------------
    def _row_general_download(self, parent):
        inner = self._card(parent)
        _row, right = self._split_row(
            inner, "下载目录", self.app.downloads.directory, wrap=360)
        W.PrimaryButton(right, "更换", icon="folder",
                        command=self._choose_download_dir, bg=T.ELEVATED,
                        fg=T.TEXT, panel_bg=T.PANEL,
                        min_width=84, height=30).pack()

    def _row_general_volume(self, parent):
        inner = self._card(parent)
        _row, right = self._split_row(
            inner, "默认音量", "启动时使用的音量（播放条上也能随时调）")
        self.volume_slider = W.VolumeSlider(
            right, on_change=self._on_volume, bg=T.PANEL, width=140,
            initial=self.app.player.get_volume())
        self.volume_slider.pack()

    def _row_general_mode(self, parent):
        inner = self._card(parent)
        _row, right = self._split_row(
            inner, "默认播放模式", "顺序播放 / 随机播放 / 单曲循环")
        from play_queue import MODE_META, MODE_ORDER
        labels = [MODE_META[m]["label"] for m in MODE_ORDER]
        current = MODE_META[self.app.queue.mode]["label"]
        self.mode_select = W.Dropdown(right, labels, width=120, bg=T.PANEL,
                                      initial=current,
                                      on_change=self._on_mode)
        self.mode_select.pack()

    # ---------------- 自动更新 ----------------
    def _row_auto_update(self, parent):
        inner = self._card(parent)
        _row, right = self._split_row(
            inner, "启动时自动检查更新",
            "开启后每隔一段时间自动检查一次；关掉也不会影响其他功能")
        self.auto_switch = W.Switch(
            right, value=bool(self.app_cfg.get("auto_update", True)),
            on_change=self._on_auto_update, bg=T.PANEL)
        self.auto_switch.pack()

    def _row_update_interval(self, parent):
        inner = self._card(parent)
        _row, right = self._split_row(inner, "检查间隔", "多久检查一次更新")
        options = ["每次启动", "每 6 小时", "每 12 小时", "每天", "每 3 天",
                   "每周"]
        values = [0, 6, 12, 24, 72, 168]
        hours = float(self.app_cfg.get("update_interval_hours") or 24)
        try:
            current = options[values.index(int(hours))]
        except ValueError:
            current = "每天"
        self.interval_select = W.Dropdown(
            right, options, width=130, bg=T.PANEL, initial=current,
            on_change=lambda label: self._on_interval(
                values[options.index(label)]))
        self.interval_select.pack()

    def _row_update_source(self, parent):
        inner = self._card(parent)
        self._label_block(
            inner, "更新源地址",
            "指向一个 JSON 清单，或 GitHub Releases 的 latest 接口")
        entry = tk.Entry(inner, bg=T.ELEVATED, fg=T.TEXT,
                         insertbackground=T.ACCENT, relief=tk.FLAT, bd=0,
                         font=self.fonts.small,
                         highlightthickness=1, highlightbackground=T.BORDER,
                         highlightcolor=T.ACCENT)
        entry.pack(fill=tk.X, pady=(10, 0), ipady=7, padx=1)
        source = self.app_cfg.get("update_source") or ""
        entry.insert(0, source)
        self.source_entry = entry
        entry.bind("<FocusOut>", lambda e: self._on_source(entry.get()))
        entry.bind("<Return>", lambda e: self._on_source(entry.get()))

        row = tk.Frame(inner, bg=T.PANEL)
        row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(row, text=f"默认：{updater.DEFAULT_SOURCE}",
                 bg=T.PANEL, fg=T.TEXT_3, font=self.fonts.tiny,
                 anchor="w", justify=tk.LEFT).pack(side=tk.LEFT)
        W.PrimaryButton(row, "填入默认", command=self._use_default_source,
                        bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=T.PANEL,
                        min_width=88, height=26,
                        font=self.fonts.tiny).pack(side=tk.RIGHT)

    def _row_update_action(self, parent):
        inner = self._card(parent)
        version = tk.Label(inner, text=f"当前版本 v{self.app.version}",
                           bg=T.PANEL, fg=T.TEXT_2, font=self.fonts.small,
                           anchor="w")
        version.pack(fill=tk.X)

        self.update_status = tk.Label(inner, text="", bg=T.PANEL, fg=T.TEXT_3,
                                      font=self.fonts.tiny, anchor="w",
                                      justify=tk.LEFT, wraplength=470)
        self.update_status.pack(fill=tk.X, pady=(3, 0))

        self.notes_label = tk.Label(inner, text="", bg=T.PANEL,
                                    fg=T.TEXT_2, font=self.fonts.tiny,
                                    anchor="w", justify=tk.LEFT,
                                    wraplength=470)
        self.notes_label.pack(fill=tk.X, pady=(3, 0))

        buttons = tk.Frame(inner, bg=T.PANEL)
        buttons.pack(fill=tk.X, pady=(10, 0))
        self.check_btn = W.PrimaryButton(
            buttons, "立即检查", icon="refresh", command=self.check_now,
            bg=T.ACCENT, fg=T.TEXT_ON_ACCENT, hover_bg=T.ACCENT_HOVER,
            panel_bg=T.PANEL, min_width=112, height=32)
        self.check_btn.pack(side=tk.LEFT)

        self.download_btn = W.PrimaryButton(
            buttons, "下载更新", icon="download", command=self._download_update,
            bg=T.ELEVATED, fg=T.TEXT, panel_bg=T.PANEL, min_width=112,
            height=32)
        self.download_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.download_btn.set_enabled(False)

        self.progress = tk.Label(inner, text="", bg=T.PANEL, fg=T.ACCENT_TEXT,
                                 font=self.fonts.tiny, anchor="w")
        self.progress.pack(fill=tk.X, pady=(6, 0))

    def _row_about(self, parent):
        inner = self._card(parent)
        info = tk.Frame(inner, bg=T.PANEL)
        info.pack(fill=tk.X)
        tk.Label(info, text=f"多平台音乐播放器 v{self.app.version}",
                 bg=T.PANEL, fg=T.TEXT, font=self.fonts.body_bold,
                 anchor="w").pack(fill=tk.X)
        rows = [
            ("配置文件", self.app.config_file),
            ("播放列表", self.app.playlist_file),
            ("播放缓存", self.app.cache_dir),
        ]
        for name, path in rows:
            line = tk.Frame(info, bg=T.PANEL)
            line.pack(fill=tk.X, pady=(3, 0))
            tk.Label(line, text=f"{name}：{path}", bg=T.PANEL, fg=T.TEXT_3,
                     font=self.fonts.tiny, anchor="w", justify=tk.LEFT,
                     wraplength=430).pack(side=tk.LEFT)
            W.PrimaryButton(line, "打开", command=lambda p=path: self._open(p),
                            bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=T.PANEL,
                            min_width=62, height=24,
                            font=self.fonts.tiny).pack(side=tk.RIGHT)

    # ==================================================
    # 回调
    # ==================================================
    def _choose_download_dir(self):
        path = filedialog.askdirectory(title="选择下载目录",
                                       initialdir=self.app.downloads.directory)
        if not path:
            return
        if self.app.downloads.set_directory(path):
            self.app_cfg["download_dir"] = path
            self.app._persist_config()
            self.app._refresh_downloads()
            self._reopen = True
            self.destroy()

    def _on_volume(self, value):
        self.app.player.set_volume(value)
        self.app.volume_slider.set_value(value)
        self.app_cfg["volume"] = round(value, 3)
        self.app._save_config_soon()

    def _on_mode(self, label):
        from play_queue import MODE_META, MODE_ORDER
        for mode in MODE_ORDER:
            if MODE_META[mode]["label"] == label:
                self.app.queue.set_mode(mode)
                self.app_cfg["play_mode"] = mode
                self.app._persist_config()
                self.app._update_mode_button()
                break

    def _on_auto_update(self, value):
        self.app_cfg["auto_update"] = bool(value)
        self.app._persist_config()
        self._refresh_update_status()
        W.Toast.show(self.app.root,
                     "已开启启动时自动检查更新" if value
                     else "已关闭自动检查更新", "info", 2000)

    def _on_interval(self, hours):
        self.app_cfg["update_interval_hours"] = int(hours)
        self.app._persist_config()

    def _on_source(self, text):
        self.app_cfg["update_source"] = (text or "").strip()
        self.app._persist_config()

    def _use_default_source(self):
        self.source_entry.delete(0, tk.END)
        self.source_entry.insert(0, updater.DEFAULT_SOURCE)
        self._on_source(updater.DEFAULT_SOURCE)

    def _open(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(path)                   # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("打不开", str(exc))

    # ==================================================
    # 更新检查
    # ==================================================
    def _refresh_update_status(self):
        enabled = bool(self.app_cfg.get("auto_update", True))
        source = (self.app_cfg.get("update_source") or "").strip()
        if not enabled:
            self.update_status.configure(text="自动更新已关闭", fg=T.TEXT_3)
        elif not source:
            self.update_status.configure(
                text="还没设置更新源地址 —— 填一个 JSON 清单地址就能用了",
                fg=T.AMBER)
        else:
            self.update_status.configure(
                text=f"将自动检查：{source}", fg=T.TEXT_3)

    def check_now(self):
        source = (self.app_cfg.get("update_source") or "").strip()
        if not source:
            W.Toast.show(self.root, "请先填写更新源地址", "warn")
            return
        self.check_btn.set_enabled(False)
        self.update_status.configure(text="正在检查…", fg=T.TEXT_2)
        self.notes_label.configure(text="")

        def done(info):
            self.app._ui(lambda: self._on_check_done(info))
        updater.check_async(self.app.version, source, enabled=True,
                            callback=done)

    def _on_check_done(self, info):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._update_info = info
        self.check_btn.set_enabled(True)
        colors = {
            updater.STATUS_UP_TO_DATE: T.GREEN,
            updater.STATUS_UPDATE_AVAILABLE: T.ACCENT_TEXT,
            updater.STATUS_ERROR: T.ROSE,
            updater.STATUS_NO_SOURCE: T.AMBER,
            updater.STATUS_DISABLED: T.TEXT_3,
        }
        self.update_status.configure(text=info.message(),
                                     fg=colors.get(info.status, T.TEXT_2))
        notes = (info.notes or "").strip()
        if notes:
            self.notes_label.configure(text="更新说明：" + notes[:260])
        self.download_btn.set_enabled(bool(info.url))
        if info.has_update and not info.url:
            self.notes_label.configure(
                text=(notes[:200] + "\n" if notes else "")
                + "更新源没有提供下载地址，可点「打开下载页」手动下载")
            if info.page:
                self.download_btn.set_text("打开下载页")
                self.download_btn.set_enabled(True)
        elif info.has_update:
            self.download_btn.set_text("下载更新")

    def _download_update(self):
        info = self._update_info
        if info is None:
            return
        if not info.url:
            if info.page:
                updater.open_path(info.page)
            return
        self.download_btn.set_enabled(False)
        self.progress.configure(text="开始下载…")

        def worker():
            try:
                def report(ratio, done, total):
                    self.app._ui(lambda: self.progress.configure(
                        text=f"下载中 {int(ratio * 100)}%  "
                             f"({done // 1024} / {total // 1024} KB)"))
                path = updater.download(info.url, progress=report)
                self.app._ui(lambda: self._after_download(path, info))
            except Exception as exc:
                self.app._ui(lambda: self.progress.configure(
                    text=f"下载失败：{exc}"))
                self.app._ui(lambda: self.download_btn.set_enabled(True))
        threading.Thread(target=worker, daemon=True,
                         name="update-download").start()

    def _after_download(self, path, info):
        self.progress.configure(text=f"已下载到 {path}")
        if updater.is_frozen():
            if not messagebox.askyesno(
                    "安装更新",
                    f"新版本 {info.latest} 已下载完成。\n"
                    "现在替换程序并重启吗？", parent=self):
                return
            if updater.install_frozen(path):
                W.Toast.show(self.app.root, "正在重启完成更新…", "ok")
                self.app.on_close()
            else:
                messagebox.showerror("失败", "启动更新脚本失败，请手动替换。",
                                     parent=self)
        else:
            updater.open_path(os.path.dirname(path))
            W.Toast.show(
                self.app.root,
                "已下载到临时目录。当前是源码运行，请手动解压替换。", "ok",
                4200)

    def _close(self):
        self._on_source(self.source_entry.get())
        try:
            self.app._settings_dialog = None
        except Exception:
            pass
        self.destroy()
