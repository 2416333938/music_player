"""无头启动自检：把界面搭起来并跑几轮事件循环，检查基本控件都在。

用法： python selftest.py
"""
import os
import sys
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:                                     # 控制台按 UTF-8 输出，避免 GBK 报错
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tkinter as tk  # noqa: E402

FAILURES = []

ICON_NAMES = [
    "play", "pause", "stop", "next", "prev", "sequential", "shuffle",
    "repeat_one", "volume", "volume_mute", "plus", "minus", "close",
    "check", "search", "download", "trash", "music", "list", "folder",
    "gear", "more", "refresh", "chevron_right", "warning", "info",
]


def check(condition, label):
    status = "OK  " if condition else "FAIL"
    if not condition:
        FAILURES.append(label)
    print(f"[{status}] {label}")


def main():
    print("=== 1. 模块导入 ===")
    import theme as T
    import icons
    import widgets as W
    import tray
    import play_queue
    import downloader
    import player
    import app_gui

    for name, module in [("theme", T), ("icons", icons), ("widgets", W),
                         ("tray", tray), ("play_queue", play_queue),
                         ("downloader", downloader), ("player", player),
                         ("app_gui", app_gui)]:
        check(module is not None, f"import {name}")

    print("\n=== 2. 纯逻辑：曲目模型 / 歌单存储 ===")
    raw = {"id": 123, "name": "测试歌曲", "artists": "歌手A/歌手B",
           "album": "专辑X"}
    track = tray.make_track("netease", raw)
    check(track["id"] == "123" and track["title"] == "测试歌曲",
          "make_track 标准化")
    check(tray.track_key(track) == "netease::123", "track_key")
    check(tray.download_filename(track) == "歌手A/歌手B - 测试歌曲 [网易云].mp3"
          .replace("/", "_"), "下载文件名合法化")

    bili = tray.make_track("bilibili", {"bvid": "BV1xx", "title": "视频",
                                        "author": "UP主"})
    check(bili["id"] == "BV1xx" and bili["artists"] == "UP主",
          "B站曲目映射")

    tmp_store = os.path.join(BASE_DIR, "_selftest_playlists.json")
    if os.path.exists(tmp_store):
        os.unlink(tmp_store)
    store = tray.PlaylistStore(tmp_store)
    pl = store.create("自检歌单")
    added, skipped = store.add_tracks(pl["id"], [track, track])
    check(added == 1 and skipped == 1, f"去重加入（added={added} skipped={skipped}）")
    check(store.track_count(pl["id"]) == 1, "歌单曲目数")
    check(store.get(pl["id"])["name"] == "自检歌单", "歌单名")
    store.set_active(pl["id"])
    reopened = tray.PlaylistStore(tmp_store)
    check(len(reopened.playlists) == 1 and
          reopened.track_count(reopened.playlists[0]["id"]) == 1,
          "重新读取持久化数据")
    check(reopened.rename(pl["id"], "改名后的歌单"), "重命名")
    check(reopened.move_track(pl["id"], 0, 1) == 0, "移动越界保护")
    check(reopened.delete(pl["id"]), "删除歌单")
    os.unlink(tmp_store)

    print("\n=== 3. 播放模式逻辑（假播放器） ===")

    class FakePlayer:
        def __init__(self):
            self.on_state = None
            self.on_finished = None
            self.played = []

        def play(self, source, title="", is_url=True):
            self.played.append(source)
            if self.on_state:
                self.on_state("playing")

        def stop(self):
            pass

        def pause(self):
            pass

        def resume(self):
            pass

        def toggle_pause(self):
            return True

        def get_state(self):
            return {"playing": False, "paused": False, "loading": False,
                    "position": 0.0, "duration": 0.0, "current": None}

        def set_volume(self, value):
            pass

        def get_volume(self):
            return 0.7

        def set_clients(self, clients):
            pass

    items = [tray.make_track("netease", {"id": i, "name": f"歌{i}",
                                         "artists": "X", "album": "Y"})
             for i in range(3)]
    for item in items:
        item["local_path"] = __file__          # 假装已下载，跳过取地址

    fp = FakePlayer()
    q = play_queue.PlayQueue(fp, clients={}, mode="sequential")

    # 顺序播放：放完最后一首应该停
    q.load(items, 0, "自检")
    for _ in range(200):
        if q._token:
            pass
        import time
        time.sleep(0.01)
        break
    check(q.index == 0, "装载后索引为 0")
    order = []
    for _ in range(5):
        before = q.index
        q._handle_finished()
        import time
        time.sleep(0.05)
        order.append((before, q.index))
    check(q.index == 2, f"顺序播放走到最后一首（index={q.index}）")
    check(q._stopped is True, "顺序播放到末尾自动停止")

    # 单曲循环
    q2 = play_queue.PlayQueue(FakePlayer(), clients={}, mode="repeat_one")
    q2.load(items, 0, "自检")
    import time
    time.sleep(0.05)
    q2._handle_finished()
    time.sleep(0.05)
    check(q2.index == 0 and not q2._stopped, "单曲循环保持同一首")

    # 随机播放
    q3 = play_queue.PlayQueue(FakePlayer(), clients={}, mode="shuffle")
    q3.load(items, 0, "自检")
    time.sleep(0.05)
    seen = {q3.index}
    for _ in range(10):
        q3._handle_finished()
        time.sleep(0.03)
        seen.add(q3.index)
        if q3._stopped:
            break
    check(len(seen) == 3, f"随机播放覆盖全部曲目（{sorted(seen)}）")
    check(q3._stopped is True, "随机播放一轮后停止")

    # 模式循环切换
    modes = [q.cycle_mode() for _ in range(3)]
    check(modes == ["shuffle", "repeat_one", "sequential"],
          f"模式循环切换 {modes}")

    print("\n=== 4. 矢量图标逐个绘制 ===")
    root = tk.Tk()
    root.withdraw()
    probe = tk.Canvas(root, width=64, height=64)
    bad_icons = []
    for name in ICON_NAMES:
        try:
            probe.delete("all")
            ids = icons.draw_icon(probe, name, 32, 32, 22, "#ffffff")
            if not ids:
                bad_icons.append(f"{name}(空)")
        except Exception as exc:
            bad_icons.append(f"{name}({exc})")
    check(not bad_icons, f"全部 {len(ICON_NAMES)} 个图标可绘制"
                         + (f" — 异常: {bad_icons}" if bad_icons else ""))

    print("\n=== 5. 界面构建 ===")
    app = None
    try:
        app = app_gui.PlayerApp(root)
        for _ in range(12):
            root.update()
        check(app.search_tree is not None, "搜索曲目表存在")
        check(app.playlist_tree is not None, "歌单曲目表存在")
        check(app.library_tree is not None, "全部音乐表存在")
        check(app.mode_btn is not None, "播放模式按钮存在")
        check(app.seekbar is not None, "进度条存在")
        check(len(app.nav_buttons) == 3, "侧边栏导航 3 项")

        # 各视图切换
        for view in (app_gui.VIEW_LIBRARY, app_gui.VIEW_PLAYLIST,
                     app_gui.VIEW_DOWNLOAD, app_gui.VIEW_SEARCH):
            app._switch_view(view)
            root.update()
        check(True, "四个视图切换无异常")

        # 填入搜索结果
        app._display_results({"netease": items, "bilibili": [bili]}, {},
                             "自检关键词")
        root.update()
        check(len(app.search_tree.get_children()) == 4, "搜索结果渲染 4 行")
        check(len(app._library_tracks()) == 4, "全部音乐缓存 4 首")

        # 歌单：新建 → 加入 → 渲染
        pl = app.store.create("自检歌单")
        app.store.set_active(pl["id"])
        app._refresh_playlists()
        app._add_tracks_to_playlist(pl["id"], items)
        app._refresh_playlist_view()
        app._switch_view(app_gui.VIEW_PLAYLIST)
        root.update()
        check(len(app.playlist_tree.get_children()) == 3, "歌单视图渲染 3 行")

        # 播放模式按钮
        for _ in range(3):
            app._cycle_mode()
            root.update()
        check(app.queue.mode == "sequential", "点击模式按钮循环一圈")

        # 下载行渲染
        app.downloads.enqueue(items, playlist_id=pl["id"])
        app._refresh_downloads()
        root.update()
        check(len(app._download_rows) == 3, "下载队列渲染 3 行")

        app.store.delete(pl["id"])
        app._refresh_playlists()
        root.update()
    except Exception:
        traceback.print_exc()
        import tkinter as _tk
        FAILURES.append("界面构建异常")
        try:
            print("DEBUG: 顶层窗口列表:",
                  [str(w) for w in root.winfo_children()])
            print("DEBUG: 出错控件 self =", repr(getattr(
                sys.exc_info()[2].tb_next, "tb_frame", None)))
        except Exception:
            pass
    finally:
        try:
            if app is not None:
                app.marquee.stop()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    print("\n=== 结果 ===")
    if FAILURES:
        print(f"❌ {len(FAILURES)} 项失败:")
        for item in FAILURES:
            print("   -", item)
        return 1
    print("✅ 全部自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
