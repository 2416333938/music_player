"""汽水音乐客户端 —— 直接调用 PC 端接口"""
import requests
import json


class QishuiClient:
    BASE = "https://api.qishui.com"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    def __init__(self, cookie=None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.UA})
        if cookie:
            for item in cookie.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    self.session.cookies.set(k, v)

    def search(self, keyword: str, limit: int = 10):
        """搜索歌曲"""
        url = f"{self.BASE}/luna/pc/search/track"
        params = {"q": keyword, "cursor": 0, "count": limit}
        try:
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            songs = []
            for item in data.get("data", {}).get("list", []):
                track = item.get("track", {})
                songs.append({
                    "id": track.get("id"),
                    "name": track.get("name"),
                    "artists": "/".join(a.get("name", "") for a in track.get("artists", [])),
                    "album": track.get("album", {}).get("name", ""),
                })
            return songs
        except Exception as e:
            print(f"[汽水音乐] 搜索失败: {e}")
            return []

    def get_play_url(self, track_id: str):
        """获取播放直链（可能返回加密内容，需额外解密）"""
        url = f"{self.BASE}/luna/pc/track_v2"
        params = {"track_id": track_id}
        try:
            r = self.session.get(url, params=params, timeout=10)
            data = r.json()
            return data.get("data", {}).get("url")
        except Exception as e:
            print(f"[汽水音乐] 获取播放链接失败: {e}")
            return None