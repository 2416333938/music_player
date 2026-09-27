# 多平台音乐播放器

聚合 **网易云 / QQ音乐 / 酷狗 / 汽水音乐 / B站** 五个平台的搜索与播放，
同时提供 Tkinter 图形界面和命令行两个入口。

## 功能

- **跨平台搜索**：一次输入，同时检索全部（或指定）平台，结果汇总到同一列表
- **播放控制**：播放 / 暂停 / 继续 / 停止，音量 0–100% 实时调节
- **登录管理**：图形化登录对话框，支持 扫码 / 手机号 / 直接粘贴 Cookie 三种方式
- **B站音频**：按视频搜索，自动挑选最高码率的 dash 音频流播放

## 目录结构

```
music_player/
├─ main_gui.py          # 图形界面入口（推荐）
├─ main.py              # 命令行入口
├─ login_dialog.py      # 登录对话框（二维码 / 手机号 / Cookie）
├─ player.py            # 统一播放器：下载 → 本地解码播放，ffmpeg 兜底转码
├─ config.py            # 配置读写（缺省键自动补齐，兼容旧版配置）
├─ config.json          # 本地登录凭证（已 gitignore，不入库）
├─ config.example.json  # 配置模板
├─ requirements.txt     # 运行依赖
├─ platforms/           # 平台适配器，统一 search / get_play_url 接口
│  ├─ netease.py        #   网易云（pyncm）
│  ├─ qqmusic.py        #   QQ音乐（qqmusic-api-python 0.7.x）
│  ├─ kugou.py          #   酷狗（移动端网页接口）
│  ├─ qishui.py         #   汽水音乐（PC 端接口）
│  └─ bilibili.py       #   B站音频（bilibili-api-python）
├─ 安装依赖.bat          # 一键安装依赖
├─ 启动播放器.bat        # 启动图形界面
├─ 命令行版.bat          # 启动命令行版
└─ auto-py-to-exe.json  # 打包配置（可选）
```

## 运行

环境要求：Windows + Python 3.11（3.9 及以上理论可用）。

**方式一：双击脚本（推荐给不熟悉命令行的场景）**

1. 双击 `安装依赖.bat` —— 自动挑选 Python、升级 pip、安装全部依赖并验证导入
2. 双击 `启动播放器.bat` —— 打开图形界面
3. 双击 `命令行版.bat` —— 打开命令行界面

**方式二：手动运行**

```bat
py -3.11 -m pip install -r requirements.txt
py -3.11 main_gui.py
```

命令行版支持的命令：

```
search <关键词>        跨平台搜索音乐
bili <关键词>          搜索 B 站视频
play <平台> <索引>     播放搜索结果，如 play netease 0
playbili <bvid>        播放 B 站视频音频
login                  配置登录信息
quit                   退出
```

## 登录与凭证

登录信息统一保存在 `config.json`，由界面里的「⚙ 登录」按钮写入，
保存后客户端会**热重载**，无需重启程序。

| 平台 | 支持的登录方式 | 实际存储的字段 |
| --- | --- | --- |
| 网易云 | 扫码 / 手机号 / Cookie | `cookie` = `MUSIC_U` 的值 |
| QQ音乐 | 扫码 / Cookie | `cookie` = Credential 的 JSON 串 |
| B站 | 扫码 / Cookie | `sessdata` + `bili_jct` |
| 酷狗 | Cookie | `cookie` |
| 汽水音乐 | Cookie | `cookie` |

> 没有 `config.json` 也能启动：`config.py` 会用默认值补齐，匿名状态下仍可搜索。

**安全提示**：`config.json` 里存的是**可用的明文登录凭证**，等同于账号登录态。
它已加入 `.gitignore`，请勿提交到仓库或分享给他人；如需重置，删除该文件即可。

## 已知限制

- **酷狗**：播放直链需要设备签名校验，公开接口无法稳定获取，`get_play_url()` 通常返回 `None`
  （搜索功能正常）。此时界面会提示无法获取播放地址，请换用其他平台。
- **汽水音乐**：返回的播放地址可能是加密内容，需要额外的解密步骤。
- **格式兼容**：`pygame` 无法直接解码的格式（部分 flac/m4a）会调用 `ffmpeg` 转成 mp3 兜底；
  未安装 ffmpeg 时会提示「无法播放该格式」。ffmpeg 下载：<https://ffmpeg.org>
- **无音频设备**：`pygame.mixer.init()` 失败时程序不会崩溃，但无法出声。

## 打包

`auto-py-to-exe.json` 是 [auto-py-to-exe](https://github.com/brentvolve/auto-py-to-exe) 的配置，
入口为 `main_gui.py`，窗口模式（`console: false`）。

注意：配置中的路径是**绝对路径**（`D:/c++/py/music_player/...`）。
如果项目换目录或换机器，需要重新选择文件后再打包。
打包前请确认已安装 `pyinstaller` 与 `auto-py-to-exe`（二者不是运行依赖）。
