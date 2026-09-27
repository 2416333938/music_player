"""统一音频播放器：支持 mp3/flac/m4a 等格式"""
import os
import shutil
import subprocess
import tempfile
import threading

import pygame
import requests


class MusicPlayer:
    def __init__(self):
        self._mixer_ok = True
        try:
            pygame.mixer.init()
        except Exception as e:
            # 无音频设备时不让程序崩溃，播放时再提示
            self._mixer_ok = False
            print(f"[播放器] 音频设备初始化失败: {e}")
        self._playing = False
        self._temp_files = []          # 所有生成的临时文件
        self._lock = threading.Lock()

    # ---------------- 对外接口 ----------------
    def play_url(self, url: str, on_state_change=None):
        """异步下载并播放指定的音频 URL"""
        self.stop()
        threading.Thread(
            target=self._download_and_play,
            args=(url, on_state_change),
            daemon=True,
        ).start()

    def pause(self):
        try:
            pygame.mixer.music.pause()
        except Exception:
            pass

    def resume(self):
        try:
            pygame.mixer.music.unpause()
        except Exception:
            pass

    def stop(self):
        with self._lock:
            self._playing = False
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        self._cleanup()

    def set_volume(self, value: float):
        """value: 0.0 ~ 1.0"""
        try:
            pygame.mixer.music.set_volume(max(0.0, min(1.0, value)))
        except Exception:
            pass

    # ---------------- 内部实现 ----------------
    def _download_and_play(self, url, on_state_change):
        try:
            if not self._mixer_ok:
                raise RuntimeError("音频设备不可用，无法播放")
            if on_state_change:
                on_state_change("downloading")

            filepath = self._download(url)
            if not filepath:
                raise RuntimeError("下载失败")

            # 尝试直接加载
            try:
                pygame.mixer.music.load(filepath)
            except Exception:
                # 加载失败 → 用 ffmpeg 转成 mp3
                converted = self._convert_to_mp3(filepath)
                if not converted:
                    raise RuntimeError(
                        "无法播放该格式，请安装 ffmpeg：https://ffmpeg.org"
                    )
                filepath = converted
                pygame.mixer.music.load(filepath)

            pygame.mixer.music.play()
            with self._lock:
                self._playing = True

            if on_state_change:
                on_state_change("playing")

            while True:
                with self._lock:
                    if not self._playing:
                        break
                if not pygame.mixer.music.get_busy():
                    break
                pygame.time.wait(300)

            if on_state_change:
                on_state_change("finished")

        except Exception as e:
            if on_state_change:
                on_state_change(f"error:{e}")

    def _download(self, url: str) -> str:
        """把 URL 内容下载到临时文件，返回路径"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, stream=True, timeout=30, headers=headers)
        r.raise_for_status()

        ct = (r.headers.get("Content-Type") or "").lower()
        if "m4a" in ct or "mp4" in ct:
            suffix = ".m4a"
        elif "flac" in ct:
            suffix = ".flac"
        elif "wav" in ct:
            suffix = ".wav"
        elif "ogg" in ct:
            suffix = ".ogg"
        else:
            # 从 URL 里尝试推断
            path = url.split("?")[0]
            ext = os.path.splitext(path)[1].lower()
            suffix = ext if ext in (".mp3", ".flac", ".m4a", ".wav", ".ogg") else ".mp3"

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in r.iter_content(16384):
            tmp.write(chunk)
        tmp.close()

        self._temp_files.append(tmp.name)
        return tmp.name

    def _convert_to_mp3(self, src: str):
        """用 ffmpeg 转换成 mp3，失败返回 None"""
        if not shutil.which("ffmpeg"):
            return None
        dst = src + ".converted.mp3"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", src, "-vn",
                    "-acodec", "libmp3lame", "-q:a", "2",
                    dst,
                ],
                check=True,
                timeout=180,
            )
            self._temp_files.append(dst)
            return dst
        except Exception:
            return None

    def _cleanup(self):
        """清理所有临时文件"""
        for f in list(self._temp_files):
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except Exception:
                pass
        self._temp_files.clear()