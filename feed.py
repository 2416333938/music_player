"""首页内容源

网易云那种首页需要「内容」，但我们的数据来自五个平台的搜索结果，
所以这里用两套东西拼出来：

1. 平台真实内容：按分类关键词去搜（华语流行 / 欧美热歌 / 轻音乐 …），
   搜到的曲目汇总成一个个「推荐歌单」，卡片上显示真实封面。
2. 个人内容：我喜欢的音乐、最近播放、每个自建歌单。
3. 每日推荐：按日期做种，从音乐库里挑一批，每天自动换一批。

结果带磁盘缓存，避免每次启动都重新联网搜。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time

import theme as T
import tray

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEED_CACHE_FILE = os.path.join(BASE_DIR, "feed_cache.json")
CACHE_TTL = 12 * 3600          # 12 小时

# 首页「分类」卡片（第一排）
CATEGORY_CARDS = [
    {"key": "daily", "title": "每日推荐", "subtitle": "根据你的音乐库每天更新",
     "color": "#E64A4A", "icon": "check"},
    {"key": "guess", "title": "猜你喜欢", "subtitle": "从你的音乐库里挑选",
     "color": "#6C5CE7", "icon": "music"},
    {"key": "recent", "title": "最近播放", "subtitle": "你最近听过的曲目",
     "color": "#22D3EE", "icon": "refresh"},
    {"key": "bili", "title": "B站精选", "subtitle": "视频里的好音乐",
     "color": "#FB7299", "icon": "play"},
    {"key": "instrumental", "title": "纯音乐", "subtitle": "安静地听一会儿",
     "color": "#31C27C", "icon": "volume"},
]

# 「推荐歌单」用的分类关键词（每个分类去一个平台搜）
FEED_STATIONS = [
    {"key": "huayu", "title": "华语流行精选", "keyword": "华语流行",
     "platform": "netease", "hint": "网易云"},
    {"key": "eu", "title": "欧美热歌榜", "keyword": "欧美热歌",
     "platform": "netease", "hint": "网易云"},
    {"key": "light", "title": "轻音乐 · 放松", "keyword": "轻音乐 放松",
     "platform": "netease", "hint": "网易云"},
    {"key": "rock", "title": "摇滚现场", "keyword": "摇滚",
     "platform": "netease", "hint": "网易云"},
    {"key": "guofeng", "title": "古风国风", "keyword": "古风",
     "platform": "netease", "hint": "网易云"},
    {"key": "piano", "title": "钢琴纯音", "keyword": "钢琴 纯音乐",
     "platform": "netease", "hint": "网易云"},
    {"key": "qqhot", "title": "QQ音乐热歌", "keyword": "热门歌曲",
     "platform": "qqmusic", "hint": "QQ音乐"},
    {"key": "anime", "title": "动漫神曲", "keyword": "动漫 主题曲",
     "platform": "netease", "hint": "网易云"},
]

DAILY_SEEDS = [
    "今天也要好好听歌", "通勤路上", "深夜单曲循环", "午后阳光",
    "写代码的时候", "下雨天", "心情不错", "放空十分钟",
]


def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


def _seed_for_day() -> int:
    return int(hashlib.sha1(_today_key().encode()).hexdigest()[:10], 16)


# ============================================================
# 缓存
# ============================================================
class FeedCache:
    """feed_cache.json：{key: {"at": 时间戳, "tracks": [...]}}"""

    def __init__(self, path=FEED_CACHE_FILE):
        self.path = path
        self.data = {}
        self._lock = threading.Lock()
        self.load()

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.data = raw
        except Exception as exc:
            print(f"[首页] 缓存读取失败: {exc}")

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception as exc:
            print(f"[首页] 缓存写入失败: {exc}")

    def get(self, key: str, ttl=CACHE_TTL):
        with self._lock:
            entry = self.data.get(key)
        if not entry:
            return None
        if ttl and time.time() - entry.get("at", 0) > ttl:
            return None
        tracks = entry.get("tracks")
        return tracks if isinstance(tracks, list) else None

    def get_any(self, key: str):
        """忽略过期时间取旧数据（用于先展示再刷新）"""
        with self._lock:
            entry = self.data.get(key)
        tracks = (entry or {}).get("tracks")
        return tracks if isinstance(tracks, list) else None

    def put(self, key: str, tracks):
        with self._lock:
            self.data[key] = {"at": time.time(), "tracks": list(tracks or [])}


# ============================================================
# 每日推荐 / 猜你喜欢
# ============================================================
def build_daily(library, history, limit=30):
    """每日推荐：同一天结果固定，第二天自动换一批"""
    pool = []
    for track in list(library or []):
        pool.append(track)
    for track in list(history or []):
        pool.append(track)
    if not pool:
        return []

    # 去重
    seen = set()
    unique = []
    for track in pool:
        key = tray.track_key(track)
        if key in seen:
            continue
        seen.add(key)
        unique.append(track)

    rng = random.Random(_seed_for_day())
    rng.shuffle(unique)
    return unique[:limit]


def build_guess(library, history, played_keys, limit=30):
    """猜你喜欢：优先没听过的，其次常听的歌手"""
    library = list(library or [])
    if not library:
        return []
    played = {tray.track_key(t) for t in (history or [])}

    # 统计听过的歌手偏好
    artist_count = {}
    for track in (history or []):
        artist = tray.track_artist(track)
        if artist:
            artist_count[artist] = artist_count.get(artist, 0) + 1

    def score(track):
        value = 0
        if tray.track_key(track) not in played:
            value += 3
        value += artist_count.get(tray.track_artist(track), 0)
        value += 1 if tray.track_has_local(track) else 0
        return value

    rng = random.Random(_seed_for_day() + 7)
    ordered = sorted(library, key=score, reverse=True)
    head = ordered[: limit * 2]
    rng.shuffle(head)
    return head[:limit]


def build_recent(history, limit=30):
    items = list(history or [])
    return items[:limit]


def daily_title() -> str:
    seed = _seed_for_day()
    return f"{_today_key()} · {DAILY_SEEDS[seed % len(DAILY_SEEDS)]}"


# ============================================================
# 平台内容抓取
# ============================================================
def fetch_station(station: dict, clients, run_async, limit=18):
    """按分类关键词去对应平台搜一批曲目"""
    platform = station.get("platform") or "netease"
    client = (clients or {}).get(platform)
    keyword = station.get("keyword") or ""
    if client is None or not keyword:
        return []
    try:
        if platform == "netease":
            raw = client.search(keyword, limit)
        elif platform == "qqmusic":
            raw = run_async(client.search(keyword, limit))
        elif platform == "kugou":
            raw = client.search(keyword, limit)
        elif platform == "qishui":
            raw = client.search(keyword, limit)
        elif platform == "bilibili":
            raw = run_async(client.search_videos(keyword, limit))
        else:
            raw = []
        tracks = []
        for item in (raw or []):
            track = tray.make_track(platform, item)
            if track.get("id"):
                tracks.append(track)
        return tracks
    except Exception as exc:
        print(f"[首页] 抓取「{station.get('title')}」失败: {exc}")
        return []


def station_cover(tracks):
    """取该歌单里第一张可用封面"""
    for track in (tracks or []):
        if track.get("cover"):
            return track["cover"]
    return ""


def fake_play_count(title: str) -> str:
    """给分类歌单编一个稳定的播放量（纯装饰）"""
    value = int(hashlib.sha1(title.encode()).hexdigest()[:6], 16) % 480000
    return str(value + 12000)
