"""多平台音乐播放器 —— 图形界面入口

实际的界面代码在 app_gui.py：
- 现代深色 UI（侧边栏 + 曲目列表 + 播放条）
- 播放列表的创建 / 保存 / 播放 / 下载
- 播放模式：顺序播放 / 随机播放 / 单曲循环（点图标切换，播完即停）
"""
import os
import sys


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def main():
    from app_gui import main as run
    return run()


if __name__ == "__main__":
    main()
