"""曲目模型 + 播放列表存储

- Track 就是普通 dict，直接可 JSON 序列化；
- PlaylistStore 负责 playlists.json 的读写，全部写入都是原子的。
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import uuid

import theme as T

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLAYLIST_FILE = os.path.join(BASE_DIR, "playlists.json")
STORE_VERSION = 1

_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(text) -> str:
    """去掉 HTML 标签并还原实体

    平台的搜索接口会在标题里插入 <em class="keyword">…</em> 高亮标记，
    直接显示会很难看，这里统一清掉。
    """
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        text = "".join(part for part in text if isinstance(part, str))
    text = _TAG_RE.sub("", str(text))
    return html.unescape(text).strip()

# 每个平台用来取「播放 / 下载直链」的标识字段
ID_FIELDS = {
    "netease": "id",
    "qqmusic": "mid",
    "kugou": "hash",
    "qishui": "id",
    "bilibili": "bvid",
}

# 各平台搜索结果里标题 / 歌手 / 专辑的字段名
_PLATFORM_FIELDS = {
    "bilibili": ("title", "author", None),
    "default": ("name", "artists", "album"),
}


# ============================================================
# 曲目模型
# ============================================================
def make_track(platform: str, raw: dict) -> dict:
    """把平台搜索结果统一成内部曲目结构"""
    title_key, artist_key, album_key = _PLATFORM_FIELDS.get(
        platform, _PLATFORM_FIELDS["default"])

    title = (raw.get(title_key) or raw.get("name") or raw.get("title")
             or "未知曲目")
    if isinstance(title, list):        # B站搜索偶尔返回富文本数组
        title = "".join(part for part in title if isinstance(part, str))
    artists = raw.get(artist_key) or ""
    album = (raw.get(album_key) or "") if album_key else ""

    track = {
        "platform": platform,
        "id": str(raw.get(ID_FIELDS.get(platform, "id")) or ""),
        "title": clean_text(title) or "未知曲目",
        "artists": clean_text(artists),
        "album": clean_text(album),
        "duration": int(raw.get("duration") or 0),
        "local_path": raw.get("local_path") or "",
        "added_at": int(time.time()),
    }
    if platform == "kugou" and raw.get("album_id"):
        track["album_id"] = str(raw["album_id"])
    return track


def track_key(track: dict) -> str:
    """曲目唯一键：平台 + 平台内 id"""
    return f"{track.get('platform')}::{track.get('id')}"


def track_title(track: dict) -> str:
    return track.get("title") or "未知曲目"


def track_artist(track: dict) -> str:
    return track.get("artists") or ""


def track_platform(track: dict) -> str:
    return track.get("platform") or ""


def track_display(track: dict) -> str:
    artist = track_artist(track)
    return f"{track_title(track)} - {artist}" if artist else track_title(track)


def track_has_local(track: dict) -> bool:
    path = track.get("local_path") or ""
    return bool(path) and os.path.exists(path)


def safe_filename(text: str, max_len: int = 80) -> str:
    """把标题处理成合法文件名"""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in bad else ch for ch in (text or ""))
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32).strip(" .")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len]


def download_filename(track: dict, ext: str = ".mp3") -> str:
    """生成下载文件名：歌手 - 标题 [平台].ext"""
    artist = track_artist(track)
    title = track_title(track)
    base = f"{artist} - {title}" if artist else title
    platform = T.platform_name(track_platform(track))
    return f"{safe_filename(base)} [{platform}]{ext}"


# ============================================================
# 播放列表存储
# ============================================================
class PlaylistStore:
    """playlists.json 的读写封装

    数据结构：
    {
      "version": 1,
      "active": "<playlist id>",
      "playlists": [
        {"id": "...", "name": "...", "created_at": 0, "updated_at": 0,
         "tracks": [ {...track...} ]}
      ]
    }
    """

    def __init__(self, path: str = PLAYLIST_FILE):
        self.path = path
        self.data = {"version": STORE_VERSION, "active": "", "playlists": []}
        self.load()

    # ---------------- 读写 ----------------
    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            print(f"[播放列表] 读取失败，将重新开始: {exc}")
            self._backup_broken()
            return

        playlists = []
        for item in (raw.get("playlists") or []):
            if not isinstance(item, dict):
                continue
            playlists.append({
                "id": str(item.get("id") or uuid.uuid4().hex[:12]),
                "name": str(item.get("name") or "未命名歌单"),
                "created_at": int(item.get("created_at") or time.time()),
                "updated_at": int(item.get("updated_at") or time.time()),
                "tracks": [t for t in (item.get("tracks") or [])
                           if isinstance(t, dict) and t.get("id")],
            })
        self.data = {
            "version": STORE_VERSION,
            "active": str(raw.get("active") or ""),
            "playlists": playlists,
        }

    def _backup_broken(self):
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".broken")
        except Exception:
            pass

    def save(self):
        """原子写入，避免中途崩溃写坏文件"""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception as exc:
            print(f"[播放列表] 保存失败: {exc}")
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass
            return False

    # ---------------- 查询 ----------------
    @property
    def playlists(self):
        return self.data["playlists"]

    def get(self, playlist_id: str):
        for pl in self.playlists:
            if pl["id"] == playlist_id:
                return pl
        return None

    def by_name(self, name: str):
        name = (name or "").strip()
        for pl in self.playlists:
            if pl["name"] == name:
                return pl
        return None

    def track_count(self, playlist_id: str) -> int:
        pl = self.get(playlist_id)
        return len(pl["tracks"]) if pl else 0

    @property
    def active_id(self):
        active = self.data.get("active") or ""
        if active and self.get(active) is None:
            self.data["active"] = ""
            return ""
        return active

    def set_active(self, playlist_id: str):
        self.data["active"] = playlist_id or ""
        self.save()

    # ---------------- 播放列表增删改 ----------------
    def create(self, name: str, tracks=None):
        name = (name or "").strip() or "新建歌单"
        now = int(time.time())
        playlist = {
            "id": uuid.uuid4().hex[:12],
            "name": self._unique_name(name),
            "created_at": now,
            "updated_at": now,
            "tracks": list(tracks or []),
        }
        self.playlists.append(playlist)
        self.save()
        return playlist

    def _unique_name(self, name: str) -> str:
        existing = {pl["name"] for pl in self.playlists}
        if name not in existing:
            return name
        i = 2
        while f"{name} ({i})" in existing:
            i += 1
        return f"{name} ({i})"

    def rename(self, playlist_id: str, name: str):
        pl = self.get(playlist_id)
        if not pl:
            return False
        name = (name or "").strip()
        if not name or name == pl["name"]:
            return False
        if self.by_name(name):
            return False
        pl["name"] = name
        pl["updated_at"] = int(time.time())
        self.save()
        return True

    def delete(self, playlist_id: str):
        pl = self.get(playlist_id)
        if not pl:
            return False
        self.playlists.remove(pl)
        if self.data.get("active") == playlist_id:
            self.data["active"] = ""
        self.save()
        return True

    def duplicate(self, playlist_id: str):
        pl = self.get(playlist_id)
        if not pl:
            return None
        return self.create(f"{pl['name']} 副本", [dict(t) for t in pl["tracks"]])

    # ---------------- 曲目增删改 ----------------
    def add_tracks(self, playlist_id: str, tracks, dedupe=True,
                   position=None):
        """返回 (新增数量, 跳过数量)"""
        pl = self.get(playlist_id)
        if not pl or not tracks:
            return 0, 0

        existing = {track_key(t) for t in pl["tracks"]} if dedupe else set()
        added, skipped = 0, 0
        new_items = []
        for track in tracks:
            key = track_key(track)
            if dedupe and key in existing:
                skipped += 1
                continue
            item = dict(track)
            item.setdefault("added_at", int(time.time()))
            new_items.append(item)
            existing.add(key)
            added += 1

        if new_items:
            if position is None:
                pl["tracks"].extend(new_items)
            else:
                pos = max(0, min(int(position), len(pl["tracks"])))
                pl["tracks"][pos:pos] = new_items
            pl["updated_at"] = int(time.time())
            self.save()
        return added, skipped

    def remove_tracks(self, playlist_id: str, keys) -> int:
        pl = self.get(playlist_id)
        if not pl:
            return 0
        key_set = set(keys)
        before = len(pl["tracks"])
        pl["tracks"] = [t for t in pl["tracks"] if track_key(t) not in key_set]
        removed = before - len(pl["tracks"])
        if removed:
            pl["updated_at"] = int(time.time())
            self.save()
        return removed

    def move_track(self, playlist_id: str, index: int, delta: int) -> int:
        """上移 / 下移一首，返回新位置（越界返回原位置）"""
        pl = self.get(playlist_id)
        if not pl:
            return index
        tracks = pl["tracks"]
        new_index = index + delta
        if index < 0 or index >= len(tracks) or new_index < 0 or new_index >= len(tracks):
            return index
        tracks[index], tracks[new_index] = tracks[new_index], tracks[index]
        pl["updated_at"] = int(time.time())
        self.save()
        return new_index

    def set_local_path(self, playlist_id: str, key: str, path: str) -> bool:
        """标记某首曲目已下载到本地"""
        pl = self.get(playlist_id)
        if not pl:
            return False
        for track in pl["tracks"]:
            if track_key(track) == key:
                track["local_path"] = path
                self.save()
                return True
        return False

    def clear(self, playlist_id: str) -> bool:
        pl = self.get(playlist_id)
        if not pl or not pl["tracks"]:
            return False
        pl["tracks"] = []
        pl["updated_at"] = int(time.time())
        self.save()
        return True

    # ---------------- 导入 / 导出 ----------------
    def export_m3u(self, playlist_id: str, path: str) -> bool:
        pl = self.get(playlist_id)
        if not pl:
            return False
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for track in pl["tracks"]:
                    f.write(f"#EXTINF:-1,{track_artist(track)} - "
                            f"{track_title(track)}\n")
                    f.write(f"{track.get('local_path') or ''}\n")
            return True
        except Exception as exc:
            print(f"[播放列表] 导出失败: {exc}")
            return False
