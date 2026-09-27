"""统一配置管理

每个平台现在支持保存多个账号（见 accounts.py），
config.json 的结构由 accounts.AccountStore 负责维护。
"""
import json
import os
import sys

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "config.json")

DEFAULT_CONFIG = {
    "netease": {
        "cookie": "",          # 当前账号的 MUSIC_U（由账号管理同步）
        "phone": "",
        "password": "",
        "accounts": [],        # 多账号列表
        "current": "",         # 当前使用哪个账号
    },
    "qqmusic": {
        "cookie": "",
        "phone": "",
        "accounts": [],
        "current": "",
    },
    "kugou": {
        "cookie": "",
        "accounts": [],
        "current": "",
    },
    "qishui": {
        "cookie": "",
        "accounts": [],
        "current": "",
    },
    "bilibili": {
        "sessdata": "",
        "bili_jct": "",
        "accounts": [],
        "current": "",
    },
    "app": {
        "download_dir": "",
        "play_mode": "sequential",
        "volume": 0.7,
        # 自动更新：开关 / 检查间隔（小时）/ 更新源地址
        "auto_update": True,
        "update_interval_hours": 24,
        "update_source": "",
        "last_update_check": 0,
    },
}


def load_config(migrate_accounts=True):
    """读取配置；缺省键用默认值补齐，兼容旧版本配置文件

    旧版把凭据直接写在 cfg['netease']['cookie'] 之类的字段里，
    这里会自动迁移成一条账号记录（只做一次，之后写入 accounts）。
    """
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[配置] 读取失败，使用默认配置: {exc}")
            data = {}
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value

    if migrate_accounts:
        try:
            from accounts import AccountStore
            migrated = AccountStore(cfg, save=None).migrate_legacy()
            if migrated:
                print(f"[配置] 已把 {migrated} 个旧版登录凭据迁移成账号记录")
                save_config(cfg)
        except Exception as exc:
            print(f"[配置] 账号迁移跳过: {exc}")
    return cfg


def save_config(cfg):
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


def config_path() -> str:
    return CONFIG_FILE
