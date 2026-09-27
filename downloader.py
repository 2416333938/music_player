"""批量下载

- DownloadManager：队列 + 工作线程，逐个下载并回报进度
- 自动按内容类型选扩展名，尽量写入 ID3 标签（mutagen 可选）
- 下载完成后可以标记到播放列表的 local_path，之后播放直接读本地文件
"""
from __future__ import annotations

import os
import threading
import time
import uuid

import tray
from player import http_session, CACHE_DIR

try:                                     # mutagen 不是硬依赖
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    HAS_MUTAGEN = True
except Exception:                        # pragma: no cover
    HAS_MUTAGEN = False

try:
    import requests
except Exception:                        # pragma: no cover
    requests = None


STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

STATUS_TEXT = {
    STATUS_WAITING: "等待中",
    STATUS_RUNNING: "下载中",
    STATUS_DONE: "已完成",
    STATUS_FAILED: "失败",
    STATUS_CANCELLED: "已取消",
}


def default_download_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), "Music", "多平台音乐")
    return base


def _ext_from(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "m4a" in ct or "mp4" in ct or "aac" in ct:
        return ".m4a"
    if "flac" in ct:
        return ".flac"
    if "wav" in ct:
        return ".wav"
    if "ogg" in ct or "opus" in ct:
        return ".ogg"
    path = (url or "").split("?")[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac", ".opus"):
        return ext
    return ".mp3"


def unique_path(directory: str, filename: str) -> str:
    """同名文件自动加 (2) (3) 后缀，绝不覆盖已有文件"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({index}){ext}")
        index += 1
    return candidate


AUDIO_CONTAINERS = {
    ".mp3": "mp3",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".flac": "flac",
    ".ogg": "ogg",
    ".oga": "ogg",
    ".opus": "opus",
    ".wav": "wav",
    ".aac": "adts",
}

# MP4 家族的 box 类型，用来在 ftyp 出现位置不典型时兜底判断
_MP4_BOXES = (b"moov", b"mdat", b"free", b"wide", b"skip", b"ftyp", b"styp",
              b"sidx", b"moof")


def _id3_size(head: bytes) -> int:
    """ID3v2 标签总长度（含 10 字节头）；不是 ID3 返回 0"""
    if len(head) < 10 or head[:3] != b"ID3":
        return 0
    size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | \
           ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
    return 10 + size


def sniff_container(path: str) -> str:
    """按文件头判断真实容器格式，而不是看扩展名

    这个很重要：B站音频是 fMP4/AAC，如果按 .mp3 去写 ID3v2 标签，
    文件会被写坏（ID3 头 + MP4 数据），pygame 和 ffmpeg 都读不了。
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            if not head:
                return ""
            offset = _id3_size(head)
            if offset:
                if offset > len(head) - 8:
                    fh.seek(offset)
                    head = head[:10] + fh.read(16)
                # 跳过 ID3 头看真实载荷
                payload = head[10 + (offset - 10):] if offset <= len(head) \
                    else b""
                if len(payload) >= 8:
                    head = payload
                else:
                    fh.seek(offset)
                    head = fh.read(16)
    except Exception:
        return ""

    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    if len(head) >= 8 and head[4:8] in _MP4_BOXES:
        return "mp4"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        if b"OpusHead" in head:
            return "opus"
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"\xff\xf2",
                    b"\xff\xe3", b"\xff\xf9"):
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF0) == 0xF0:
        return "adts"
    return ""


def ext_for_container(container: str) -> str:
    return {"mp3": ".mp3", "mp4": ".m4a", "flac": ".flac", "ogg": ".ogg",
            "opus": ".opus", "wav": ".wav", "adts": ".aac"}.get(container, "")


def _container_of_ext(ext: str) -> str:
    return AUDIO_CONTAINERS.get((ext or "").lower(), "")


def ensure_correct_extension(path: str):
    """核对扩展名和真实格式，不一致就改名

    返回最终的文件路径（可能和传进来的不同）。
    """
    container = sniff_container(path)
    if not container:
        return path
    current_ext = os.path.splitext(path)[1].lower()
    if _container_of_ext(current_ext) == container:
        return path
    wanted = ext_for_container(container)
    if not wanted:
        return path
    target = os.path.splitext(path)[0] + wanted
    if os.path.normcase(target) == os.path.normcase(path):
        return path
    try:
        if os.path.exists(target):                 # 不覆盖已有文件
            target = unique_path(os.path.dirname(target),
                                 os.path.basename(target))
        os.replace(path, target)
        print(f"[下载] 扩展名与真实格式不符（{container}），已改名："
              f"{os.path.basename(target)}")
        return target
    except Exception as exc:
        print(f"[下载] 改名失败: {exc}")
        return path


