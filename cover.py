"""封面图：异步下载 + 磁盘缓存 + 程序化兜底封面

平台不一定给封面（酷狗 / 汽水就没有），所以这里准备了兜底方案：
用「标题+歌手」做种子生成一张确定性的渐变几何封面，
同一个曲目每次生成的图案都一样，视觉上不会花。
"""
from __future__ import annotations

import hashlib
import io
import os
import queue
import tempfile
import threading
import time

import theme as T

try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except Exception:                                   # pragma: no cover
    HAS_PIL = False

try:
    import requests
except Exception:                                   # pragma: no cover
    requests = None

COVER_DIR = os.path.join(
    os.environ.get("TEMP") or tempfile.gettempdir(), "music_player_cache",
    "covers")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

COVER_LIMIT_BYTES = 300 * 1024 * 1024

# 兜底封面的配色组（深色、跟界面主色协调）
_ART_PALETTES = (
    ("#6C5CE7", "#22D3EE"),
    ("#E64A4A", "#FBBF24"),
    ("#31C27C", "#22D3EE"),
    ("#FB7299", "#6C5CE7"),
    ("#F97316", "#FB7185"),
    ("#0EA5E9", "#8B5CF6"),
    ("#14B8A6", "#84CC16"),
    ("#F43F5E", "#8B5CF6"),
    ("#FF6A3D", "#FBBF24"),
    ("#2CA2F0", "#34D399"),
)


def _seed_int(text: str) -> int:
    return int(hashlib.sha1((text or "?").encode("utf-8")).hexdigest()[:12], 16)


def url_key(url: str) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:20]


def cached_path(url: str):
    """返回磁盘缓存路径（不保证存在）"""
    key = url_key(url)
    for ext in (".jpg", ".png", ".webp", ".jpeg"):
        path = os.path.join(COVER_DIR, key + ext)
        if os.path.isfile(path) and os.path.getsize(path) > 512:
            return path
    return None


def prune_cache():
    try:
        if not os.path.isdir(COVER_DIR):
            return
        entries = []
        total = 0
        for name in os.listdir(COVER_DIR):
            path = os.path.join(COVER_DIR, name)
            try:
                stat = os.stat(path)
            except Exception:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        if total <= COVER_LIMIT_BYTES:
            return
        entries.sort()
        for _mtime, size, path in entries:
            if total <= COVER_LIMIT_BYTES:
                break
            try:
                os.unlink(path)
                total -= size
            except Exception:
                pass
    except Exception:
        pass


