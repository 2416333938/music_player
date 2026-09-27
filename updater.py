"""自动更新

检查逻辑：
1. 从「更新源」拉一个清单文件（JSON），拿到最新版本号、更新说明、下载地址；
2. 和当前版本比较，新的就提示；
3. 打包成 exe 时可以直接下载替换并重启；源码运行时打开下载页。

更新源格式（两种都支持）：

A. 自己的 JSON 清单（推荐）
    {
      "version": "2.1.0",
      "notes": "修了几个问题",
      "url": "https://example.com/music_player-2.1.0.zip",
      "page": "https://example.com/releases"
    }

B. GitHub Releases API 地址
    https://api.github.com/repos/用户名/仓库/releases/latest
    会自动读 tag_name / body / assets[0].browser_download_url
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

try:
    import requests
except Exception:                                   # pragma: no cover
    requests = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

DEFAULT_SOURCE = ("https://raw.githubusercontent.com/"
                  "your-name/music_player/main/version.json")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STATUS_DISABLED = "disabled"
STATUS_NO_SOURCE = "no_source"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_ERROR = "error"


# ============================================================
# 版本号
# ============================================================
def parse_version(text) -> tuple:
    """把 'v2.1.0' / '2.1' 解析成可比较的元组"""
    text = str(text or "").strip().lstrip("vV")
    parts = []
    for chunk in text.replace("-", ".").replace("_", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(candidate, current) -> bool:
    return parse_version(candidate) > parse_version(current)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ============================================================
# 检查结果
# ============================================================
class UpdateInfo:
    def __init__(self, status, current="", latest="", notes="", url="",
                 page="", error=""):
        self.status = status
        self.current = current
        self.latest = latest
        self.notes = notes
        self.url = url
        self.page = page
        self.error = error

    @property
    def has_update(self) -> bool:
        return self.status == STATUS_UPDATE_AVAILABLE

    def message(self) -> str:
        if self.status == STATUS_DISABLED:
            return "自动更新已关闭"
        if self.status == STATUS_NO_SOURCE:
            return "还没设置更新源地址"
        if self.status == STATUS_UP_TO_DATE:
            return f"已是最新版本（{self.current}）"
        if self.status == STATUS_UPDATE_AVAILABLE:
            return f"发现新版本 {self.latest}（当前 {self.current}）"
        return f"检查更新失败：{self.error or '未知错误'}"

    def as_dict(self) -> dict:
        return {"status": self.status, "current": self.current,
                "latest": self.latest, "notes": self.notes, "url": self.url,
                "page": self.page, "error": self.error}


# ============================================================
# 检查
# ============================================================
def _normalize_manifest(raw: dict) -> dict:
    """把两种更新源格式统一成 {version, notes, url, page}"""
    if not isinstance(raw, dict):
        return {}

    # GitHub Releases API
    if "tag_name" in raw or "assets" in raw:
        assets = raw.get("assets") or []
        url = ""
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name.endswith((".zip", ".exe", ".7z")):
                url = asset.get("browser_download_url") or ""
                break
        if not url and assets:
            url = assets[0].get("browser_download_url") or ""
        return {
            "version": raw.get("tag_name") or raw.get("name") or "",
            "notes": raw.get("body") or "",
            "url": url,
            "page": raw.get("html_url") or "",
        }

    version = raw.get("version") or raw.get("latest") or ""
    return {
        "version": version,
        "notes": raw.get("notes") or raw.get("changelog") or "",
        "url": raw.get("url") or raw.get("download") or "",
        "page": raw.get("page") or raw.get("homepage") or "",
    }


def _fetch_manifest(source: str, timeout=12) -> dict:
    if requests is None:
        raise RuntimeError("缺少 requests 库")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    response = requests.get(source, timeout=timeout, headers=headers)
    response.raise_for_status()
    return _normalize_manifest(response.json())


def check_for_update(current_version: str, source: str, enabled=True,
                     timeout=12) -> UpdateInfo:
    """同步检查更新（请放在工作线程里调用）"""
    if not enabled:
        return UpdateInfo(STATUS_DISABLED, current=current_version)
    source = (source or "").strip()
    if not source:
        return UpdateInfo(STATUS_NO_SOURCE, current=current_version)

    try:
        manifest = _fetch_manifest(source, timeout=timeout)
    except Exception as exc:
        return UpdateInfo(STATUS_ERROR, current=current_version,
                          error=str(exc)[:120])

    latest = manifest.get("version") or ""
    if not latest:
        return UpdateInfo(STATUS_ERROR, current=current_version,
                          error="更新源里没有 version 字段")
    if is_newer(latest, current_version):
        return UpdateInfo(STATUS_UPDATE_AVAILABLE, current=current_version,
                          latest=latest, notes=manifest.get("notes") or "",
                          url=manifest.get("url") or "",
                          page=manifest.get("page") or "")
    return UpdateInfo(STATUS_UP_TO_DATE, current=current_version,
                      latest=latest, notes=manifest.get("notes") or "",
                      page=manifest.get("page") or "")


def check_async(current_version, source, enabled=True, callback=None):
    """后台检查，结果通过 callback(UpdateInfo) 返回"""
    def worker():
        info = check_for_update(current_version, source, enabled)
        if callback:
            try:
                callback(info)
            except Exception as exc:
                print("[更新] 回调异常:", exc)

    thread = threading.Thread(target=worker, daemon=True, name="update-check")
    thread.start()
    return thread


# ============================================================
# 下载 / 安装
# ============================================================
def download(url: str, progress=None, timeout=60) -> str:
    """下载更新包，返回本地路径"""
    if requests is None:
        raise RuntimeError("缺少 requests 库")
    target_dir = os.path.join(tempfile.gettempdir(), "music_player_update")
    os.makedirs(target_dir, exist_ok=True)
    name = os.path.basename((url or "").split("?")[0]) or "update.zip"
    path = os.path.join(target_dir, name)

    response = requests.get(url, stream=True, timeout=timeout,
                            headers={"User-Agent": UA})
    response.raise_for_status()
    total = int(response.headers.get("Content-Length") or 0)
    done = 0
    with open(path, "wb") as fh:
        for chunk in response.iter_content(65536):
            if not chunk:
                continue
            fh.write(chunk)
            done += len(chunk)
            if progress and total:
                try:
                    progress(done / total, done, total)
                except Exception:
                    pass
    return path


def open_path(path: str):
    """用系统默认方式打开文件或目录"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                       # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as exc:
        print(f"[更新] 打开失败: {exc}")
        return False


