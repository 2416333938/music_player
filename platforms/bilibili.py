"""B站音频客户端 —— 基于 bilibili-api-python"""
import asyncio
from bilibili_api import video, search, Credential


class BilibiliClient:
    def __init__(self, sessdata=None, bili_jct=None):
        if sessdata:
            self.credential = Credential(sessdata=sessdata, bili_jct=bili_jct)
        else:
            self.credential = None

    async def search_videos(self, keyword: str, limit: int = 10):
        """搜索视频，返回 BV 号列表"""
        results = await search.search_by_type(
            keyword, search_type=search.SearchObjectType.VIDEO,
            page=1, page_size=limit
        )
        videos = []
        for item in results.get("result", [])[:limit]:
            videos.append({
                "bvid": item.get("bvid"),
                "title": item.get("title"),
                "author": item.get("author"),
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