"""音频文件修复

背景：早先版本写标签时只看扩展名，把 B站下载的 fMP4/AAC 文件
（扩展名是 .mp3）当成 mp3 写了 ID3v2 头，结果文件变成
「ID3 头 + MP4 数据」这种混合体，pygame 和 ffmpeg 都读不了。

好在写坏的方式很「整齐」：只是在开头**插入**了一段 ID3v2 标签，
后面的音频数据一个字节都没动。所以把这段标签摘掉就能完整恢复。

这个模块同时被两个地方用：
1. 「本地音乐」页的「修复文件」按钮 —— 被动、可控；
2. 播放本地文件前自动检查 —— 用户不用管，遇到就顺手修好。
"""
from __future__ import annotations

import os

import downloader as D

# 已经是「ID3 头 + MP4」这种坏组合的判断依据
ID3_HEADER_SIZE = 10


def id3_payload_offset(head: bytes) -> int:
    """返回 ID3v2 标签之后的数据偏移；不是 ID3 返回 0"""
    if len(head) < ID3_HEADER_SIZE or head[:3] != b"ID3":
        return 0
    size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | \
           ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
    return ID3_HEADER_SIZE + size


def needs_repair(path: str) -> bool:
    """文件是否是「ID3 头 + 非 MP3 容器」这种被写坏的状态"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            offset = id3_payload_offset(head)
            if not offset:
                return False
            fh.seek(offset)
            probe = fh.read(12)
    except Exception:
        return False
    # ID3 头后面跟的却是 MP4 容器 → 一定是被写坏了
    return len(probe) >= 8 and probe[4:8] == b"ftyp"


def strip_id3_copy(path: str, dry_run=False):
    """摘掉开头的 ID3v2 标签，恢复原始音频

    返回 (是否成功, 新路径或原因)。会在原目录里生成正确后缀的新文件，
    原名加 .broken 保留，不会静默丢数据。
    """
    if not needs_repair(path):
        return False, "不需要修复"

    try:
        with open(path, "rb") as fh:
            offset = id3_payload_offset(fh.read(16))
            if not offset:
                return False, "读不到 ID3 头"
            fh.seek(offset)
            payload_head = fh.read(16)
    except Exception as exc:
        return False, f"读取失败: {exc}"

    container = "mp4" if payload_head[4:8] == b"ftyp" else ""
    if not container:
        return False, "标签后面不是 MP4 数据，不处理"
    ext = D.ext_for_container(container) or ".m4a"

    if dry_run:
        return True, f"可修复 → {ext}"

    base, _old_ext = os.path.splitext(path)
    target = base + ext
    if os.path.exists(target):
        target = D.unique_path(os.path.dirname(target),
                               os.path.basename(target))
    tmp = target + ".repairing"

    try:
        total = os.path.getsize(path)
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            src.seek(offset)
            remaining = total - offset
            while remaining > 0:
                chunk = src.read(min(1 << 20, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
        if not os.path.exists(tmp):
            raise RuntimeError("没有生成恢复文件")
        # 校验恢复结果确实是能识别的音频（不设大小下限：
        # 正常文件一定比 ID3 标签本身大，且能通过容器嗅探）
        if os.path.getsize(tmp) <= offset:
            raise RuntimeError("恢复出来的文件比 ID3 标签还小")
        if not D.sniff_container(tmp):
            raise RuntimeError("恢复出来的文件格式无法识别")
        os.replace(tmp, target)
    except Exception as exc:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        return False, f"修复失败: {exc}"

    # 原名留一份后备，确认没问题后用户可以自己删
    broken = path + ".broken"
    try:
        if os.path.exists(broken):
            os.unlink(broken)
        os.replace(path, broken)
    except Exception:
        try:
            os.unlink(path)
        except Exception:
            pass

    # 顺手按真实格式写一次正确标签
    try:
        D.write_tags(target, {"title": os.path.splitext(
            os.path.basename(target))[0]})
    except Exception:
        pass
    return True, target


def scan_and_repair(directory: str, progress=None, limit=0):
    """扫描目录，修复所有被写坏的文件

    返回 {"fixed": [...], "failed": [...], "scanned": n}
    """
    result = {"fixed": [], "failed": [], "scanned": 0}
    exts = (".mp3", ".m4a", ".flac", ".ogg", ".wav", ".aac", ".opus")
    if not directory or not os.path.isdir(directory):
        return result

    for root, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if name.endswith(".broken") or name.endswith(".part"):
                continue
            if not name.lower().endswith(exts):
                continue
            path = os.path.join(root, name)
            result["scanned"] += 1
            if progress:
                try:
                    progress(name)
                except Exception:
                    pass
            if not needs_repair(path):
                continue
            ok, info = strip_id3_copy(path)
            if ok:
                result["fixed"].append((name, info))
            else:
                result["failed"].append((name, info))
            if limit and len(result["fixed"]) >= limit:
                return result
    return result


def repair_before_play(path: str):
    """播放前顺手修复；返回应该播放的路径"""
    if not path or not os.path.isfile(path):
        return path
    if not needs_repair(path):
        return path
    ok, info = strip_id3_copy(path)
    if ok:
        print(f"[修复] {os.path.basename(path)} 已恢复为 {os.path.basename(info)}")
        return info
    print(f"[修复] {os.path.basename(path)} 修复失败：{info}")
    return path
