"""酷狗音乐客户端 —— 基于酷狗移动端网页接口（requests 直连）

说明：
- 搜索接口可正常使用；
- 播放直链目前酷狗平台要求设备签名验证，公开接口无法稳定获取，
  获取失败时返回 None，由上层提示用户登录/换平台。
"""
import warnings

import requests

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 该域名存在证书问题（HTTPS 握手失败），改用 HTTP；搜索数据已验证可用
SEARCH_API = "http://mobilecdn.kugou.com/api/v3/search/song"

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)


class KugouClient:
    def __init__(self, cookie=None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        if cookie:
            for item in cookie.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    self.session.cookies.set(k, v)

    def search(self, keyword: str, limit: int = 10):
        """搜索歌曲，返回 [{hash, name, artists, album}]"""
        try:
            r = self.session.get(
                SEARCH_API,
                params={
                    "format": "json",
                    "keyword": keyword,
                    "page": 1,
                    "pagesize": limit,
                    "showtype": 1,
                },
                timeout=10,
            )
            data = r.json()
        except Exception as e:
            print(f"[酷狗] 搜索失败: {e}")
            return []

        songs = []
        for item in (data.get("data") or {}).get("info") or []:
            songs.append({
                "hash": item.get("hash"),
                "name": item.get("songname") or item.get("filename", "").split("-")[-1].strip(),
                "artists": item.get("singername"),
                "album": item.get("album_name", ""),
                "album_id": item.get("album_id"),
            })
        return songs

    def get_play_url(self, song_hash: str, album_id=None):
        """获取播放直链（酷狗接口受限，尽力获取，失败返回 None）"""
        # 方式一：移动端播放信息接口
        try:
            r = self.session.get(
                "https://m.kugou.com/app/i/getSongInfo.php",
                params={"cmd": "playInfo", "hash": song_hash,
                        "album_id": album_id or ""},
                timeout=10,
            )
            j = r.json()
            url = (j.get("url") or "").strip()
            if url:
                return url
        except Exception:
            pass

        # 方式二：网页版播放数据接口
        try:
            r = self.session.get(
                "https://wwwapi.kugou.com/yy/index.php",
                params={"r": "play/getdata", "hash": song_hash,
                        "album_id": album_id or ""},
                timeout=10,
            )
            j = r.json()
            d = j.get("data") or {}
            url = (d.get("play_url") or "").strip() if isinstance(d, dict) else ""
            if url:
                return url
        except Exception:
            pass

        print("[酷狗] 获取播放链接失败：酷狗平台当前限制公开接口，请使用其他平台")
        return None