def write_tags(path: str, track: dict):
    """尽力写入元数据；任何失败都忽略（不影响音频本身）

    关键点：按文件**真实格式**挑标签写法，不看扩展名。
    MP4/M4A 只能写 iTunSMPB 那套 atom，绝对不能加 ID3v2 头，否则文件报废。
    """
    if not HAS_MUTAGEN:
        return
    title = tray.track_title(track)
    artist = tray.track_artist(track)
    album = track.get("album") or ""

    container = sniff_container(path) or _container_of_ext(
        os.path.splitext(path)[1])
    try:
        if container == "mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("TIT2")
            tags.add(TIT2(encoding=3, text=title))
            if artist:
                tags.delall("TPE1")
                tags.add(TPE1(encoding=3, text=artist))
            if album:
                tags.delall("TALB")
                tags.add(TALB(encoding=3, text=album))
            tags.save(path, v2_version=3)
        elif container == "mp4":
            audio = MP4(path)
            audio["\xa9nam"] = title
            if artist:
                audio["\xa9ART"] = artist
            if album:
                audio["\xa9alb"] = album
            audio.save()
        elif container == "flac":
            audio = FLAC(path)
            audio["title"] = title
            if artist:
                audio["artist"] = artist
            if album:
                audio["album"] = album
            audio.save()
        else:
            # ogg / opus / wav / adts：不写标签，避免踩各家实现的坑
            return
    except Exception as exc:
        print(f"[下载] 写入标签失败（忽略）: {exc}")


# ============================================================
# 下载任务
# ============================================================
class DownloadTask:
    def __init__(self, track: dict, playlist_id: str = "", filename: str = ""):
        self.uid = uuid.uuid4().hex[:10]
        self.track = track
        self.playlist_id = playlist_id
        self.filename = filename or tray.download_filename(track)
        self.status = STATUS_WAITING
        self.progress = 0.0            # 0~1，总进度
        self.received = 0
        self.total = 0
        self.path = ""
        self.error = ""
        self.speed = 0.0
        self.created_at = time.time()
        self.finished_at = 0.0


