"""GUI 登录对话框 —— 支持二维码 / 手机号 / Cookie 三种登录方式

登录成功后的凭据不再直接覆盖 config.json 的单个字段，而是交给外面
（app_gui）通过 save_handler 存成一个「账号」，这样可以一个平台存多个账号。
没有设置 save_handler 时会退回旧行为：直接写进 cfg 的旧字段。
"""
import asyncio
import io
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import qrcode
from PIL import Image, ImageTk

import theme as T
import widgets as W
from config import save_config


# ========================= 工具函数 =========================
def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def make_qr_image(content: str, size: int = 220):
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def bytes_to_photoimage(data: bytes, size: int = 220):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


# ========================= 登录对话框 =========================
class LoginDialog(tk.Toplevel):
    """账号登录窗口

    参数
    ----
    master       : 父窗口
    cfg          : config 字典（兼容旧行为时直接写它）
    on_success   : 登录成功回调 (platform, cred_dict, method)
    save_handler : 决定「保存成哪个账号」的回调，签名见 set_save_handler()
    accounts     : AccountStore，用于显示当前账号
    """

    PLATFORMS = [
        ("netease", "网易云"),
        ("qqmusic", "QQ音乐"),
        ("kugou", "酷狗"),
        ("qishui", "汽水音乐"),
        ("bilibili", "B站"),
    ]

    def __init__(self, master, cfg, on_success=None, save_handler=None,
                 accounts=None):
        super().__init__(master)
        self.title("账号登录 / 添加账号")
        self.geometry("820x640")
        self.minsize(780, 600)
        self.configure(bg=T.BG)
        self.transient(master)
        self.grab_set()

        self.cfg = cfg
        self.on_success = on_success
        self.save_handler = save_handler
        self.accounts = accounts

        self._qr_photo = None         # 保持 PhotoImage 引用，避免被 GC
        self._polling = False         # 轮询开关
        self.pages = {}               # platform -> widgets
        self._current_platform = self.PLATFORMS[0][0]
        self._saved_once = set()      # 本次会话里已经保存过的平台

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------
    # 保存策略（由 app_gui 注入）
    # ------------------------------------------------
    def set_save_handler(self, fn):
        """fn(platform) -> {"mode", "label", "placeholder", "confirm_text"}"""
        self.save_handler = fn

    def _save_options(self, platform):
        default = {"mode": "new", "label": "", "placeholder":
                   "给这个账号起个名字（留空自动命名）", "confirm_text": "保存账号"}
        if not self.save_handler:
            default["confirm_text"] = "保存登录信息"
            return default
        try:
            options = self.save_handler(platform) or {}
            default.update(options)
        except Exception as exc:
            print(f"[登录] 获取保存选项失败: {exc}")
        return default

    def _prepare_save_ui(self, platform):
        """切到某个平台时刷新保存区的文案"""
        page = self.pages.get(platform)
        if not page:
            return
        options = self._save_options(platform)
        page["save_mode_var"].set(options["mode"])
        if options["mode"] == "update":
            page["save_btn"].set_text("更新已有账号")
        else:
            page["save_btn"].set_text("保存为新账号")
        page["name_entry"].delete(0, tk.END)
        page["name_entry"].insert(0, options.get("label") or "")
        try:
            page["name_hint"].configure(text=options.get("placeholder") or "")
        except Exception:
            pass

    # ------------------------------------------------
    # UI
    # ------------------------------------------------
    def _build_ui(self):
        T.apply_ttk_theme(self)
        fonts = T.Fonts(self)

        # ---- 顶部：说明 + 当前账号 ----
        top = tk.Frame(self, bg=T.BG)
        top.pack(fill=tk.X, padx=18, pady=(16, 6))
        tk.Label(top, text="账号登录", bg=T.BG, fg=T.TEXT,
                 font=fonts.h2).pack(side=tk.LEFT)
        tk.Label(top, text="同一平台可以保存多个账号，在「账号管理」里随时切换",
                 bg=T.BG, fg=T.TEXT_3, font=fonts.small).pack(
            side=tk.LEFT, padx=(12, 0), pady=(6, 0))

        self.current_label = tk.Label(
            self, text="", bg=T.PANEL, fg=T.TEXT_2, font=fonts.small,
            anchor="w", padx=12, pady=8)
        self.current_label.pack(fill=tk.X, padx=18, pady=(0, 8))

        # ---- 平台选项卡 ----
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 6))
        self.notebook = nb
        for key, label in self.PLATFORMS:
            page = ttk.Frame(nb)
            nb.add(page, text=f"  {label}  ")
            self.pages[key] = self._build_page(page, key)
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ---- 底部按钮 ----
        footer = tk.Frame(self, bg=T.BG)
        footer.pack(fill=tk.X, padx=18, pady=(6, 16))
        tk.Label(footer,
                 text="提示：扫码最省事；Cookie 方式需要自己从浏览器里复制",
                 bg=T.BG, fg=T.TEXT_3, font=fonts.tiny).pack(side=tk.LEFT)
        tk.Button(footer, text="关闭", command=self._on_close,
                  bg=T.ELEVATED, fg=T.TEXT, relief=tk.FLAT, bd=0,
                  font=fonts.body, padx=18, pady=6,
                  activebackground=T.HOVER, activeforeground=T.TEXT,
                  cursor="hand2").pack(side=tk.RIGHT)

        for key, _ in self.PLATFORMS:
            self._prepare_save_ui(key)
        self._refresh_current_label()

    def _build_page(self, parent, platform):
        w = {}
        parent.configure(style="TFrame")

        body = tk.Frame(parent, bg=T.BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # ---------------- 左：扫码 ----------------
        left = tk.Frame(body, bg=T.PANEL, highlightthickness=1,
                        highlightbackground=T.BORDER)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        tk.Label(left, text="① 扫码登录", bg=T.PANEL, fg=T.TEXT_2,
                 font=T.Fonts(self).small_bold, anchor="w").pack(
            fill=tk.X, padx=14, pady=(12, 0))

        qr_holder = tk.Frame(left, bg=T.PANEL)
        qr_holder.pack(fill=tk.BOTH, expand=True, pady=8)
        qr_label = tk.Label(qr_holder, text="点击下方「获取二维码」",
                            bg=T.PANEL, fg=T.TEXT_3,
                            font=T.Fonts(self).small)
        qr_label.pack(expand=True)
        w["qr_label"] = qr_label

        status = tk.StringVar(value="未开始")
        tk.Label(left, textvariable=status, bg=T.PANEL, fg=T.TEXT_3,
                 font=T.Fonts(self).small).pack(pady=(0, 8))
        w["status_var"] = status

        qr_row = tk.Frame(left, bg=T.PANEL)
        qr_row.pack(pady=(0, 14))
        W.PrimaryButton(qr_row, "获取二维码", icon="refresh",
                        command=lambda: self._start_qr(platform),
                        bg=T.ACCENT, fg=T.TEXT_ON_ACCENT,
                        hover_bg=T.ACCENT_HOVER, panel_bg=T.PANEL,
                        min_width=124, height=32).pack(side=tk.LEFT, padx=4)
        W.PrimaryButton(qr_row, "取消", command=lambda: self._stop_qr(platform),
                        bg=T.ELEVATED, fg=T.TEXT_2, panel_bg=T.PANEL,
                        min_width=78, height=32).pack(side=tk.LEFT, padx=4)

        # ---------------- 右：手机号 / Cookie ----------------
        right = tk.Frame(body, bg=T.PANEL, highlightthickness=1,
                         highlightbackground=T.BORDER)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        right_inner = tk.Frame(right, bg=T.PANEL, padx=14, pady=12)
        right_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(right_inner, text="② 手机号登录", bg=T.PANEL, fg=T.TEXT_2,
                 font=T.Fonts(self).small_bold, anchor="w").pack(fill=tk.X)

        phone_var = tk.StringVar()
        pwd_var = tk.StringVar()
        w["phone_var"] = phone_var
        w["pwd_var"] = pwd_var

        rows = tk.Frame(right_inner, bg=T.PANEL)
        rows.pack(fill=tk.X, pady=(8, 0))
        tk.Label(rows, text="手机号", bg=T.PANEL, fg=T.TEXT_3, width=9,
                 anchor="w", font=T.Fonts(self).small).grid(row=0, column=0,
                                                            pady=4)
        ttk.Entry(rows, textvariable=phone_var, width=24,
                  style="Modern.TEntry").grid(row=0, column=1, pady=4)
        tk.Label(rows, text="密码/验证码", bg=T.PANEL, fg=T.TEXT_3, width=9,
                 anchor="w", font=T.Fonts(self).small).grid(row=1, column=0,
                                                            pady=4)
        ttk.Entry(rows, textvariable=pwd_var, width=24, show="*",
                  style="Modern.TEntry").grid(row=1, column=1, pady=4)

        tk.Frame(right_inner, bg=T.BORDER_SOFT, height=1).pack(
            fill=tk.X, pady=10)

        tk.Label(right_inner, text="③ 或直接粘贴 Cookie", bg=T.PANEL,
                 fg=T.TEXT_2, font=T.Fonts(self).small_bold,
                 anchor="w").pack(fill=tk.X)
        tk.Label(right_inner,
                 text=self._cookie_hint(platform), bg=T.PANEL, fg=T.TEXT_3,
                 font=T.Fonts(self).tiny, anchor="w", justify=tk.LEFT,
                 wraplength=300).pack(fill=tk.X, pady=(2, 6))

        cookie_text = tk.Text(right_inner, height=4, bg=T.ELEVATED, fg=T.TEXT,
                              insertbackground=T.ACCENT, relief=tk.FLAT, bd=0,
                              font=T.Fonts(self).small,
                              highlightthickness=1,
                              highlightbackground=T.BORDER,
                              highlightcolor=T.ACCENT)
        cookie_text.pack(fill=tk.X)
        w["cookie_text"] = cookie_text

        # ---------------- 账号名 + 保存 ----------------
        tk.Frame(right_inner, bg=T.BORDER_SOFT, height=1).pack(
            fill=tk.X, pady=10)
        save_bar = tk.Frame(right_inner, bg=T.PANEL)
        save_bar.pack(fill=tk.X)
        tk.Label(save_bar, text="账号名", bg=T.PANEL, fg=T.TEXT_3, width=9,
                 anchor="w", font=T.Fonts(self).small).pack(side=tk.LEFT)
        name_entry = ttk.Entry(save_bar, width=22, style="Modern.TEntry")
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        name_hint = tk.Label(right_inner, text="", bg=T.PANEL, fg=T.TEXT_3,
                             font=T.Fonts(self).tiny, anchor="w")
        name_hint.pack(fill=tk.X, pady=(4, 0))
        w["name_hint"] = name_hint
        w["name_entry"] = name_entry
        w["save_mode_var"] = tk.StringVar(value="new")

        buttons = tk.Frame(right_inner, bg=T.PANEL)
        buttons.pack(fill=tk.X, pady=(10, 0))

        def login_via_phone():
            self._phone_login(platform, phone_var.get(), pwd_var.get())

        def login_via_cookie():
            self._cookie_login(platform,
                               cookie_text.get("1.0", tk.END).strip())

        W.PrimaryButton(buttons, "手机号登录", command=login_via_phone,
                        bg=T.ELEVATED, fg=T.TEXT, panel_bg=T.PANEL,
                        min_width=112, height=32).pack(side=tk.LEFT)
        save_btn = W.PrimaryButton(buttons, "保存为新账号",
                                   command=login_via_cookie, bg=T.ACCENT,
                                   fg=T.TEXT_ON_ACCENT,
                                   hover_bg=T.ACCENT_HOVER, panel_bg=T.PANEL,
                                   min_width=134, height=32)
        save_btn.pack(side=tk.RIGHT)
        w["save_btn"] = save_btn
        return w

    def _cookie_hint(self, platform):
        return {
            "netease": "填 MUSIC_U 的值（浏览器 F12 → Application → Cookies）",
            "qqmusic": "填登录后的 Cookie 串，或 Credential 的 JSON",
            "kugou": "填完整 Cookie 串，形如 a=1; b=2",
            "qishui": "填完整 Cookie 串，形如 a=1; b=2",
            "bilibili": "填 SESSDATA 的值即可（bili_jct 可选，一行一个字段）",
        }.get(platform, "粘贴 Cookie")

    def _on_tab_changed(self, _event=None):
        try:
            index = self.notebook.index(self.notebook.select())
        except Exception:
            return
        platform = self.PLATFORMS[index][0]
        self._current_platform = platform
        self._refresh_current_label()

    def _refresh_current_label(self):
        """顶部显示该平台当前正在用哪个账号"""
        platform = self._current_platform
        name = T.platform_name(platform)
        text = f"【{name}】当前账号："
        if self.accounts is not None:
            account = self.accounts.current(platform)
            total = len(self.accounts.accounts(platform))
            if account:
                text += (f"{account.get('label')}（该平台共保存 {total} 个账号，"
                         f"登录成功后可切换）")
            else:
                text += f"未登录（该平台已保存 {total} 个账号）"
        else:
            text += "未登录"
        try:
            self.current_label.configure(text=text)
        except Exception:
            pass

    # ------------------------------------------------
    # 二维码登录
    # ------------------------------------------------
    def _start_qr(self, platform):
        if self._polling:
            messagebox.showinfo("提示", "请先取消当前二维码")
            return
        self._polling = True
        self.pages[platform]["status_var"].set("正在获取二维码…")
        self.pages[platform]["qr_label"].config(image="", text="加载中…")
        threading.Thread(target=self._qr_worker, args=(platform,),
                         daemon=True).start()

    def _stop_qr(self, platform):
        self._polling = False
        w = self.pages[platform]
        w["status_var"].set("已取消")
        w["qr_label"].config(image="", text="点击「获取二维码」")

    def _qr_worker(self, platform):
        try:
            if platform == "netease":
                self._qr_netease()
            elif platform == "qqmusic":
                self._qr_qqmusic()
            elif platform == "bilibili":
                self._qr_bilibili()
            else:
                self._ui(lambda: self.pages[platform]["status_var"].set(
                    "该平台暂未实现扫码登录，请用 Cookie 方式"))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(
                f"出错: {e}"))
        finally:
            self._polling = False

    # -------- 网易云 --------
    def _qr_netease(self):
        from pyncm import apis, GetCurrentSession
        w = self.pages["netease"]

        resp = apis.login.LoginQrcodeUnikey()
        unikey = resp.get("unikey")
        if not unikey:
            raise RuntimeError(f"获取 unikey 失败：{resp}")

        content = f"https://music.163.com/login?codekey={unikey}"
        self._show_qr("netease", content)
        self._ui(lambda: w["status_var"].set("请使用网易云 App 扫码"))

        start = time.time()
        while self._polling and time.time() - start < 300:
            try:
                r = apis.login.LoginQrcodeCheck(unikey)
            except Exception:
                time.sleep(2)
                continue

            code = r.get("code")
            if code == 800:
                self._ui(lambda: w["status_var"].set("二维码已过期，请重新获取"))
                return
            if code == 801:
                self._ui(lambda: w["status_var"].set("等待扫码…"))
            elif code == 802:
                self._ui(lambda: w["status_var"].set("已扫码，请在手机上确认"))
            elif code == 803:
                cookies = GetCurrentSession().cookies.get_dict()
                music_u = cookies.get("MUSIC_U", "")
                if not music_u:
                    self._ui(lambda: w["status_var"].set("登录成功但未拿到 Cookie"))
                    return
                self._finish("netease", {"cookie": music_u}, "qr")
                return
            time.sleep(2)

    # -------- QQ音乐 --------
    def _qr_qqmusic(self):
        w = self.pages["qqmusic"]

        async def flow():
            from qqmusic_api import Client
            from qqmusic_api.models.login import QRLoginType, QRCodeLoginEvents

            async with Client() as client:
                qr = await client.login.get_qrcode(QRLoginType.QQ)
                if not qr.data:
                    raise RuntimeError("获取二维码失败")

                self._show_qr_bytes("qqmusic", qr.data)
                self._ui(lambda: w["status_var"].set("请使用 QQ音乐 App 扫码"))

                start = time.time()
                while self._polling and time.time() - start < 300:
                    try:
                        result = await client.login.check_qrcode(qr)
                    except Exception:
                        await asyncio.sleep(2)
                        continue

                    if result.event == QRCodeLoginEvents.DONE and result.credential:
                        cred_json = json.dumps(
                            result.credential.model_dump(), ensure_ascii=False)
                        self._finish("qqmusic", {"cookie": cred_json}, "qr")
                        return
                    await asyncio.sleep(2)

        run_async(flow())

    # -------- B站 --------
    def _qr_bilibili(self):
        w = self.pages["bilibili"]

        async def flow():
            from bilibili_api import login_v2

            qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
            await qr.generate_qrcode()

            pic = qr.get_qrcode_picture()
            if pic and pic.content:
                self._show_qr_bytes("bilibili", pic.content)
            else:
                content = qr.get_qrcode_terminal()
                if not content:
                    raise RuntimeError("无法获取 B 站二维码")
                self._show_qr("bilibili", content)

            self._ui(lambda: w["status_var"].set("请使用 B站 App 扫码"))

            start = time.time()
            while self._polling and time.time() - start < 300:
                try:
                    state = await qr.check_state()
                except Exception:
                    await asyncio.sleep(2)
                    continue

                if state == login_v2.QrCodeLoginEvents.CONF:
                    self._ui(lambda: w["status_var"].set("已扫码，等待确认"))
                elif state == login_v2.QrCodeLoginEvents.DONE:
                    cred = qr.get_credential()
                    self._finish("bilibili",
                                 {"sessdata": cred.sessdata,
                                  "bili_jct": cred.bili_jct or ""}, "qr")
                    return
                elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                    self._ui(lambda: w["status_var"].set("二维码已过期"))
                    return
                await asyncio.sleep(2)

        run_async(flow())

    # ------------------------------------------------
    # 手机号登录
    # ------------------------------------------------
    def _phone_login(self, platform, phone, pwd):
        if not phone or not pwd:
            messagebox.showwarning("提示", "请输入手机号和密码")
            return

        if platform == "netease":
            try:
                from pyncm.apis.login import LoginViaCellphone
                from pyncm import GetCurrentSession
                LoginViaCellphone(phone=phone, password=pwd)
                cookies = GetCurrentSession().cookies.get_dict()
                music_u = cookies.get("MUSIC_U", "")
                if not music_u:
                    raise RuntimeError("登录成功但没拿到 MUSIC_U")
                self._finish("netease", {"cookie": music_u}, "phone")
            except Exception as e:
                messagebox.showerror("失败", f"网易云登录失败：{e}")
        else:
            messagebox.showinfo(
                "提示",
                "只有网易云支持手机号登录；其他平台请用扫码或 Cookie 方式。")

    # ------------------------------------------------
    # Cookie 直接登录
    # ------------------------------------------------
    def _cookie_login(self, platform, cookie):
        if not cookie:
            messagebox.showwarning("提示", "Cookie 不能为空")
            return

        if platform == "bilibili":
            cred = self._parse_bilibili_cookie(cookie)
            if not cred.get("sessdata"):
                messagebox.showwarning("提示", "没解析出 SESSDATA，请检查粘贴内容")
                return
        else:
            cred = {"cookie": cookie.strip()}

        self._finish(platform, cred, "cookie")

    @staticmethod
    def _parse_bilibili_cookie(text: str) -> dict:
        """支持三种填法：纯 SESSDATA / 完整 Cookie 串 / 两行字段"""
        text = (text or "").strip()
        cred = {}
        if "=" in text:
            for part in text.replace("\n", ";").split(";"):
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "SESSDATA":
                    cred["sessdata"] = value
                elif key == "bili_jct":
                    cred["bili_jct"] = value
        if not cred.get("sessdata"):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                cred["sessdata"] = lines[0]
                if len(lines) > 1 and "bili_jct" not in cred:
                    cred["bili_jct"] = lines[1]
        return cred

    # ------------------------------------------------
    # 登录成功后的统一处理
    # ------------------------------------------------
    def _finish(self, platform, cred, method):
        """把凭据交给外面保存（新账号 / 更新已有账号）"""
        page = self.pages[platform]
        label = ""
        try:
            label = page["name_entry"].get().strip()
        except Exception:
            pass

        saved_label = label
        created = True
        if self.save_handler:
            try:
                result = self.save_handler(platform, cred, method, label)
                if isinstance(result, tuple):
                    saved_label, created = result
                elif isinstance(result, str):
                    saved_label = result
            except Exception as exc:
                print(f"[登录] 保存账号失败: {exc}")
                self._ui(lambda: page["status_var"].set(f"保存账号失败: {exc}"))
                return
        else:
            # 兼容旧行为：直接写旧字段
            self.cfg.setdefault(platform, {})
            for key, value in (cred or {}).items():
                self.cfg[platform][key] = value
            save_config(self.cfg)

        self._saved_once.add(platform)
        action = "已添加账号" if created else "已更新账号"
        text = f"登录成功，{action}：{saved_label or '未命名'}"
        self._ui(lambda: page["status_var"].set(text))
        self._ui(lambda: page["qr_label"].config(image="", text="登录成功"))
        self._qr_photo = None

        def notify():
            self._refresh_current_label()
            self._prepare_save_ui(platform)
            if self.on_success:
                try:
                    self.on_success(platform)
                except Exception as exc:
                    print(f"[登录] on_success 回调异常: {exc}")
        self._ui(notify)

    # ------------------------------------------------
    # 通用工具
    # ------------------------------------------------
    def _show_qr(self, platform, content: str):
        try:
            photo = make_qr_image(content, 220)
            self._qr_photo = photo
            self._ui(lambda: self.pages[platform]["qr_label"].config(
                image=photo, text=""))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(
                f"生成二维码失败：{e}"))

    def _show_qr_bytes(self, platform, data: bytes):
        try:
            photo = bytes_to_photoimage(data, 220)
            self._qr_photo = photo
            self._ui(lambda: self.pages[platform]["qr_label"].config(
                image=photo, text=""))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(
                f"显示二维码失败：{e}"))

    def _ui(self, fn):
        try:
            self.after(0, fn)
        except Exception:
            pass

    def _on_close(self):
        self._polling = False
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
