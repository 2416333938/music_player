"""QQ音乐客户端 —— 基于 qqmusic-api-python (0.7.x)"""
import json

from qqmusic_api import Client, Credential
from qqmusic_api.modules.search import SearchType
from qqmusic_api.modules.song import SongFileInfo, SongFileType

# 播放地址 CDN 兜底域名（新版本接口返回相对路径 purl）
FALLBACK_DOMAIN = "https://isure.stream.qqmusic.qq.com/"


class QQMusicClient:
    def __init__(self, cookie=None):
        """
        cookie 说明：
        - 新版本登录后保存的是 Credential 的 JSON 字符串（由登录对话框写入）；
        - 旧格式的 Cookie 串无法直接使用，视为未登录。
        """
        self.credential = None
        if cookie:
            try:
                self.credential = Credential.model_validate(json.loads(cookie))
            except Exception:
                self.credential = None

    async def search(self, keyword: str, limit: int = 10):
        """搜索歌曲，返回 [{mid, name, artists, album}]"""
        async with Client(credential=self.credential) as client:
            songs_raw = await client.search.search_by_type(
                keyword, SearchType.SONG, num=limit, page=1
            ).collect_items(limit)

        songs = []
        for item in songs_raw:
            songs.append({
                "mid": item.mid,
                "name": item.name or item.title or "",
                "artists": "/".join(
                    s.name for s in (item.singer or []) if s.name
                ),
                "album": (item.album.name if item.album else "") or "",
            })
        return songs

    async def get_play_url(self, song_mid: str):
        """获取播放直链"""
        async with Client(credential=self.credential) as client:
            resp = await client.song.get_song_urls(
                [SongFileInfo(mid=song_mid, file_type=SongFileType.MP3_128)],
                SongFileType.MP3_128,
            )
            for item in resp.data:
                if item.purl and item.result == 0:
                    if item.purl.startswith("http"):
                        return item.purl
                    return FALLBACK_DOMAIN + item.purl.lstrip("/")
        return None
