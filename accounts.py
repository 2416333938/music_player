"""多账号管理

一个平台可以保存多个账号，随时切换当前使用的那一个。

数据结构（存在 config.json 的每个平台下）：
    "netease": {
        "cookie": "旧字段，作为兼容保留",
        "accounts": [
            {"id": "a1b2c3", "label": "我的网易云",
             "method": "扫码", "cred": {"cookie": "MUSIC_U=..."},
             "created_at": 1700000000, "last_used": 1700000000},
            ...
        ],
        "current": "a1b2c3"
    }

- cred 里放的内容跟平台有关，直接喂给 platforms/ 里的客户端：
    网易云 / 酷狗 / 汽水：{"cookie": "..."}
    QQ音乐：              {"cookie": "<Credential 的 JSON 串>"}
    B站：                 {"sessdata": "...", "bili_jct": "..."}
- 旧的单账号字段（cookie / sessdata+bili_jct）在 load_config() 时
  会自动迁移成一条叫「默认账号」的记录，老配置不会丢。
"""
from __future__ import annotations

import hashlib
import time
import uuid

import theme as T

# 各平台凭据里必须有的字段
PLATFORM_CRED_KEYS = {
    "netease": ("cookie",),
    "qqmusic": ("cookie",),
    "kugou": ("cookie",),
    "qishui": ("cookie",),
    "bilibili": ("sessdata",),
}

# 旧版单账号字段 → 新结构 cred 的映射
LEGACY_FIELDS = {
    "netease": {"cookie": "cookie"},
    "qqmusic": {"cookie": "cookie"},
    "kugou": {"cookie": "cookie"},
    "qishui": {"cookie": "cookie"},
    "bilibili": {"sessdata": "sessdata", "bili_jct": "bili_jct"},
}

METHOD_LABELS = {
    "qr": "扫码登录",
    "phone": "手机号登录",
    "cookie": "Cookie 登录",
    "manual": "手动添加",
}


# ============================================================
# 凭据工具
# ============================================================
def cred_id(platform: str, cred: dict) -> str:
    """按凭据内容算指纹，用来判断「同一个账号」"""
    keys = PLATFORM_CRED_KEYS.get(platform, ("cookie",))
    parts = [platform]
    for key in keys:
        parts.append(f"{key}={(cred or {}).get(key) or ''}")
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def cred_ready(platform: str, cred: dict) -> bool:
    """凭据是否够用来实例化客户端"""
    for key in PLATFORM_CRED_KEYS.get(platform, ("cookie",)):
        if not (cred or {}).get(key):
            return False
    return True


def mask(value: str, head: int = 4, tail: int = 3) -> str:
    """把凭据打码，方便在界面上辨认又不会泄露"""
    value = str(value or "")
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}…{value[-tail:]}  ({len(value)}位)"


def cred_preview(platform: str, cred: dict) -> str:
    """一行摘要，用于卡片副标题"""
    cred = cred or {}
    if platform == "bilibili":
        sess = cred.get("sessdata") or ""
        return f"SESSDATA {mask(sess)}" if sess else "未填写 SESSDATA"
    value = cred.get("cookie") or ""
    if not value:
        return "凭据为空"
    if platform == "qqmusic" and value.strip().startswith("{"):
        return "Credential JSON 已保存"
    return mask(value)


def platform_ready(platform: str, cred: dict) -> bool:
    return cred_ready(platform, cred)


