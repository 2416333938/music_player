"""统一音频播放器

在原来的「下载 → 本地解码播放」基础上增强：
- 支持直接播放本地文件（下载过的曲目秒开）
- 支持暂停 / 继续 / 跳转进度（seek）
- 播放结束回调 on_finished（供播放列表自动续播）
- 下载缓存：同一个 URL 只下一次，重复播放不再等待
- pygame 解不了的格式自动用 ffmpeg 转码兜底

对外接口尽量保持向后兼容：play_url(url, on_state_change=...) 仍可用。

ffmpeg 查找顺序：项目根目录（含常见子目录） → 系统 PATH。
把 ffmpeg.exe 丢在项目根目录就会被自动用上，不必配环境变量。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import pygame
import requests


def _app_dir() -> str:
    """源码运行取脚本目录；PyInstaller 打包后取 exe 所在目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CACHE_DIR = os.path.join(
    os.environ.get("TEMP") or tempfile.gettempdir(), "music_player_cache")

CACHE_LIMIT_BYTES = 900 * 1024 * 1024      # 缓存上限 900MB
CACHE_KEEP_NEWEST = 120                    # 至少保留最近 120 个文件

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac", ".opus")

# 次常用的 ffmpeg 存放位置（除了根目录，也顺手找找这些）
_FFMPEG_EXTRA_DIRS = ("bin", "ffmpeg", "ffmpeg/bin", "tools", "tools/ffmpeg",
                      "tools/ffmpeg/bin")

_FFMPEG_NAMES = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg",)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_ffmpeg_path = None          # 缓存查找结果
_ffmpeg_checked = False


def _iter_ffmpeg_candidates():
    """按优先级列出可能存在的 ffmpeg 可执行文件路径"""
    app_dir = _app_dir()
    roots = [app_dir]
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle and bundle not in roots:
        roots.append(bundle)

    for root in roots:
        for name in _FFMPEG_NAMES:
            yield os.path.join(root, name)
        for extra in _FFMPEG_EXTRA_DIRS:
            for name in _FFMPEG_NAMES:
                yield os.path.join(root, *extra.split("/"), name)

    # 根目录下形如 ffmpeg-7.1-full_build/ 的解压目录
    try:
        for entry in sorted(os.listdir(app_dir)):
            full = os.path.join(app_dir, entry)
            if not os.path.isdir(full) or not entry.lower().startswith("ffmpeg"):
                continue
            for name in _FFMPEG_NAMES:
                yield os.path.join(full, name)
                yield os.path.join(full, "bin", name)
    except Exception:
        pass


def find_ffmpeg(recheck=False):
    """返回可用的 ffmpeg 路径；找不到返回 None

    顺序：项目根目录及常见子目录 → 系统 PATH。
    结果会缓存，避免每次转码都扫目录。
    """
    global _ffmpeg_path, _ffmpeg_checked
    if _ffmpeg_checked and not recheck:
        return _ffmpeg_path

    _ffmpeg_checked = True
    _ffmpeg_path = None

    for candidate in _iter_ffmpeg_candidates():
        try:
            if os.path.isfile(candidate):
                _ffmpeg_path = candidate
                return _ffmpeg_path
        except Exception:
            continue

    # 退回系统 PATH
    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_path = found
    return _ffmpeg_path


def describe_ffmpeg() -> str:
    """给界面/日志用的一句话说明"""
    path = find_ffmpeg()
    if path:
        return f"已找到 ffmpeg：{path}"
    return ("未找到 ffmpeg。把 ffmpeg.exe 放到程序根目录即可自动启用"
            "（下载地址 https://ffmpeg.org 或 https://www.gyan.dev/ffmpeg/builds/）")


# ============================================================
# 工具
# ============================================================
def http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    return session


def _suffix_from_response(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "m4a" in ct or "mp4" in ct:
        return ".m4a"
    if "flac" in ct:
        return ".flac"
    if "wav" in ct:
        return ".wav"
    if "ogg" in ct or "opus" in ct:
        return ".ogg"
    if "aac" in ct:
        return ".aac"
    path = (url or "").split("?")[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in AUDIO_EXTS else ".mp3"


def cache_path_for(url: str, suffix: str = "") -> str:
    key = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:20]
    return os.path.join(CACHE_DIR, key + (suffix or ".bin"))


def find_cached(url: str):
    """查找该 URL 已缓存的文件"""
    try:
        key = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:20]
        if not os.path.isdir(CACHE_DIR):
            return None
        for name in os.listdir(CACHE_DIR):
            if name.startswith(key + ".") and not name.endswith(".part"):
                path = os.path.join(CACHE_DIR, name)
                if os.path.getsize(path) > 1024:
                    return path
    except Exception:
        pass
    return None


