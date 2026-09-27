"""播放队列 + 播放模式

四种播放模式（与用户需求一一对应）：
- sequential ：顺序播放，放完整个列表后自动停止
- shuffle    ：随机播放，把列表随机打乱后放完即停
- repeat_one ：单曲循环，一直重复当前这一首
另外列表为空或只有一首歌时，行为退化为「单曲循环」。
"""
from __future__ import annotations

import random
import threading
import time

import tray
from player import MusicPlayer, find_cached

MODE_SEQUENTIAL = "sequential"
MODE_SHUFFLE = "shuffle"
MODE_REPEAT_ONE = "repeat_one"

MODE_ORDER = (MODE_SEQUENTIAL, MODE_SHUFFLE, MODE_REPEAT_ONE)

MODE_META = {
    MODE_SEQUENTIAL: {"label": "顺序播放", "icon": "sequential",
                      "hint": "按列表顺序播放，播完即停"},
    MODE_SHUFFLE:    {"label": "随机播放", "icon": "shuffle",
                      "hint": "随机打乱顺序播放，播完即停"},
    MODE_REPEAT_ONE: {"label": "单曲循环", "icon": "repeat_one",
                      "hint": "一直重复播放当前这首"},
}


def mode_label(mode: str) -> str:
    return MODE_META.get(mode, MODE_META[MODE_SEQUENTIAL])["label"]


def mode_icon(mode: str) -> str:
    return MODE_META.get(mode, MODE_META[MODE_SEQUENTIAL])["icon"]


def mode_hint(mode: str) -> str:
    return MODE_META.get(mode, MODE_META[MODE_SEQUENTIAL])["hint"]


# ============================================================
# 解析播放地址
# ============================================================
def resolve_play_url(platform: str, track: dict, clients: dict):
    """按平台取播放直链（同步函数，请在工作线程里调用）"""
    client = (clients or {}).get(platform)
    if client is None:
        raise RuntimeError(f"{tray.track_platform(track) or platform} 客户端未初始化")

    track_id = track.get("id")

    if platform == "netease":
        return client.get_play_url(int(track_id))

    if platform == "qqmusic":
        return _run_async(client.get_play_url(track_id))

    if platform == "kugou":
        album_id = track.get("album_id")
        try:
            return client.get_play_url(track_id, album_id)
        except TypeError:
            return client.get_play_url(track_id)

    if platform == "qishui":
        return client.get_play_url(track_id)

    if platform == "bilibili":
        return _run_async(client.get_audio_url(track_id))

    raise RuntimeError(f"未知平台: {platform}")


def _run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ResolveError(RuntimeError):
    """取播放地址失败"""