# ============================================================
# 账号仓库
# ============================================================
class AccountStore:
    """直接操作 cfg 字典，配合 config.save_config() 落盘"""

    def __init__(self, cfg: dict, save=None):
        self.cfg = cfg
        self._save = save

    # ---------------- 内部 ----------------
    def _bucket(self, platform: str, create=False) -> dict:
        platform_cfg = self.cfg.get(platform)
        if not isinstance(platform_cfg, dict):
            if not create:
                return {}
            platform_cfg = {}
            self.cfg[platform] = platform_cfg
        if create:
            platform_cfg.setdefault("accounts", [])
            platform_cfg.setdefault("current", "")
        return platform_cfg

    def _persist(self):
        if self._save:
            try:
                self._save()
            except Exception as exc:
                print(f"[账号] 保存失败: {exc}")

    # ---------------- 查询 ----------------
    def get(self, platform: str, account_id: str):
        for account in self.accounts(platform):
            if account.get("id") == account_id:
                return account
        return None

    def accounts(self, platform: str) -> list:
        bucket = self._bucket(platform)
        items = bucket.get("accounts")
        return items if isinstance(items, list) else []

    def current_id(self, platform: str) -> str:
        bucket = self._bucket(platform)
        current = bucket.get("current") or ""
        if current and self.get(platform, current) is None:
            bucket["current"] = ""
            return ""
        return current

    def current(self, platform: str):
        current = self.current_id(platform)
        return self.get(platform, current) if current else None

    def current_cred(self, platform: str) -> dict:
        """当前账号的凭据

        只有在「这个平台一个账号都没存过」时才回退到旧的单账号字段，
        否则退出登录 / 删除账号后旧字段会把凭据又「带回来」。
        """
        account = self.current(platform)
        if account:
            return dict(account.get("cred") or {})
        if not self.accounts(platform):
            return self.legacy_cred(platform)
        return {}

    def legacy_cred(self, platform: str) -> dict:
        bucket = self._bucket(platform)
        mapping = LEGACY_FIELDS.get(platform, {"cookie": "cookie"})
        cred = {}
        for cfg_key, cred_key in mapping.items():
            value = bucket.get(cfg_key)
            if value:
                cred[cred_key] = value
        return cred

    def find_by_cred(self, platform: str, cred: dict):
        """按凭据内容找已有账号（用于避免重复添加）"""
        target = cred_id(platform, cred)
        for account in self.accounts(platform):
            if cred_id(platform, account.get("cred") or {}) == target:
                return account
        return None

    def counts(self) -> dict:
        """每个平台的账号数与当前账号标签"""
        result = {}
        for platform in T.PLATFORM_KEYS:
            accounts = self.accounts(platform)
            current = self.current(platform)
            result[platform] = {
                "total": len(accounts),
                "label": (current or {}).get("label", "") if current else "",
                "logged_in": bool(current),
            }
        return result

    def logged_in_platforms(self) -> list:
        return [p for p in T.PLATFORM_KEYS if self.current(p)]

    def summary_text(self) -> str:
        """侧边栏用的一行状态（配合下面 5 个平台圆点看）"""
        logged = self.logged_in_platforms()
        if not logged:
            return "未登录任何平台"
        if len(logged) == 1:
            platform = logged[0]
            account = self.current(platform)
            label = (account or {}).get("label", "")
            return f"已登录 {T.platform_name(platform)}｜{label}"
        return f"已登录 {len(logged)}/5 个平台"

    # ---------------- 增删改 ----------------
    def add(self, platform: str, cred: dict, label: str = "",
            method: str = "manual", make_current=True, prefer_id: str = ""):
        """新增账号；如果凭据已存在则更新那一条

        prefer_id   ：指定要覆盖的账号 id（比如「更新当前账号」）
        make_current：是否把结果设为当前账号；都不要时会自动设为唯一的那个

        返回 (account, created)
        """
        if not cred_ready(platform, cred):
            return None, False

        bucket = self._bucket(platform, create=True)
        now = int(time.time())

        # 1) 用户明确要求更新某个账号
        if prefer_id:
            target = self.get(platform, prefer_id)
            if target is not None:
                target["cred"] = dict(cred)
                target["method"] = method or target.get("method") or "manual"
                target["last_used"] = now
                if label and label != target.get("label"):
                    target["label"] = label
                if make_current:
                    bucket["current"] = target["id"]
                self._sync_legacy(platform)
                self._persist()
                return target, False

        # 2) 凭据和已有账号一致 → 更新那一条，避免存出重复账号
        existing = self.find_by_cred(platform, cred)
        if existing is not None:
            existing["cred"] = dict(cred)
            existing["method"] = method or existing.get("method") or "manual"
            existing["last_used"] = now
            if label and label != existing.get("label"):
                existing["label"] = label
            if make_current:
                bucket["current"] = existing["id"]
            self._sync_legacy(platform)
            self._persist()
            return existing, False

        # 3) 全新的账号
        account = {
            "id": uuid.uuid4().hex[:10],
            "label": (label or "").strip() or self._default_label(platform),
            "method": method or "manual",
            "cred": dict(cred),
            "created_at": now,
            "last_used": now,
        }
        bucket["accounts"].append(account)
        if make_current or len(bucket["accounts"]) == 1:
            bucket["current"] = account["id"]
        self._sync_legacy(platform)
        self._persist()
        return account, True

    def _default_label(self, platform: str) -> str:
        count = len(self.accounts(platform)) + 1
        name = T.platform_name(platform)
        return f"{name}账号 {count}"

    def rename(self, platform: str, account_id: str, label: str) -> bool:
        account = self.get(platform, account_id)
        label = (label or "").strip()
        if account is None or not label:
            return False
        account["label"] = label
        self._persist()
        return True

    def remove(self, platform: str, account_id: str) -> bool:
        bucket = self._bucket(platform)
        accounts = bucket.get("accounts") or []
        target = self.get(platform, account_id)
        if target is None:
            return False
        accounts.remove(target)
        if bucket.get("current") == account_id:
            # 切到剩下的第一个；一个都不剩就清空
            bucket["current"] = accounts[0]["id"] if accounts else ""
        self._sync_legacy(platform)
        self._persist()
        return True

    def set_current(self, platform: str, account_id: str) -> bool:
        account = self.get(platform, account_id)
        if account is None:
            return False
        bucket = self._bucket(platform, create=True)
        bucket["current"] = account_id
        account["last_used"] = int(time.time())
        self._sync_legacy(platform)
        self._persist()
        return True

    def clear_current(self, platform: str) -> bool:
        """退出登录（保留账号记录，只是不再使用）"""
        bucket = self._bucket(platform)
        if not bucket.get("current"):
            return False
        bucket["current"] = ""
        self._sync_legacy(platform)
        self._persist()
        return True

    def _sync_legacy(self, platform: str):
        """把当前账号写回旧字段，保持向后兼容

        这样即使有别的代码/旧版本读 cfg['netease']['cookie'] 也拿得到值。
        没有当前账号时清空，避免退出登录后凭据还残留在旧字段里。
        """
        bucket = self._bucket(platform, create=True)
        account = self.current(platform)
        cred = dict(account.get("cred") or {}) if account else {}
        for cfg_key in LEGACY_FIELDS.get(platform, {}):
            bucket[cfg_key] = cred.get(cfg_key, "")

    # ---------------- 旧数据迁移 ----------------
    def migrate_legacy(self) -> int:
        """把旧的单账号字段迁移成账号记录，返回迁移条数"""
        migrated = 0
        for platform in T.PLATFORM_KEYS:
            bucket = self._bucket(platform, create=True)
            if not isinstance(bucket.get("accounts"), list):
                bucket["accounts"] = []
            cred = self.legacy_cred(platform)
            if not cred or not cred_ready(platform, cred):
                continue
            if self.find_by_cred(platform, cred) is not None:
                continue                        # 已经迁移过了
            now = int(time.time())
            account = {
                "id": uuid.uuid4().hex[:10],
                "label": "默认账号",
                "method": "manual",
                "cred": cred,
                "created_at": now,
                "last_used": now,
            }
            bucket["accounts"].append(account)
            if not bucket.get("current"):
                bucket["current"] = account["id"]
            migrated += 1
        if migrated:
            self._persist()
        return migrated

    # ---------------- 给客户端用 ----------------
    def client_kwargs(self, platform: str) -> dict:
        """返回实例化该平台客户端需要的参数"""
        cred = self.current_cred(platform) or {}
        if platform == "bilibili":
            return {"sessdata": cred.get("sessdata") or None,
                    "bili_jct": cred.get("bili_jct") or None}
        return {"cookie": cred.get("cookie") or None}