def install_frozen(new_file: str, main_exe: str = "") -> bool:
    """打包成 exe 时的自替换：写一个批处理，退出后替换并重启

    源码运行时不会走到这里（会改成打开下载页）。
    """
    if not is_frozen():
        return False
    exe = main_exe or sys.executable
    script = os.path.join(tempfile.gettempdir(), "music_player_update.bat")
    try:
        with open(script, "w", encoding="gbk", errors="ignore") as fh:
            fh.write("@echo off\r\n")
            fh.write("chcp 65001 >nul\r\n")
            fh.write(":wait\r\n")
            fh.write("tasklist /FI \"PID eq %d\" 2>nul | find \"%d\" >nul\r\n"
                     % (os.getpid(), os.getpid()))
            fh.write("if not errorlevel 1 (\r\n")
            fh.write("  timeout /t 1 /nobreak >nul\r\n")
            fh.write("  goto wait\r\n")
            fh.write(")\r\n")
            fh.write(f'copy /y "{new_file}" "{exe}" >nul\r\n')
            fh.write(f'start "" "{exe}"\r\n')
            fh.write('del "%~f0"\r\n')
        subprocess.Popen(["cmd", "/c", script],
                         creationflags=CREATE_NO_WINDOW, close_fds=True)
        return True
    except Exception as exc:
        print(f"[更新] 启动更新脚本失败: {exc}")
        return False


# ============================================================
# 定时策略
# ============================================================
def should_check(app_cfg: dict, force=False) -> bool:
    """按「检查间隔」判断这次启动要不要自动检查"""
    if force:
        return True
    cfg = app_cfg or {}
    if not cfg.get("auto_update", True):
        return False
    interval_hours = float(cfg.get("update_interval_hours") or 24)
    last = float(cfg.get("last_update_check") or 0)
    return (time.time() - last) >= interval_hours * 3600


def mark_checked(app_cfg: dict):
    app_cfg["last_update_check"] = time.time()
    return app_cfg