# ============================================================
# 播放队列
# ============================================================
class PlayQueue:
    """把「列表 + 播放模式 + 播放器」串起来"""

    def __init__(self, player: MusicPlayer, clients=None, mode=MODE_SEQUENTIAL,
                 on_track=None, on_state=None, on_mode=None, on_queue=None,
                 on_error=None):
        self.player = player
        self.clients = clients if clients is not None else {}

        self.items = []                 # 曲目 dict 列表
        self.source_name = ""           # 队列来源显示名（歌单名 / 搜索结果）
        self._index = -1
        self._mode = mode if mode in MODE_META else MODE_SEQUENTIAL
        self._shuffle_order = []
        self._shuffle_pos = -1
        self._stopped = False
        self._token = ""                # 防止过期的「取地址」线程抢播

        self.on_track = on_track        # (index, track, reason) -> None
        self.on_state = on_state        # (state:str) -> None
        self.on_mode = on_mode          # (mode:str) -> None
        self.on_queue = on_queue        # () -> None
        self.on_error = on_error        # (message:str) -> None

        # 播放器回调：统一走这里，UI 不用自己接
        self.player.on_state = self._handle_state
        self.player.on_finished = self._handle_finished

    # ==================================================
    # 属性
    # ==================================================
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def index(self) -> int:
        return self._index

    @property
    def current(self):
        if 0 <= self._index < len(self.items):
            return self.items[self._index]
        return None

    def set_clients(self, clients):
        self.clients = clients or {}

    def set_items(self, items, source_name="", notify=True):
        """只更新列表内容，不动正在播放的曲目"""
        self.items = list(items or [])
        self.source_name = source_name or self.source_name
        self._rebuild_shuffle()
        if self._index >= len(self.items):
            self._index = -1
        if notify and self.on_queue:
            self.on_queue()

    # ==================================================
    # 播放控制
    # ==================================================
    def load(self, items, start_index=0, source_name="", autoplay=True):
        """装载列表并从 start_index 开始播放"""
        self.items = list(items or [])
        self.source_name = source_name or ""
        self._rebuild_shuffle()
        self._stopped = False
        if self.on_queue:
            self.on_queue()
        if not self.items:
            self.stop()
            return
        start_index = max(0, min(int(start_index), len(self.items) - 1))
        if autoplay:
            self.play_at(start_index, reason="load")

    def play_at(self, index: int, reason="manual"):
        if not self.items:
            return
        index = max(0, min(int(index), len(self.items) - 1))
        self._index = index
        self._stopped = False
        track = self.items[index]
        # 用户主动选曲时才把随机顺序重排到这一首；
        # 自动续播必须沿用已经算好的随机顺序，否则会来回跳。
        if reason in ("load", "manual", "jump", "resume"):
            self._sync_shuffle_pos(index)
        if self.on_track:
            self.on_track(index, track, reason)
        self._start(track)

    def play_track(self, track, items=None, source_name=""):
        """播放单曲（必要时同时替换队列内容）"""
        if items is not None:
            self.items = list(items)
            self.source_name = source_name or self.source_name
            self._rebuild_shuffle()
            if self.on_queue:
                self.on_queue()
        for i, item in enumerate(self.items):
            if tray.track_key(item) == tray.track_key(track):
                self.play_at(i, reason="manual")
                return
        self.items.append(track)
        self._rebuild_shuffle()
        if self.on_queue:
            self.on_queue()
        self.play_at(len(self.items) - 1, reason="manual")

    def toggle_pause(self) -> bool:
        """返回 True 表示当前处于暂停状态"""
        paused = self.player.toggle_pause()
        if self.on_state:
            self.on_state("paused" if paused else "playing")
        return paused

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def stop(self, reason="manual"):
        """停止播放并复位"""
        self._stopped = True
        self.player.stop()
        if self.on_state:
            self.on_state("stopped")
        if reason == "user" and self.on_track:
            self.on_track(self._index, self.current, "stopped")

    def next(self, user=True):
        """下一首；返回是否真的切了歌"""
        if not self.items:
            return False
        target = self._next_index()
        if target is None:
            self._end_of_list()
            return False
        self.play_at(target, reason="next" if user else "auto")
        return True

    def previous(self, user=True):
        """上一首：播放超过 3 秒时先回到开头（和主流播放器一致）"""
        if not self.items:
            return False
        if user and self.player.get_state()["position"] > 3.0:
            self.player.seek(0.0)
            return True
        target = self._previous_index()
        if target is None:
            self.play_at(0, reason="prev")
            return True
        self.play_at(target, reason="prev")
        return True

    def jump(self, delta: int):
        if not self.items:
            return
        target = self._index + delta
        if 0 <= target < len(self.items):
            self.play_at(target, reason="jump")
    # ==================================================
    # 播放模式
    # ==================================================
    def set_mode(self, mode: str, notify=True):
        if mode not in MODE_META:
            return
        self._mode = mode
        self._rebuild_shuffle()
        if notify and self.on_mode:
            self.on_mode(mode)

    def cycle_mode(self) -> str:
        """点击图标切换：顺序 → 随机 → 单曲循环 → 顺序 …"""
        index = MODE_ORDER.index(self._mode)
        mode = MODE_ORDER[(index + 1) % len(MODE_ORDER)]
        self.set_mode(mode)
        return mode

    # ==================================================
    # 内部：顺序计算
    # ==================================================
    def _rebuild_shuffle(self):
        """生成一份打乱的播放顺序

        如果当前正播某一首，就把这一首放在最前面，
        保证「随机播放」既不会漏掉任何一首，也不会打断当前这首。
        """
        order = list(range(len(self.items)))
        random.shuffle(order)
        if self._index >= 0 and self._index < len(self.items):
            if self._index in order:
                order.remove(self._index)
            order.insert(0, self._index)
            self._shuffle_pos = 0
        else:
            self._shuffle_pos = -1
        self._shuffle_order = order

    def _sync_shuffle_pos(self, index: int):
        """让「当前这首」成为随机顺序的起点，保证一轮能覆盖全部曲目"""
        order = self._shuffle_order
        if not order or index not in order:
            self._rebuild_shuffle()
            return
        order.remove(index)
        order.insert(0, index)
        self._shuffle_pos = 0

    def _next_index(self):
        total = len(self.items)
        if total == 0:
            return None
        if self._mode == MODE_REPEAT_ONE:
            return self._index
        if self._mode == MODE_SHUFFLE:
            if not self._shuffle_order:
                self._rebuild_shuffle()
            self._shuffle_pos += 1
            if self._shuffle_pos >= total:      # 一轮放完 → 停
                return None
            return self._shuffle_order[self._shuffle_pos]
        # 顺序播放
        target = self._index + 1
        return target if target < total else None

    def _previous_index(self):
        total = len(self.items)
        if total == 0:
            return None
        if self._mode == MODE_SHUFFLE:
            self._shuffle_pos -= 1
            if self._shuffle_pos < 0:
                self._shuffle_pos = 0
                return self._shuffle_order[0] if self._shuffle_order else None
            return self._shuffle_order[self._shuffle_pos]
        return max(0, self._index - 1)

    def _end_of_list(self):
        """一轮播放结束：停在这里，保留最后一首的信息（播完即停）"""
        self._stopped = True
        try:
            self.player.stop()
        except Exception:
            pass
        if self.on_state:
            self.on_state("ended")

    # ==================================================
    # 内部：播放一首
    # ==================================================
    def _start(self, track):
        if self.on_state:
            self.on_state("loading")
        token = f"{tray.track_key(track)}::{time.time()}"
        self._token = token
        threading.Thread(target=self._start_worker, args=(track, token),
                         daemon=True, name="queue-start").start()

    def _start_worker(self, track, token):
        if getattr(self, "_token", token) != token:
            return

        # ---- 1. 本地优先 ----
        local = track.get("local_path") or ""
        is_url = True
        source = ""
        if local and tray.track_has_local(track):
            source = local
            is_url = False
        elif local:
            cached = find_cached(local)
            if cached:
                source, is_url = cached, False

        if getattr(self, "_token", token) != token:
            return

        # 本地文件顺手修复（老版本可能把 fMP4 当 mp3 写过 ID3 头）
        if not is_url and source:
            try:
                import repair
                source = repair.repair_before_play(source)
            except Exception as exc:
                print(f"[播放] 本地文件检查失败（忽略）: {exc}")

        # ---- 2. 取在线地址 ----
        if not source:
            platform = track.get("platform")
            try:
                url = resolve_play_url(platform, track, self.clients)
            except Exception as exc:
                self._report_error(f"取播放地址失败: {exc}")
                self._idle()
                return
            if getattr(self, "_token", token) != token:
                return
            if not url:
                self._report_error(
                    f"无法获取播放地址（{tray.track_display(track)}），"
                    f"该平台可能需要登录或暂不支持")
                self._idle()
                return
            source, is_url = url, True

        if getattr(self, "_token", token) != token:
            return

        self.player.play(source, title=tray.track_display(track),
                         is_url=is_url)

    def _idle(self):
        """取地址失败时把状态收回来，避免界面一直卡在「加载中」"""
        if self.on_state:
            self.on_state("idle")

    def _report_error(self, message):
        if self.on_error:
            self.on_error(message)
        else:
            print("[播放队列]", message)

    # ==================================================
    # 内部：播放器回调
    # ==================================================
    def _handle_state(self, state: str):
        if self.on_state:
            self.on_state(state)

    def _handle_finished(self):
        """一首放完 → 按播放模式决定下一步"""
        if self._stopped:
            return
        if self._mode == MODE_REPEAT_ONE and self.items:
            self.play_at(self._index, reason="repeat")
            return
        if len(self.items) <= 1:
            # 只有一首时退化成单曲循环
            if self.items:
                self.play_at(self._index, reason="repeat")
            return
        if not self.next(user=False):
            self._end_of_list()


# ============================================================
# 播放模式持久化
# ============================================================
def mode_from_config(cfg: dict) -> str:
    mode = ((cfg or {}).get("app") or {}).get("play_mode") or ""
    return mode if mode in MODE_META else MODE_SEQUENTIAL
