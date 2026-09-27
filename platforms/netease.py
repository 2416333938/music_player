"""网易云音乐客户端 —— 基于 pyncm"""
from pyncm import apis
from pyncm import GetCurrentSession, SetCurrentSession, CreateNewSession
from pyncm.apis.login import (
    LoginViaCellphone,
    LoginViaAnonymousAccount,
    LoginViaCookie,
)


class NeteaseClient:
    def __init__(self, cookie=None):
        self.session = CreateNewSession()
        SetCurrentSession(self.session)
        self.logged_in = False
        if cookie:
            try:
                # MUSIC_U 是网易云的登录凭证值（不是完整 Cookie 串）
                LoginViaCookie(MUSIC_U=cookie)
                self.logged_in = True
            except Exception:
                # 凭证无效时退化为直接写入 session cookie，仍可匿名搜索
                self.session.cookies.set("MUSIC_U", cookie)
                self.logged_in = True
        else:
            LoginViaAnonymousAccount()

    def login_by_phone(self, phone: str, password: str):
        """手机号登录"""
        LoginViaCellphone(phone=phone, password=password)
        self.logged_in = True
        return True

    def search(self, keyword: str, limit: int = 10):
        """搜索歌曲，返回 [{id, name, artists, album}]"""
        result = apis.cloudsearch.GetSearchResult(keyword, stype=1, limit=limit)
        songs = []
        for item in result["result"]["songs"]:
            songs.append({
                "id": item["id"],
                "name": item["name"],
                "artists": "/".join(a["name"] for a in item["ar"]),
                "album": item["al"]["name"],
            })
        return songs

    def get_play_url(self, song_id: int):
        """获取播放直链（pyncm 的 GetTrackAudio 接收歌曲 id 列表）"""
        result = apis.track.GetTrackAudio([song_id])
        if result.get("data") and result["data"][0].get("url"):
            return result["data"][0]["url"]
        return None