# ============================================================
# 下载管理器
# ============================================================
class DownloadManager:
    """批量下载队列

    resolve(track) -> url 由调用方注入（platforms 里的客户端逻辑）
    """

    def __init__(self, resolve, on_change=None, directory=None,
                 max_workers=2, store=None):
        self.resolve = resolve
        self.on_change = on_change          # () -> None（任意状态变化）
        self.directory = directory or default_download_dir()
        self.max_workers = max(1, int(max_workers))
        self.store = store                  # 可选：PlaylistStore，用于回写 local_path

        self.tasks = []
        self._lock = threading.Lock()
        self._queue = []
        self._queued_uids = set()
        self._workers = []
        self._cancel_flags = set()
        self._session = http_session() if requests else None

        try:
            os.makedirs(self.directory, exist_ok=True)
        except Exception:
            self.directory = CACHE_DIR

        self._spawn_workers()

    # ---------------- 线程池 ----------------
    def _spawn_workers(self):
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True,
                                      name=f"downloader-{i}")
            worker.start()
            self._workers.append(worker)

    def _worker(self):
        while True:
            try:
                uid = self._queue.pop(0)
            except IndexError:
                time.sleep(0.25)
                continue
            with self._lock:
                self._queued_uids.discard(uid)
                task = self._find(uid)
            if task is None or task.status != STATUS_WAITING:
                continue
            self._run_task(task)

    def _find(self, uid):
        for task in self.tasks:
            if task.uid == uid:
                return task
        return None

    # ---------------- 对外接口 ----------------
    def enqueue(self, tracks, playlist_id="", filenames=None):
        """加入下载队列，返回新建的任务列表（自动跳过重复项）"""
        created = []
        with self._lock:
            existing = {
                (t.track.get("platform"), str(t.track.get("id")), t.playlist_id)
                for t in self.tasks
                if t.status in (STATUS_WAITING, STATUS_RUNNING, STATUS_DONE)
            }
            for index, track in enumerate(tracks):
                key = (track.get("platform"), str(track.get("id")), playlist_id)
                if key in existing:
                    continue
                filename = ""
                if filenames and index < len(filenames):
                    filename = filenames[index]
                task = DownloadTask(track, playlist_id, filename)
                self.tasks.append(task)
                self._queue.append(task.uid)
                self._queued_uids.add(task.uid)
                existing.add(key)
                created.append(task)
        self._changed()
        return created

    def retry(self, task):
        if task.status not in (STATUS_FAILED, STATUS_CANCELLED):
            return False
        with self._lock:
            task.status = STATUS_WAITING
            task.progress = 0.0
            task.received = 0
            task.error = ""
            self._queue.append(task.uid)
            self._queued_uids.add(task.uid)
        self._changed()
        return True

    def cancel(self, task):
        if task.status == STATUS_WAITING:
            with self._lock:
                task.status = STATUS_CANCELLED
            self._changed()
            return True
        if task.status == STATUS_RUNNING:
            self._cancel_flags.add(task.uid)
            return True
        return False

    def remove(self, task):
        """从列表里移除一条（正在下载的先取消）"""
        if task.status == STATUS_RUNNING:
            self._cancel_flags.add(task.uid)
        with self._lock:
            if task in self.tasks:
                self.tasks.remove(task)
        self._changed()

    def clear_finished(self):
        with self._lock:
            self.tasks = [t for t in self.tasks
                          if t.status not in (STATUS_DONE, STATUS_CANCELLED)]
        self._changed()

    def pending_count(self):
        return sum(1 for t in self.tasks
                   if t.status in (STATUS_WAITING, STATUS_RUNNING))

    def stats(self):
        done = sum(1 for t in self.tasks if t.status == STATUS_DONE)
        failed = sum(1 for t in self.tasks if t.status == STATUS_FAILED)
        return {
            "total": len(self.tasks),
            "done": done,
            "failed": failed,
            "pending": self.pending_count(),
        }

    def set_directory(self, path):
        try:
            os.makedirs(path, exist_ok=True)
            self.directory = path
            return True
        except Exception as exc:
            print(f"[下载] 目录不可用: {exc}")
            return False

    # ---------------- 具体下载 ----------------
    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception as exc:
                print("[下载] 状态回调异常:", exc)

    def _run_task(self, task):
        task.status = STATUS_RUNNING
        task.progress = 0.0
        self._changed()

        url = ""
        try:
            url = self.resolve(task.track) or ""
        except Exception as exc:
            url = ""
            task.error = f"取下载地址失败: {exc}"

        if not url:
            task.status = STATUS_FAILED
            task.error = task.error or "无法获取下载地址（可能需要登录该平台）"
            task.finished_at = time.time()
            self._changed()
            return

        tmp_path = ""
        try:
            response = self._session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            ext = _ext_from(url, response.headers.get("Content-Type"))
            if task.filename.lower().endswith((".mp3", ".flac", ".m4a",
                                               ".wav", ".ogg")):
                target_name = task.filename
            else:
                target_name = os.path.splitext(task.filename)[0] + ext
            target = unique_path(self.directory, target_name)
            tmp_path = target + ".part"

            task.total = int(response.headers.get("Content-Length") or 0)
            received = 0
            started = time.time()
            with open(tmp_path, "wb") as fh:
                for chunk in response.iter_content(65536):
                    if task.uid in self._cancel_flags:
                        raise _Cancelled()
                    if not chunk:
                        continue
                    fh.write(chunk)
                    received += len(chunk)
                    task.received = received
                    elapsed = max(0.001, time.time() - started)
                    task.speed = received / elapsed
                    if task.total:
                        task.progress = min(0.999, received / task.total)
                    else:
                        task.progress = min(0.9, received / (6 * 1024 * 1024))
                    self._changed()

            os.replace(tmp_path, target)
            # 先核对真实格式，扩展名不对就改名；
            # 避免把 fMP4 当成 mp3 去写 ID3 标签导致文件报废
            target = ensure_correct_extension(target)
            task.path = target
            write_tags(target, task.track)

            if self.store and task.playlist_id:
                self.store.set_local_path(
                    task.playlist_id, tray.track_key(task.track), target)
            task.track["local_path"] = target

            task.progress = 1.0
            task.status = STATUS_DONE
            task.finished_at = time.time()

        except _Cancelled:
            task.status = STATUS_CANCELLED
            task.finished_at = time.time()
            self._safe_unlink(tmp_path)
        except Exception as exc:
            task.status = STATUS_FAILED
            task.error = str(exc)
            task.finished_at = time.time()
            self._safe_unlink(tmp_path)
        finally:
            self._cancel_flags.discard(task.uid)
            self._changed()

    @staticmethod
    def _safe_unlink(path):
        if not path:
            return
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass


class _Cancelled(Exception):
    """内部信号：任务被用户取消"""
