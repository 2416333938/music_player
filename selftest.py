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

# 自检会写账号/歌单，跑之前把真实文件挪开，跑完再放回去
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONFIG_BACKUP = CONFIG_FILE + ".selftest-backup"
PLAYLIST_FILE = os.path.join(BASE_DIR, "playlists.json")
PLAYLIST_BACKUP = PLAYLIST_FILE + ".selftest-backup"


def _stash_real_files():
    for path, backup in ((CONFIG_FILE, CONFIG_BACKUP),
                         (PLAYLIST_FILE, PLAYLIST_BACKUP)):
        try:
            if os.path.exists(backup):
                os.unlink(backup)
            if os.path.exists(path):
                os.replace(path, backup)
        except Exception as exc:
            print(f"[自检] 备份 {os.path.basename(path)} 失败: {exc}")


def _restore_real_files():
    for path, backup in ((CONFIG_FILE, CONFIG_BACKUP),
                         (PLAYLIST_FILE, PLAYLIST_BACKUP)):
        try:
            if os.path.exists(path):
                os.unlink(path)
            if os.path.exists(backup):
                os.replace(backup, path)
        except Exception as exc:
            print(f"[自检] 还原 {os.path.basename(path)} 失败: {exc}")


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
    print("=== 0. 保护真实数据 ===")
    _stash_real_files()
    print(f"[OK  ] 真实 config.json / playlists.json 已临时移开，"
          f"跑完自动还原")
    try:
        return _run_checks()
    finally:
        _restore_real_files()