def prune_cache():
    """按体积 / 数量清理缓存目录"""
    try:
        if not os.path.isdir(CACHE_DIR):
            return
        files = []
        total = 0
        for name in os.listdir(CACHE_DIR):
            path = os.path.join(CACHE_DIR, name)
            try:
                stat = os.stat(path)
            except Exception:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        files.sort(reverse=True)          # 新的在前
        for index, (mtime, size, path) in enumerate(files):
            if index < CACHE_KEEP_NEWEST and total <= CACHE_LIMIT_BYTES:
                continue
            if index < 12:                # 最近 12 个无论如何留着
                continue
            try:
                os.unlink(path)
                total -= size
            except Exception:
                pass
            if total <= CACHE_LIMIT_BYTES and index >= CACHE_KEEP_NEWEST:
                break
    except Exception:
        pass


def convert_to_mp3(src: str, workdir: str = None):
    """用 ffmpeg 转 mp3，失败返回 None

    ffmpeg 优先用项目根目录里的那一份（见 find_ffmpeg）。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    workdir = workdir or os.path.dirname(src) or tempfile.gettempdir()
    base = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(workdir, base + ".conv.mp3")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-vn",
             "-acodec", "libmp3lame", "-q:a", "2", dst],
            check=True, timeout=300,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return dst if os.path.exists(dst) and os.path.getsize(dst) > 1024 else None
    except Exception as exc:
        print(f"[播放器] ffmpeg 转码失败: {exc}")
        return None


# ============================================================
# 播放器
# ============================================================
class MusicPlayer:
    """基于 pygame.mixer 的播放器，内部单工作线程串行处理命令"""

    def __init__(self):
        self._mixer_ok = True
        self._mixer_error = ""
        try:
            pygame.mixer.init()
        except Exception as exc:          # 没有声卡也不崩溃
            self._mixer_ok = False
            self._mixer_error = str(exc)
            print(f"[播放器] 音频设备初始化失败: {exc}")

        self._volume = 0.7
        self._lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._wake = threading.Event()    # 有新命令时唤醒工作线程
        self._pending = None              # 最新一条待执行命令
        self._generation = 0              # 每次切歌 +1，用于作废旧回调
        self._playing = False
        self._paused = False
        self._finished_emitted = False
        self._loading = False
        self._current = None              # {"url"/"path", "title", "gen"}
        self._position = 0.0              # 秒
        self._duration = 0.0              # 秒
        self._started_at = 0.0
        self._offset = 0.0
        self._local_files = []            # 由本播放器创建的临时文件

        self.on_state = None              # 回调: (state:str) -> None
        self.on_finished = None           # 回调: () -> None

        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
        except Exception:
            pass

        self._worker = threading.Thread(target=self._loop, daemon=True,
                                        name="music-player")
        # 先启动工作线程，再把缓存清理放到后台
        self._worker.start()

        threading.Thread(target=prune_cache, daemon=True).start()

    # ==================================================
    # 对外接口
    # ==================================================
    @property
    def mixer_ok(self) -> bool:
        return self._mixer_ok

    @property
    def mixer_error(self) -> str:
        return self._mixer_error

    def set_volume(self, value: float):
        """value: 0.0 ~ 1.0"""
        self._volume = max(0.0, min(1.0, float(value or 0)))
        try:
            pygame.mixer.music.set_volume(self._volume)
        except Exception:
            pass

    def get_volume(self) -> float:
        return self._volume

    def play(self, source: str, title: str = "", on_state_change=None,
             on_finished=None, is_url=None):
        """播放一首曲目

        source  ：音频 URL 或本地文件路径
        is_url  ：None 表示自动判断（含 "://" 视为 URL）
        """
        if on_state_change is not None:
            self.on_state = on_state_change
        if on_finished is not None:
            self.on_finished = on_finished

        if is_url is None:
            is_url = "://" in (source or "")
        self._submit({"action": "play", "source": source,
                      "title": title or "", "is_url": bool(is_url)})

    def play_url(self, url: str, on_state_change=None, on_finished=None):
        """向后兼容的旧接口"""
        self.play(url, on_state_change=on_state_change,
                  on_finished=on_finished, is_url=True)

    def play_file(self, path: str, on_state_change=None, on_finished=None):
        self.play(path, on_state_change=on_state_change,
                  on_finished=on_finished, is_url=False)

    def pause(self):
        if not self._playing or self._paused:
            return
        try:
            pygame.mixer.music.pause()
            self._paused = True
            self._emit("paused")
        except Exception:
            pass

    def resume(self):
        if not self._playing or not self._paused:
            return
        try:
            pygame.mixer.music.unpause()
            self._paused = False
            self._emit("playing")
        except Exception:
            pass

    def toggle_pause(self):
        if self._paused:
            self.resume()
        else:
            self.pause()
        return self._paused

    def stop(self, keep_source=False):
        """停止播放并释放资源（不动列表里的下一首）"""
        self._submit({"action": "stop"})
        if not keep_source:
            self._current = None

    def seek(self, seconds: float):
        seconds = max(0.0, float(seconds or 0))
        self._submit({"action": "seek", "seconds": seconds})

    def seek_ratio(self, ratio: float):
        with self._lock:
            duration = self._duration
        if duration > 0:
            self.seek(duration * max(0.0, min(1.0, float(ratio or 0))))

    def shutdown(self):
        """退出程序时调用：停播 + 清理临时文件"""
        try:
            self._submit({"action": "quit"})
        except Exception:
            pass
        time.sleep(0.15)
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        self._cleanup_local()

    # ---------------- 状态查询 ----------------
    def get_state(self) -> dict:
        """返回播放状态快照"""
        with self._lock:
            playing = self._playing
            paused = self._paused
            position = self._position
            duration = self._duration
            loading = self._loading
            current = dict(self._current) if self._current else None

        if playing and not paused:
            try:
                if pygame.mixer.music.get_busy():
                    position = min(
                        duration if duration > 0 else 10 ** 9,
                        self._offset + max(0.0, pygame.mixer.music.get_pos() / 1000.0),
                    )
            except Exception:
                pass

        return {
            "playing": playing,
            "paused": paused,
            "loading": loading,
            "position": max(0.0, position),
            "duration": max(0.0, duration),
            "current": current,
        }

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing and not self._paused

    # ==================================================
    # 工作线程
    # ==================================================
    def _submit(self, cmd: dict):
        """提交命令：只保留最新一条，天然实现「快速切歌不排队」

        注意：这里不能顺手把播放状态清掉——seek / pause 期间状态必须保持，
        否则界面会以为已经停止播放。
        """
        with self._cmd_lock:
            self._pending = cmd
        self._wake.set()

    def _loop(self):
        while True:
            self._wake.wait(timeout=0.12)
            self._wake.clear()

            with self._cmd_lock:
                cmd = self._pending
                self._pending = None
            if cmd is None:
                self._tick()
                continue

            action = cmd.get("action")
            try:
                if action == "play":
                    self._do_play(cmd)
                elif action == "stop":
                    self._do_stop()
                elif action == "seek":
                    self._do_seek(cmd.get("seconds", 0.0))
                elif action == "quit":
                    self._do_stop()
                    return
            except Exception as exc:
                print(f"[播放器] 命令 {action} 出错: {exc}")

    def _tick(self):
        """播放中定期检查是否播完，播完则触发一次 on_finished"""
        with self._lock:
            playing = self._playing
            paused = self._paused
            done = self._finished_emitted
        if not playing or paused or done:
            return
        try:
            busy = pygame.mixer.music.get_busy()
        except Exception:
            return
        if busy:
            return

        with self._lock:
            if self._finished_emitted:
                return
            self._finished_emitted = True
            self._playing = False
            self._paused = False
        self._emit("finished")
        callback = self.on_finished
        if callback:
            try:
                callback()
            except Exception as exc:
                print("[播放器] on_finished 回调异常:", exc)

    # ---------------- 具体动作 ----------------
    def _do_stop(self):
        with self._lock:
            self._generation += 1
            self._playing = False
            self._paused = False
            self._loading = False
            self._position = 0.0
            self._duration = 0.0
            self._offset = 0.0
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        self._cleanup_local()

    def _do_seek(self, seconds: float):
        with self._lock:
            was_playing = self._playing
            paused = self._paused
            duration = self._duration
        if not was_playing:
            return
        if duration > 0:
            seconds = min(seconds, max(0.0, duration - 0.35))
        try:
            pygame.mixer.music.play(start=max(0.0, seconds))
            if paused:
                pygame.mixer.music.pause()
            with self._lock:
                self._offset = max(0.0, seconds)
                self._position = max(0.0, seconds)
                self._finished_emitted = False
        except Exception as exc:
            print(f"[播放器] 跳转失败: {exc}")

    def _do_play(self, cmd):
        source = cmd.get("source") or ""
        title = cmd.get("title") or ""
        is_url = cmd.get("is_url")

        with self._lock:
            previous = self._current
            same_source = bool(
                previous and previous.get("source") == source
                and self._playing and not self._finished_emitted)
            self._generation += 1
            generation = self._generation
            if not same_source:
                # 换歌才清空播放态；同一首重播保持 UI 连贯
                self._playing = False
                self._paused = False
                self._position = 0.0
                self._duration = 0.0
                self._offset = 0.0
            self._loading = not same_source
            self._finished_emitted = False
            self._current = {"source": source, "title": title,
                             "gen": generation}

        # 停掉上一首
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        self._cleanup_local()

        if not self._mixer_ok:
            self._fail(generation, f"音频设备不可用（{self._mixer_error}）")
            return

        self._emit_if_current(generation, "downloading")

        # ---- 1. 准备本地文件 ----
        if is_url:
            path = find_cached(source)
            if path is None:
                try:
                    path = self._download(source, generation)
                except Exception as exc:
                    self._fail(generation, f"下载失败: {exc}")
                    return
                if path is None:          # 被新命令打断
                    return
        else:
            path = source
            if not path or not os.path.exists(path):
                self._fail(generation, "文件不存在")
                return

        # ---- 2. 加载（失败则尝试 ffmpeg 转码）----
        try:
            pygame.mixer.music.load(path)
        except Exception:
            converted = convert_to_mp3(
                path,
                workdir=CACHE_DIR if is_url else os.path.dirname(path) or None)
            if not converted:
                if not find_ffmpeg():
                    self._fail(generation, "无法播放该格式：缺 ffmpeg。"
                                           "把 ffmpeg.exe 放到程序根目录即可")
                else:
                    self._fail(generation, "无法播放该格式，ffmpeg 转码也失败了")
                return
            if not is_url:
                self._local_files.append(converted)
            try:
                pygame.mixer.music.load(converted)
                path = converted
            except Exception as exc:
                if converted not in self._local_files:
                    try:
                        os.unlink(converted)
                    except Exception:
                        pass
                self._fail(generation, f"加载失败: {exc}")
                return

        # ---- 3. 播放 ----
        try:
            pygame.mixer.music.set_volume(self._volume)
            pygame.mixer.music.play()
        except Exception as exc:
            self._fail(generation, f"播放失败: {exc}")
            return

        duration = self._probe_duration(path)
        with self._lock:
            if generation != self._generation:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                return
            self._playing = True
            self._paused = False
            self._loading = False
            self._duration = duration
            self._started_at = time.time()
        self._emit_if_current(generation, "playing")

    def _probe_duration(self, path: str) -> float:
        try:
            sound = pygame.mixer.Sound(path)
            value = float(sound.get_length())
            if value > 0:
                return value
        except Exception:
            pass
        return 0.0

    def _download(self, url: str, generation: int):
        """流式下载到缓存目录，返回路径；中途被打断返回 None"""
        session = http_session()
        response = session.get(url, stream=True, timeout=30)
        response.raise_for_status()

        suffix = _suffix_from_response(url, response.headers.get("Content-Type"))
        os.makedirs(CACHE_DIR, exist_ok=True)
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        final_path = os.path.join(CACHE_DIR, key + suffix)
        tmp_path = final_path + ".part"

        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_percent = -1
        with open(tmp_path, "wb") as fh:
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                if generation != self._generation:
                    fh.close()
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    return None
                fh.write(chunk)
                done += len(chunk)
                if total:
                    percent = int(done * 100 / total)
                    # 每变化 2% 才回报一次，避免刷屏
                    if percent >= last_percent + 2:
                        last_percent = percent
                        self._emit_if_current(generation,
                                              f"downloading:{percent}")

        os.replace(tmp_path, final_path)
        return final_path

    def _emit_if_current(self, generation: int, state: str):
        with self._lock:
            if generation != self._generation:
                return
        self._emit(state)

    def _fail(self, generation: int, message: str):
        with self._lock:
            if generation != self._generation:
                return
            self._playing = False
            self._paused = False
            self._loading = False
        self._emit(f"error:{message}")

    def _emit(self, state: str):
        callback = self.on_state
        if not callback:
            return
        try:
            callback(state)
        except Exception as exc:
            print("[播放器] 状态回调异常:", exc)

    def _cleanup_local(self):
        for path in list(self._local_files):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass
        self._local_files.clear()
