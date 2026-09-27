"""GUI 登录对话框 —— 支持二维码 / 手机号 / Cookie 三种登录方式"""
import asyncio
import io
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import qrcode
from PIL import Image, ImageTk

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
    PLATFORMS = [
        ("netease", "网易云"),
        ("qqmusic", "QQ音乐"),
        ("kugou", "酷狗"),
        ("qishui", "汽水音乐"),
        ("bilibili", "B站"),
    ]

    def __init__(self, master, cfg, on_success=None):
        super().__init__(master)
        self.title("账号登录")
        self.geometry("760x600")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.cfg = cfg                # 引用 config.json 里的 dict
        self.on_success = on_success  # 登录成功回调

        self._qr_photo = None         # 保持 PhotoImage 引用，避免被 GC
        self._polling = False         # 轮询开关
        self.pages = {}               # platform -> widgets

        self._build_ui()

    # ------------------------------------------------
    # UI
    # ------------------------------------------------
    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        for key, label in self.PLATFORMS:
            page = ttk.Frame(nb)
            nb.add(page, text=label)
            self.pages[key] = self._build_page(page, key)

        # 底部
        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, padx=10, pady=(0, 12))
        ttk.Button(footer, text="关闭", width=10,
                   command=self._on_close).pack(side=tk.RIGHT)

    def _build_page(self, parent, platform):
        w = {}

        # ---- 左：二维码 ----
        left = ttk.LabelFrame(parent, text="① 扫码登录", padding=12)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6), pady=6)

        qr_label = ttk.Label(left, text="点击「获取二维码」", anchor=tk.CENTER)
        qr_label.pack(fill=tk.BOTH, expand=True)
        w["qr_label"] = qr_label

        status = tk.StringVar(value="未开始")
        ttk.Label(left, textvariable=status,
                  foreground="#666666").pack(pady=(6, 4))
        w["status_var"] = status

        row = ttk.Frame(left)
        row.pack()
        ttk.Button(row, text="获取二维码",
                   command=lambda: self._start_qr(platform)).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="取消",
                   command=lambda: self._stop_qr(platform)).pack(side=tk.LEFT, padx=4)

        # ---- 右：手机号 / Cookie ----
        right = ttk.LabelFrame(parent, text="② 手机号 / Cookie 登录", padding=12)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)

        phone_var = tk.StringVar()
        pwd_var = tk.StringVar()
        w["phone_var"] = phone_var
        w["pwd_var"] = pwd_var

        ttk.Label(right, text="手机号").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(right, textvariable=phone_var, width=26).grid(row=0, column=1, pady=4)

        ttk.Label(right, text="密码/验证码").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(right, textvariable=pwd_var, width=26, show="*").grid(row=1, column=1, pady=4)

        ttk.Button(right, text="手机号登录",
                   command=lambda: self._phone_login(platform,
                                                     phone_var.get(),
                                                     pwd_var.get())
                   ).grid(row=2, column=0, columnspan=2, pady=8)

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(
            row=3, column=0, columnspan=2, sticky=tk.EW, pady=10)

        ttk.Label(right, text="或粘贴 Cookie：").grid(
            row=4, column=0, columnspan=2, sticky=tk.W)

        cookie_text = tk.Text(right, width=32, height=5)
        cookie_text.grid(row=5, column=0, columnspan=2, pady=4)
        w["cookie_text"] = cookie_text

        ttk.Button(right, text="使用 Cookie 登录",
                   command=lambda: self._cookie_login(platform,
                                                      cookie_text.get("1.0", tk.END).strip())
                   ).grid(row=6, column=0, columnspan=2, pady=4)

        return w

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
                    "该平台暂未实现扫码登录，请使用 Cookie 方式"))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(f"❌ 出错: {e}"))
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
                self._ui(lambda: w["status_var"].set("❌ 二维码已过期，请重新获取"))
                return
            if code == 801:
                self._ui(lambda: w["status_var"].set("等待扫码…"))
            elif code == 802:
                self._ui(lambda: w["status_var"].set("已扫码，请在手机上确认"))
            elif code == 803:
                cookies = GetCurrentSession().cookies.get_dict()
                music_u = cookies.get("MUSIC_U", "")
                if not music_u:
                    self._ui(lambda: w["status_var"].set("❌ 登录成功但未拿到 Cookie"))
                    return
                self._save_cookie("netease", music_u)
                self._ui(lambda: w["status_var"].set("✅ 网易云登录成功"))
                self._ui(lambda: self._on_login_ok("netease"))
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
                            result.credential.model_dump(),
                            ensure_ascii=False,
                        )
                        self._save_cookie("qqmusic", cred_json)
                        self._ui(lambda: w["status_var"].set("✅ QQ音乐登录成功"))
                        self._ui(lambda: self._on_login_ok("qqmusic"))
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
                    self.cfg.setdefault("bilibili", {})
                    self.cfg["bilibili"]["sessdata"] = cred.sessdata
                    self.cfg["bilibili"]["bili_jct"] = cred.bili_jct
                    save_config(self.cfg)
                    self._ui(lambda: w["status_var"].set("✅ B站登录成功"))
                    self._ui(lambda: self._on_login_ok("bilibili"))
                    return
                elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                    self._ui(lambda: w["status_var"].set("❌ 二维码已过期"))
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
                    raise RuntimeError("登录成功但未拿到 MUSIC_U")
                self._save_cookie("netease", music_u)
                messagebox.showinfo("成功", "网易云登录成功")
                self._on_login_ok("netease")
            except Exception as e:
                messagebox.showerror("失败", f"网易云登录失败：{e}")
        else:
            messagebox.showinfo(
                "提示",
                f"{platform} 的手机号登录接口变动较大，建议使用二维码或 Cookie 方式。"
            )

    # ------------------------------------------------
    # Cookie 直接登录
    # ------------------------------------------------
    def _cookie_login(self, platform, cookie):
        if not cookie:
            messagebox.showwarning("提示", "Cookie 不能为空")
            return
        self._save_cookie(platform, cookie)
        messagebox.showinfo("成功", "Cookie 已保存")
        self._on_login_ok(platform)

    # ------------------------------------------------
    # 通用工具
    # ------------------------------------------------
    def _show_qr(self, platform, content: str):
        try:
            photo = make_qr_image(content, 220)
            self._qr_photo = photo
            self._ui(lambda: self.pages[platform]["qr_label"].config(image=photo, text=""))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(f"生成二维码失败：{e}"))

    def _show_qr_bytes(self, platform, data: bytes):
        try:
            photo = bytes_to_photoimage(data, 220)
            self._qr_photo = photo
            self._ui(lambda: self.pages[platform]["qr_label"].config(image=photo, text=""))
        except Exception as e:
            self._ui(lambda: self.pages[platform]["status_var"].set(f"显示二维码失败：{e}"))

    def _save_cookie(self, platform, cookie: str):
        self.cfg.setdefault(platform, {})
        self.cfg[platform]["cookie"] = cookie
        save_config(self.cfg)

    def _on_login_ok(self, platform):
        self._polling = False
        if self.on_success:
            try:
                self.on_success(platform)
            except Exception:
                pass

    def _ui(self, fn):
        try:
            self.after(0, fn)
        except Exception:
            pass

    def _on_close(self):
        self._polling = False
        self.destroy()
