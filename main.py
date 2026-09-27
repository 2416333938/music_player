"""主程序 —— 命令行交互"""
import asyncio
from config import load_config, save_config
from platforms.netease import NeteaseClient
from platforms.qqmusic import QQMusicClient
from platforms.kugou import KugouClient
from platforms.qishui import QishuiClient
from platforms.bilibili import BilibiliClient
from player import MusicPlayer


class MusicApp:
    def __init__(self):
        self.cfg = load_config()
        self.player = MusicPlayer()
        self.clients = {}
        self.last_results = {}        # 保存最近一次搜索结果，供 play 命令使用
        self._init_clients()

    def _init_clients(self):
        if self.cfg["netease"]["cookie"]:
            self.clients["netease"] = NeteaseClient(self.cfg["netease"]["cookie"])
        else:
            self.clients["netease"] = NeteaseClient()

        self.clients["qqmusic"] = QQMusicClient(
            self.cfg["qqmusic"].get("cookie") or None
        )
        self.clients["kugou"] = KugouClient(
            self.cfg["kugou"].get("cookie") or None
        )
        self.clients["qishui"] = QishuiClient(
            self.cfg["qishui"].get("cookie") or None
        )
        self.clients["bilibili"] = BilibiliClient(
            self.cfg["bilibili"].get("sessdata"),
            self.cfg["bilibili"].get("bili_jct")
        )

    def search_all(self, keyword: str, limit: int = 5):
        """跨平台搜索"""
        print(f"\n🔍 搜索: {keyword}\n")
        results = {}

        # 网易云
        try:
            netease_songs = self.clients["netease"].search(keyword, limit)
            results["netease"] = netease_songs
            print(f"【网易云】共 {len(netease_songs)} 条")
            for i, s in enumerate(netease_songs):
                print(f"  {i}. {s['name']} - {s['artists']}")
        except Exception as e:
            print(f"【网易云】搜索失败: {e}")

        # QQ音乐
        try:
            qq_songs = asyncio.run(self.clients["qqmusic"].search(keyword, limit))
            results["qqmusic"] = qq_songs
            print(f"\n【QQ音乐】共 {len(qq_songs)} 条")
            for i, s in enumerate(qq_songs):
                print(f"  {i}. {s['name']} - {s['artists']}")
        except Exception as e:
            print(f"【QQ音乐】搜索失败: {e}")

        # 酷狗
        try:
            kg_songs = self.clients["kugou"].search(keyword, limit)
            results["kugou"] = kg_songs
            print(f"\n【酷狗】共 {len(kg_songs)} 条")
            for i, s in enumerate(kg_songs):
                print(f"  {i}. {s['name']} - {s['artists']}")
        except Exception as e:
            print(f"【酷狗】搜索失败: {e}")

        # 汽水音乐
        try:
            qs_songs = self.clients["qishui"].search(keyword, limit)
            results["qishui"] = qs_songs
            print(f"\n【汽水音乐】共 {len(qs_songs)} 条")
            for i, s in enumerate(qs_songs):
                print(f"  {i}. {s['name']} - {s['artists']}")
        except Exception as e:
            print(f"【汽水音乐】搜索失败: {e}")

        self.last_results = results
        return results

    def search_bilibili(self, keyword: str, limit: int = 5):
        """搜索 B 站视频"""
        print(f"\n📺 B站搜索: {keyword}\n")
        try:
            videos = asyncio.run(
                self.clients["bilibili"].search_videos(keyword, limit)
            )
            for i, v in enumerate(videos):
                print(f"  {i}. {v['title']}  UP: {v['author']}  [{v['bvid']}]")
            self.last_results["bilibili"] = videos
            return videos
        except Exception as e:
            print(f"B站搜索失败: {e}")
            return []

    def play_bilibili(self, bvid: str):
        """播放 B 站视频的音频"""
        try:
            url = asyncio.run(
                self.clients["bilibili"].get_audio_url(bvid)
            )
            if url:
                print(f"▶ 正在播放 B站音频: {bvid}")
                self.player.play_url(url)
            else:
                print("无法获取音频地址")
        except Exception as e:
            print(f"播放失败: {e}")

    def play_index(self, platform: str, index: int):
        """播放搜索结果中的某一项"""
        songs = self.last_results.get(platform)
        if not songs:
            print("请先搜索该平台（search / bili）")
            return
        if index < 0 or index >= len(songs):
            print("索引超出范围")
            return

        item = songs[index]
        client = self.clients.get(platform)
        if client is None:
            print(f"平台 {platform} 不可用")
            return

        try:
            if platform == "netease":
                url = client.get_play_url(item["id"])
            elif platform == "qqmusic":
                url = asyncio.run(client.get_play_url(item["mid"]))
            elif platform == "kugou":
                url = client.get_play_url(item["hash"], item.get("album_id"))
            elif platform == "qishui":
                url = client.get_play_url(item["id"])
            elif platform == "bilibili":
                url = asyncio.run(client.get_audio_url(item["bvid"]))
            else:
                print("未知平台")
                return

            title = item.get("name") or item.get("title") or "未知"
            if url:
                print(f"▶ 正在播放: {title}")
                self.player.play_url(url)
            else:
                print(f"❌ 无法获取播放地址: {title}")
        except Exception as e:
            print(f"播放失败: {e}")


def main():
    app = MusicApp()
    print("=" * 50)
    print("  多平台音乐播放器")
    print("=" * 50)

    while True:
        print("\n命令:")
        print("  search <关键词>          —— 跨平台搜索音乐")
        print("  bili <关键词>            —— 搜索 B 站视频")
        print("  play <平台> <索引>       —— 播放搜索结果（如 play netease 0）")
        print("  playbili <bvid>          —— 播放 B 站视频音频")
        print("  login                    —— 配置登录信息")
        print("  quit                     —— 退出")

        cmd = input("\n> ").strip()
        if not cmd:
            continue
        if cmd == "quit":
            break
        if cmd == "login":
            configure_login(app.cfg)
            app._init_clients()
            continue

        parts = cmd.split(maxsplit=2)
        if parts[0] == "search" and len(parts) > 1:
            app.search_all(parts[1])
        elif parts[0] == "bili" and len(parts) > 1:
            app.search_bilibili(parts[1])
        elif parts[0] == "playbili" and len(parts) > 1:
            app.play_bilibili(parts[1])
        elif parts[0] == "play" and len(parts) >= 3:
            try:
                app.play_index(parts[1].lower(), int(parts[2]))
            except ValueError:
                print("索引必须是数字，例如 play netease 0")


def configure_login(cfg):
    """交互式配置登录信息"""
    print("\n选择平台: netease / qqmusic / kugou / qishui / bilibili")
    platform = input("平台: ").strip().lower()
    if platform == "bilibili":
        cfg["bilibili"]["sessdata"] = input("SESSDATA: ").strip()
        cfg["bilibili"]["bili_jct"] = input("bili_jct: ").strip()
    elif platform == "netease":
        # 网易云保存的是 MUSIC_U 值本身
        cfg["netease"]["cookie"] = input("MUSIC_U 值: ").strip().replace("MUSIC_U=", "")
    elif platform in cfg:
        cfg[platform]["cookie"] = input("Cookie: ").strip()
    save_config(cfg)
    print("✅ 已保存，客户端已刷新")


if __name__ == "__main__":
    main()