# ============================================================
# 下载
# ============================================================
class CoverLoader:
    """后台下载封面图；下载完通过 done_queue 通知主线程"""

    def __init__(self, max_workers=3):
        self.done_queue = queue.Queue()
        self._pending = set()
        self._lock = threading.Lock()
        self._jobs = queue.Queue()
        self._session = requests.Session() if requests else None
        if self._session is not None:
            self._session.headers.update({"User-Agent": UA})
        self._workers = []
        for index in range(max(1, max_workers)):
            worker = threading.Thread(target=self._worker, daemon=True,
                                      name=f"cover-{index}")
            worker.start()
            self._workers.append(worker)
        try:
            os.makedirs(COVER_DIR, exist_ok=True)
        except Exception:
            pass
        threading.Thread(target=prune_cache, daemon=True).start()

    def request(self, url: str):
        """请求下载（已缓存或已排队的会跳过）"""
        if not url or self._session is None:
            return False
        if cached_path(url):
            return False
        with self._lock:
            if url in self._pending:
                return False
            self._pending.add(url)
        self._jobs.put(url)
        return True

    def _worker(self):
        while True:
            try:
                url = self._jobs.get()
            except Exception:
                return
            if url is None:
                return
            try:
                path = self._fetch(url)
            except Exception as exc:
                path = None
                print(f"[封面] 下载失败: {exc}")
            finally:
                with self._lock:
                    self._pending.discard(url)
            self.done_queue.put((url, path))

    def _fetch(self, url: str):
        response = self._session.get(url, timeout=20, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        else:
            ext = ".jpg"

        os.makedirs(COVER_DIR, exist_ok=True)
        path = os.path.join(COVER_DIR, url_key(url) + ext)
        tmp = path + ".part"
        data = response.content
        if len(data) < 512:
            return None
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        return path


# ============================================================
# 程序化兜底封面
# ============================================================
def make_art(seed_text: str, size: int = 168):
    """根据文本生成一张确定性的渐变几何封面（PIL Image）"""
    if not HAS_PIL:
        return None
    seed = _seed_int(seed_text)
    palette = _ART_PALETTES[seed % len(_ART_PALETTES)]
    base, accent = palette

    image = Image.new("RGB", (size, size), base)
    draw = ImageDraw.Draw(image)

    # 对角渐变
    for y in range(size):
        ratio = y / float(size - 1)
        color = T.mix(base, accent, ratio * 0.85)
        draw.line([(0, y), (size, y)], fill=color)

    # 用 seed 决定几个几何块的位置，做出「专辑封面」的感觉
    rng = seed
    def nxt(limit):
        nonlocal rng
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        return rng % max(1, limit)

    for _ in range(3):
        cx = nxt(size)
        cy = nxt(size)
        radius = size // 6 + nxt(size // 4)
        tint = T.mix(accent, "#ffffff", 0.25 + (nxt(40) / 100.0))
        alpha_layer = Image.new("RGB", (size, size), tint)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius], fill=58)
        image = Image.composite(alpha_layer, image, mask)

    draw = ImageDraw.Draw(image)
    # 一条斜线装饰
    offset = nxt(size // 2)
    width = 3 + nxt(6)
    draw.line([(offset - size, size), (offset + size, 0)],
              fill=T.mix(accent, "#ffffff", 0.45), width=width)
    return image


# ============================================================
# 缓存（内存）
# ============================================================
class CoverCache:
    """内存缓存 + 缩略图生成

    所有生成 PhotoImage 的动作都在主线程做（tkinter 要求），
    CoverImage 控件会按需调用 get()。
    """

    def __init__(self, loader: CoverLoader = None):
        self.loader = loader
        self._photos = {}           # (key, size) -> PhotoImage
        self._src = {}              # url -> PIL.Image

    def get(self, url: str, seed_text: str, size: int):
        """取一张 size×size 的 PhotoImage

        返回 (photo, is_real)：
        - 有封面地址且已下载好 → (真实封面, True)
        - 有地址但还没下好     → (兜底图, False)，同时排入下载队列
        - 没有地址（酷狗/汽水）→ (兜底图, False)
        """
        if not HAS_PIL:
            return None, False

        if url:
            key = (url, size)
            photo = self._photos.get(key)
            if photo is not None:
                return photo, True
            real = self._load_real(url, size)
            if real is not None:
                self._photos[key] = real
                return real, True
            # 还没下好：给兜底图撑场面，不要占用 (url,size) 这个键
            return self._placeholder(seed_text, size), False

        key = ("art", seed_text, size)
        photo = self._photos.get(key)
        if photo is not None:
            return photo, False
        art = self._placeholder(seed_text, size)
        if art is not None:
            self._photos[key] = art
        return art, False

    def _placeholder(self, seed_text: str, size: int):
        """兜底封面（确定性，同一文本永远一样）"""
        try:
            image = make_art(seed_text, max(size, 96))
            if image is None:
                return None
            return ImageTk.PhotoImage(
                image.resize((size, size), Image.LANCZOS))
        except Exception as exc:
            print(f"[封面] 生成兜底封面失败: {exc}")
            return None

    def _has_real(self, url: str) -> bool:
        return cached_path(url) is not None

    def _load_real(self, url: str, size: int):
        path = cached_path(url)
        if path is None:
            if self.loader is not None:
                self.loader.request(url)
            return None
        try:
            source = self._src.get(url)
            if source is None:
                source = Image.open(path).convert("RGB")
                self._src[url] = source
            return ImageTk.PhotoImage(self._fit(source, size))
        except Exception as exc:
            print(f"[封面] 解码失败: {exc}")
            return None

    @staticmethod
    def _fit(source, size: int):
        """等比裁剪成正方形"""
        w, h = source.size
        edge = min(w, h)
        left = (w - edge) // 2
        top = (h - edge) // 2
        cropped = source.crop((left, top, left + edge, top + edge))
        if edge != size:
            cropped = cropped.resize((size, size), Image.LANCZOS)
        return cropped

    def invalidate(self, url: str = ""):
        if not url:
            self._photos.clear()
            self._src.clear()
            return
        for key in [k for k in self._photos if k[0] == url]:
            self._photos.pop(key, None)
        self._src.pop(url, None)

    def drain(self, limit=40):
        """把已下载好的封面转成 PhotoImage，避免渲染时卡顿"""
        count = 0
        while count < limit:
            try:
                url, path = self.loader.done_queue.get_nowait()
            except Exception:
                break
            count += 1
            if not path:
                continue
            for key in [k for k in self._photos if k[0] == url]:
                self._photos.pop(key, None)
        return count
