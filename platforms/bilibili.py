"""B站音频客户端 —— 基于 bilibili-api-python"""
import asyncio
from bilibili_api import video, search, Credential


def _parse_duration(item: dict) -> int:
    """搜索结果里的时长可能是 '12:34' / '1:02:03' / 秒数，统一成秒"""
    raw = item.get("duration")
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return 0
        if ":" in raw:
            total = 0
            try:
                for part in raw.split(":"):
                    total = total * 60 + int(part.strip())
            except ValueError:
                return 0
            return total
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


class BilibiliClient:
    def __init__(self, sessdata=None, bili_jct=None):
        if sessdata:
            self.credential = Credential(sessdata=sessdata, bili_jct=bili_jct)
        else:
            self.credential = None

    async def search_videos(self, keyword: str, limit: int = 10):
        """搜索视频，返回 BV 号列表

        title 里带 B 站的 <em> 高亮标记，交给上层 tray.make_track 统一清理。
        """
        results = await search.search_by_type(
            keyword, search_type=search.SearchObjectType.VIDEO,
            page=1, page_size=limit
        )
        videos = []
        for item in results.get("result", [])[:limit]:
            pic = item.get("pic") or ""
            if pic.startswith("//"):
                pic = "https:" + pic
            videos.append({
                "bvid": item.get("bvid"),
                "title": item.get("title"),
                "author": item.get("author"),
                "duration": _parse_duration(item),
                "cover": pic,
            })
        return videos

    async def get_audio_url(self, bvid: str):
        """获取视频的音频流地址"""
        v = video.Video(bvid=bvid, credential=self.credential)
        # 新版 bilibili-api：get_playurl 已更名为 get_download_url
        play_data = await v.get_download_url(0)
        # 优先使用 dash 音频流
        dash = play_data.get("dash") or {}
        audio_streams = dash.get("audio") or []
        if audio_streams:
            # 选择最高码率的音频流
            best = max(audio_streams, key=lambda x: x.get("bandwidth", 0))
            return best.get("baseUrl") or best.get("base_url")
        # 兜底：普通 FLV/MP4 流
        durl = play_data.get("durl") or []
        if durl:
            return durl[0].get("url")
        return None