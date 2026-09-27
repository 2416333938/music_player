"""统一配置管理"""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "netease": {
        "cookie": "",          # 浏览器登录后复制 MUSIC_U 值
        "phone": "",
        "password": ""
    },
    "qqmusic": {
        "cookie": "",          # Q_H_L_ 开头的 QQ 登录凭证
        "phone": ""
    },
    "kugou": {
        "cookie": ""
    },
    "qishui": {
        "cookie": ""           # 汽水音乐 Cookie
    },
    "bilibili": {
        "sessdata": "",        # B站 SESSDATA
        "bili_jct": ""
    }
}


def load_config():
    """读取配置；缺省键用默认值补齐，兼容旧版本配置文件"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)