def _run_checks():
    print("\n=== 1. 模块导入 ===")
    import theme as T
    import icons
    import widgets as W
    import tray
    import play_queue
    import downloader
    import player
    import accounts
    import cover
    import cards
    import feed
    import updater
    import app_gui

    FEED = feed
    CARD_MODULE = cards

    for name, module in [("theme", T), ("icons", icons), ("widgets", W),
                         ("tray", tray), ("play_queue", play_queue),
                         ("downloader", downloader), ("player", player),
                         ("accounts", accounts), ("cover", cover),
                         ("cards", cards), ("feed", feed),
                         ("updater", updater), ("app_gui", app_gui)]:
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

    print("\n=== 5. 账号管理逻辑（纯逻辑，不碰真实 config.json） ===")
    import accounts as A

    cfg = {"netease": {"cookie": "", "accounts": [], "current": ""},
           "qqmusic": {"cookie": "", "accounts": [], "current": ""},
           "kugou": {"cookie": "", "accounts": [], "current": ""},
           "qishui": {"cookie": "", "accounts": [], "current": ""},
           "bilibili": {"sessdata": "", "bili_jct": "",
                        "accounts": [], "current": ""}}
    store = A.AccountStore(cfg, save=None)

    acc1, created1 = store.add("netease", {"cookie": "MUSIC_U=AAA"},
                               label="小号", method="cookie")
    check(acc1 is not None and created1, "新增账号成功")
    check(store.current_id("netease") == acc1["id"], "第一个账号自动成为当前账号")
    check(cfg["netease"]["cookie"] == "MUSIC_U=AAA",
          "旧字段被同步（向后兼容）")

    # 同凭据重复添加 → 更新而不是新建
    again, created2 = store.add("netease", {"cookie": "MUSIC_U=AAA"},
                                label="小号改名")
    check(not created2 and again["id"] == acc1["id"], "同凭据不会重复建账号")
    check(again["label"] == "小号改名", "同凭据会更新标签")

    # 第二个账号
    acc2, _ = store.add("netease", {"cookie": "MUSIC_U=BBB"}, label="大号")
    check(len(store.accounts("netease")) == 2, "一个平台可存 2 个账号")
    check(store.current_id("netease") == acc2["id"], "新账号成为当前账号")

    # 切回第一个
    check(store.set_current("netease", acc1["id"]), "切换账号成功")
    check(store.current_cred("netease")["cookie"] == "MUSIC_U=AAA",
          "切换后取到正确凭据")
    check(cfg["netease"]["cookie"] == "MUSIC_U=AAA", "切换后旧字段同步更新")

    # 「更新当前账号」路径
    updated, created3 = store.add("netease", {"cookie": "MUSIC_U=CCC"},
                                  label="小号", prefer_id=acc1["id"])
    check(not created3 and updated["id"] == acc1["id"],
          "prefer_id 走更新而不是新增")
    check(store.current_cred("netease")["cookie"] == "MUSIC_U=CCC",
          "更新后凭据生效")
    check(len(store.accounts("netease")) == 2, "更新不会增加账号数")

    # 退出登录 / 再切回来
    check(store.clear_current("netease"), "退出登录")
    check(store.current("netease") is None, "退出后没有当前账号")
    check(len(store.accounts("netease")) == 2, "退出登录不删账号记录")
    check(cfg["netease"]["cookie"] == "", "退出后旧字段被清空")
    store.set_current("netease", acc2["id"])
    check(store.current_cred("netease")["cookie"] == "MUSIC_U=BBB",
          "退出后仍可切回")

    # 删除当前账号 → 自动切到剩下的
    store.remove("netease", acc2["id"])
    check(len(store.accounts("netease")) == 1, "删除账号成功")
    check(store.current_id("netease") == acc1["id"],
          "删除当前账号后自动切到剩下的")

    # B站双字段
    bacc, _ = store.add("bilibili", {"sessdata": "SESS-XYZ",
                                     "bili_jct": "JCT-123"}, label="B站号")
    check(store.client_kwargs("bilibili")["sessdata"] == "SESS-XYZ",
          "B站 client_kwargs 正确")
    check("cookie" not in store.client_kwargs("bilibili"),
          "B站 client_kwargs 不含 cookie")
    check(store.client_kwargs("netease") == {"cookie": "MUSIC_U=CCC"},
          "网易云 client_kwargs 正确")

    # 凭据校验
    bad, bad_created = store.add("bilibili", {"bili_jct": "只有jct没有sessdata"})
    check(bad is None and not bad_created, "缺关键字段的凭据会被拒绝")

    # 旧配置迁移
    legacy = {"netease": {"cookie": "OLD-MUSIC-U", "accounts": [],
                          "current": ""},
              "bilibili": {"sessdata": "OLD-SESS", "bili_jct": "OLD-JCT",
                           "accounts": [], "current": ""},
              "qqmusic": {"cookie": "", "accounts": [], "current": ""},
              "kugou": {"cookie": "", "accounts": [], "current": ""},
              "qishui": {"cookie": "", "accounts": [], "current": ""}}
    migrated = A.AccountStore(legacy, save=None).migrate_legacy()
    check(migrated == 2, f"旧配置迁移 2 条（实际 {migrated}）")
    migrated_store = A.AccountStore(legacy, save=None)
    check(migrated_store.current_cred("netease")["cookie"] == "OLD-MUSIC-U",
          "迁移后网易云凭据可用")
    check(migrated_store.current_cred("bilibili")["sessdata"] == "OLD-SESS",
          "迁移后 B站凭据可用")
    check(A.AccountStore(legacy, save=None).migrate_legacy() == 0,
          "重复迁移不会产生重复账号")

    # 账号摘要
    summary = store.summary_text()
    check("已登录" in summary or "未登录" in summary,
          f"侧边栏摘要文案可用：{summary}")
    counts = store.counts()
    check(set(counts.keys()) == set(app_gui.T.PLATFORM_KEYS),
          "counts() 覆盖 5 个平台")

    print("\n=== 6. 自动更新逻辑（不联网，只测解析与策略） ===")
    import updater as U

    check(U.parse_version("v2.1.0") == (2, 1, 0), "版本号解析 v2.1.0")
    check(U.parse_version("2.0") == (2, 0, 0), "版本号补零 2.0 → 2.0.0")
    check(U.parse_version("") == (0, 0, 0), "空版本号容错")
    check(U.parse_version("1.10.3") > U.parse_version("1.9.9"),
          "版本号比较 1.10.3 > 1.9.9（不是字符串比较）")
    check(U.is_newer("2.1.0", "2.0.0"), "检测到新版本")
    check(not U.is_newer("2.0.0", "2.0.0"), "同版本不算更新")
    check(not U.is_newer("1.9.0", "2.0.0"), "旧版本不算更新")

    # 两种更新源格式
    gh = U._normalize_manifest({
        "tag_name": "v3.0.0", "body": "更新说明",
        "html_url": "https://example.com/rel",
        "assets": [{"name": "app.zip",
                    "browser_download_url": "https://example.com/app.zip"}]})
    check(gh["version"] == "v3.0.0" and gh["url"].endswith("app.zip"),
          "GitHub Releases 格式解析")
    plain = U._normalize_manifest({"version": "2.5", "notes": "说明",
                                   "url": "https://example.com/a.zip"})
    check(plain["version"] == "2.5" and plain["notes"] == "说明",
          "自定义 JSON 清单解析")

    # 关闭 / 没源 / 检查间隔
    info = U.check_for_update("2.0.0", "https://example.com/x", enabled=False)
    check(info.status == U.STATUS_DISABLED, "关掉开关就不再检查")
    check(not info.has_update, "关闭状态没有更新")
    info2 = U.check_for_update("2.0.0", "", enabled=True)
    check(info2.status == U.STATUS_NO_SOURCE, "没填更新源时的状态")
    info3 = U.check_for_update("2.0.0", "https://127.0.0.1:9/nope",
                               enabled=True, timeout=2)
    check(info3.status == U.STATUS_ERROR and info3.error,
          f"取不到清单时优雅报错（{info3.error[:40]}）")

    app_cfg = {"auto_update": True, "update_interval_hours": 24,
               "last_update_check": 0}
    check(U.should_check(app_cfg), "从没检查过 → 应该检查")
    U.mark_checked(app_cfg)
    check(not U.should_check(app_cfg), "刚检查过 → 不再重复检查")
    check(U.should_check(app_cfg, force=True), "手动强制检查")
    app_cfg["auto_update"] = False
    check(not U.should_check(dict(app_cfg, last_update_check=0)),
          "开关关闭时不自动检查")

    print("\n=== 7. 封面与首页内容（本地生成，不联网） ===")
    import cover as CV
    check(CV.url_key("http://a/b.jpg") == CV.url_key("http://a/b.jpg"),
          "同一地址的缓存 key 稳定")
    check(CV.url_key("http://a/b.jpg") != CV.url_key("http://a/c.jpg"),
          "不同地址 key 不同")
    art1 = CV.make_art("周杰伦 - 晴天", 120)
    art2 = CV.make_art("周杰伦 - 晴天", 120)
    art3 = CV.make_art("陈奕迅 - 浮夸", 120)
    check(art1 is not None and art1.size == (120, 120), "兜底封面可生成")
    if art1 is not None and art2 is not None and art3 is not None:
        check(list(art1.getdata()) == list(art2.getdata()),
              "同一曲目的兜底封面完全一致（确定性）")
        check(list(art1.getdata()) != list(art3.getdata()),
              "不同曲目的兜底封面不一样")

    library = [tray.make_track("netease",
                               {"id": i, "name": f"歌{i}",
                                "artists": "歌手", "album": "专辑",
                                "duration": 180})
               for i in range(40)]
    daily1 = FEED.build_daily(library, [])
    daily2 = FEED.build_daily(library, [])
    check(len(daily1) == 30, f"每日推荐数量（{len(daily1)}）")
    check([t["id"] for t in daily1] == [t["id"] for t in daily2],
          "同一天内每日推荐结果固定")
    check(len({t["id"] for t in daily1}) == len(daily1), "每日推荐不重复")
    check(len(FEED.build_guess(library, daily1[:5], None)) == 30,
          "猜你喜欢有结果")
    check(FEED.build_daily([], []) == [], "音乐库为空时每日推荐为空")
    check(FEED.build_recent(daily1[:5], 3) == daily1[:3], "最近播放截断正确")
    check(FEED.station_cover(daily1) == "", "无封面时返回空串")
    track_with_cover = dict(library[0], cover="http://x/y.jpg")
    check(FEED.station_cover([track_with_cover]) == "http://x/y.jpg",
          "有封面时能取到")
    check(CARD_MODULE.make_badge_count(12345) == "1.2万",
          "播放量格式化 12345 → 1.2万")
    check(CARD_MODULE.make_badge_count(999) == "999", "播放量格式化 999")

    print("\n=== 8. 音频格式识别与文件修复 ===")
    import downloader as DL
    import player as PL
    import repair as RP
    import shutil as _sh
    import tempfile

    work = tempfile.mkdtemp(prefix="audio_selftest_")
    try:
        # --- 构造各种格式的样本，检查嗅探是否正确 ---
        mp3_head = b"\xff\xfb\x90\x00" + b"\x00" * 400
        mp4_head = (b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32 +
                    b"\x00\x00\x00\x08moov" + b"\x00" * 400)
        flac_head = b"fLaC" + b"\x00" * 400
        ogg_head = b"OggS" + b"\x00" * 4 + b"OpusHead" + b"\x00" * 400

        samples = {"s.mp3": (mp3_head, "mp3"),
                   "s.m4a": (mp4_head, "mp4"),
                   "s.flac": (flac_head, "flac"),
                   "s.opus": (ogg_head, "opus")}
        for name, (data, want) in samples.items():
            path = os.path.join(work, name)
            with open(path, "wb") as fh:
                fh.write(data)
            got = DL.sniff_container(path)
            check(got == want, f"格式嗅探 {name} → {got}（期望 {want}）")

        # --- 扩展名和真实格式不符时自动改名 ---
        wrong = os.path.join(work, "wrong.mp3")
        with open(wrong, "wb") as fh:
            fh.write(mp4_head)
        fixed_path = DL.ensure_correct_extension(wrong)
        check(fixed_path.endswith(".m4a"),
              f"mp4 内容用 .mp3 后缀会被改名（{os.path.basename(fixed_path)}）")
        check(not os.path.exists(wrong), "改名后旧路径不存在")

        # --- 复现「ID3 头 + MP4 数据」的损坏场景 ---
        id3 = b"ID3\x03\x00\x00\x00\x00\x00\x2a" + b"\x00" * 42   # 52 字节
        broken = os.path.join(work, "broken.mp3")
        with open(broken, "wb") as fh:
            fh.write(id3 + mp4_head)
        check(RP.needs_repair(broken), "能识别出被写坏的文件")
        check(not RP.needs_repair(os.path.join(work, "s.m4a")),
              "正常 m4a 不会被误判")
        check(not RP.needs_repair(os.path.join(work, "s.mp3")),
              "正常 mp3 不会被误判")

        ok, info = RP.strip_id3_copy(broken)
        check(ok, f"修复成功（{info if not ok else 'ok'}）")
        if ok:
            check(os.path.getsize(info) == len(mp4_head),
                  f"修复后大小精确等于原始音频（{os.path.getsize(info)} "
                  f"vs {len(mp4_head)}）")
            check(DL.sniff_container(info) == "mp4", "修复后格式正确")
            check(os.path.exists(broken + ".broken"), "原文件保留为 .broken")
            check(not RP.needs_repair(info), "修复后不再需要修复")

        # --- 正常的 mp3 走 convert_to_mp3 不该崩（缺 ffmpeg 就返回 None）---
        result = PL.convert_to_mp3(os.path.join(work, "s.mp3"))
        check(result is None or isinstance(result, str),
              "convert_to_mp3 对无效音频优雅返回")

        # --- 扫描修复 ---
        scan_dir = os.path.join(work, "scan")
        os.makedirs(scan_dir)
        with open(os.path.join(scan_dir, "a.mp3"), "wb") as fh:
            fh.write(id3 + mp4_head)
        with open(os.path.join(scan_dir, "b.mp3"), "wb") as fh:
            fh.write(mp3_head)
        scan = RP.scan_and_repair(scan_dir)
        check(scan["scanned"] == 2, f"扫描到 2 个文件（{scan['scanned']}）")
        check(len(scan["fixed"]) == 1, "修复了 1 个坏文件")
        check(len(scan["failed"]) == 0, "没有修复失败")
    finally:
        _sh.rmtree(work, ignore_errors=True)

    print("\n=== 9. 界面构建 ===")
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
        check(len(app.nav_buttons) == 6,
              f"侧边栏导航 6 项（实际 {len(app.nav_buttons)}）")
        check(app.acct_inner is not None, "账号管理视图存在")
        check(app.home_grid is not None, "首页「猜你喜欢」区域存在")
        check(len(app.category_row.cards) == len(FEED.CATEGORY_CARDS),
              "首页分类卡片已渲染")
        check(app.search_entry is not None, "顶部搜索框存在")
        check(app.back_btn is not None and app.forward_btn is not None,
              "前进 / 后退按钮存在")
        check(app.top_account_label is not None, "顶部账号区存在")

        # 各视图切换
        for view in (app_gui.VIEW_LIBRARY, app_gui.VIEW_PLAYLIST,
                     app_gui.VIEW_DOWNLOAD, app_gui.VIEW_ACCOUNTS,
                     app_gui.VIEW_LOCAL, app_gui.VIEW_SEARCH,
                     app_gui.VIEW_HOME):
            app._switch_view(view)
            root.update()
        check(True, "七个视图切换无异常")
        check(len(app._nav_stack) > 3, "浏览历史已记录")
        app._nav_back()
        root.update()
        app._nav_forward()
        root.update()
        check(True, "前进 / 后退可用")

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

        # 账号管理：加两个账号 → 渲染 → 切换 → 删除
        a1, _ = app.accounts.add("netease", {"cookie": "SELFTEST-AAA"},
                                 label="自检号A", method="cookie")
        a2, _ = app.accounts.add("netease", {"cookie": "SELFTEST-BBB"},
                                 label="自检号B", method="cookie")
        app.accounts.add("bilibili", {"sessdata": "SELFTEST-SESS",
                                      "bili_jct": "SELFTEST-JCT"},
                         label="自检B站号", method="qr")
        app._switch_view(app_gui.VIEW_ACCOUNTS)
        root.update()
        check(len(app.accounts.accounts("netease")) == 2, "界面层存了 2 个网易云账号")
        check(app.accounts.current_id("netease") == a2["id"],
              "最后添加的账号成为当前账号")
        check(app.accounts.current("bilibili") is not None,
              "B站账号已保存")

        # 切换账号 → 客户端重建
        app._switch_account("netease", a1["id"])
        root.update()
        check(app.accounts.current_id("netease") == a1["id"], "切换账号生效")
        check("netease" in app.clients, "切换后客户端仍可用")
        check(app.active_accounts.get("netease") == "自检号A",
              f"当前账号标签正确（{app.active_accounts.get('netease')}）")
        check("已登录" in app.login_status.cget("text"),
              f"侧边栏状态已刷新：{app.login_status.cget('text')}")

        # 退出登录
        app.accounts.clear_current("netease")
        app._init_clients()
        app._refresh_accounts()
        root.update()
        check(app.accounts.current("netease") is None, "退出登录生效")
        check(len(app.accounts.accounts("netease")) == 2,
              "退出登录保留账号记录")

        # 清理自检数据，避免污染真实 config
        for platform in ("netease", "bilibili"):
            for account in list(app.accounts.accounts(platform)):
                app.accounts.remove(platform, account["id"])
        app._refresh_accounts()
        root.update()
        check(not app.accounts.accounts("netease"), "自检账号已清理")

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
        print(f"[FAIL] {len(FAILURES)} 项失败:")
        for item in FAILURES:
            print("   -", item)
        return 1
    print("[OK] 全部自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
