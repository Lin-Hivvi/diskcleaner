# -*- coding: utf-8 -*-
"""
Windows 系统托盘模块
=====================
纯 ctypes 实现，零外部依赖。
使用隐藏窗口 + 消息泵，完全融入 tkinter 事件循环。
"""
import os
import ctypes
import tkinter as tk
from src.i18n import t, current_lang
from src.config import APP_NAME


class WindowsTrayIcon:
    """
    Windows 系统托盘图标

    使用隐藏窗口 + 消息泵，完全融入 tkinter 事件循环
    """

    WM_TRAY_CALLBACK = 0x8000  # WM_USER + 1
    _registered_classes = set()
    _proc_holder = {}  # 防止 WNDPROC 被 GC

    def __init__(self, root, icon_path=None, tooltip=APP_NAME,
                 on_show=None, on_exit=None, on_language=None):
        """
        Args:
            root: tkinter.Tk 实例
            icon_path: .ico 文件路径（可选，默认使用系统图标）
            tooltip: 鼠标悬浮提示
            on_show: 点击托盘图标显示窗口的回调
            on_exit: 从托盘菜单退出时的回调
            on_language: 切换语言的回调
        """
        self.root = root
        self.on_show = on_show
        self.on_exit = on_exit
        self.on_language = on_language
        self.icon_visible = False
        self._nid = None
        self._hwnd = None
        self._class_atom = None
        self._tooltip = tooltip[:127]
        try:
            self._create(icon_path)
            self.icon_visible = True
        except Exception as exc:
            print(f"[Tray] Initialization skipped: {exc}")

    def _load_hicon(self, icon_path):
        """加载 .ico 文件并返回 HICON"""
        if icon_path and os.path.exists(icon_path):
            hicon = ctypes.windll.user32.LoadImageW(
                None, icon_path, 1,  # IMAGE_ICON = 1
                32, 32, 0x00000010   # LR_LOADFROMFILE
            )
            if hicon:
                return hicon
        return ctypes.windll.user32.LoadIconW(None, 32512)  # IDI_APPLICATION

    def _register_class(self, hinstance):
        """注册隐藏窗口类（幂等）"""
        class_name = f"DiskCleanerTrayClass_{os.getpid()}"
        if class_name in self._registered_classes:
            return class_name

        from ctypes import wintypes
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
            wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
                ("hIconSm", ctypes.c_void_p),
            ]

        ctypes.windll.user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_ulonglong, ctypes.c_longlong,
        ]
        ctypes.windll.user32.DefWindowProcW.restype = ctypes.c_longlong

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAY_CALLBACK:
                mouse_msg = lparam & 0xFFFF
                if mouse_msg in (0x0201, 0x0203):
                    if self.on_show:
                        self.root.after(0, self.on_show)
                elif mouse_msg == 0x0205:  # WM_RBUTTONUP
                    self.root.after(0, self._show_context_menu)
                return 0
            if msg == 0x0010:  # WM_CLOSE
                return 0
            return ctypes.windll.user32.DefWindowProcW(
                ctypes.c_void_p(hwnd), ctypes.c_uint(msg),
                ctypes.c_ulonglong(wparam), ctypes.c_longlong(lparam)
            )

        wnd_proc_cb = WNDPROC(wnd_proc)

        class_def = WNDCLASSEXW()
        class_def.cbSize = ctypes.sizeof(WNDCLASSEXW)
        class_def.style = 0
        class_def.lpfnWndProc = ctypes.cast(wnd_proc_cb, ctypes.c_void_p)
        class_def.cbClsExtra = 0
        class_def.cbWndExtra = 0
        class_def.hInstance = hinstance
        class_def.hIcon = None
        class_def.hCursor = None
        class_def.hbrBackground = 6  # COLOR_WINDOW + 1
        class_def.lpszMenuName = None
        class_def.lpszClassName = class_name
        class_def.hIconSm = None

        atom = ctypes.windll.user32.RegisterClassExW(ctypes.byref(class_def))
        if atom == 0:
            raise ctypes.WinError()

        self._registered_classes.add(class_name)
        self._proc_holder[class_name] = wnd_proc_cb
        return class_name

    def _create(self, icon_path):
        """创建托盘图标"""
        hinstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        class_name = self._register_class(hinstance)

        self._hwnd = ctypes.windll.user32.CreateWindowExW(
            0, class_name, "TrayWindow", 0,
            0, 0, 0, 0, None, None, hinstance, None
        )
        if not self._hwnd:
            raise ctypes.WinError()

        hicon = self._load_hicon(icon_path)

        from ctypes import wintypes

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hWnd", wintypes.HWND),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", ctypes.c_uint),
                ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", ctypes.c_void_p),
            ]

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = 0x0003 | 0x0004  # NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY_CALLBACK
        nid.hIcon = hicon
        nid.szTip = self._tooltip

        if not ctypes.windll.shell32.Shell_NotifyIconW(0, ctypes.byref(nid)):
            raise ctypes.WinError()

        self._nid = nid
        self._pump_id = None
        self._start_pump()

    def _start_pump(self):
        """启动消息泵"""
        def _pump():
            if not self.icon_visible:
                return
            msg = ctypes.wintypes.MSG()
            while ctypes.windll.user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, 0x0001
            ):
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            self._pump_id = self.root.after(100, _pump)
        self._pump_id = self.root.after(100, _pump)

    def _show_context_menu(self):
        """显示右键上下文菜单"""
        try:
            menu = tk.Menu(self.root, tearoff=0, font=("微软雅黑", 9))
            menu.add_command(label=t("tray.show_window"), command=self._on_menu_show)
            menu.add_separator()
            lang_label = "🌐 English" if current_lang() == "zh_CN" else "🌐 中文"
            menu.add_command(label=lang_label, command=self._on_menu_language)
            menu.add_separator()
            menu.add_command(label=t("tray.exit"), command=self._on_menu_exit)
            try:
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()
        except Exception:
            pass

    def _on_menu_show(self):
        if self.on_show:
            self.on_show()

    def _on_menu_exit(self):
        self.remove()
        if self.on_exit:
            self.root.after(0, self.on_exit)
        else:
            self.root.after(50, self.root.destroy)

    def _on_menu_language(self):
        if self.on_language:
            self.root.after(0, self.on_language)

    def show_balloon(self, title, text, duration=5):
        """显示气泡通知"""
        if not self._nid or not self.icon_visible:
            return
        try:
            nid = self._nid
            nid.uFlags = 0x0010  # NIF_INFO
            nid.szInfo = text[:255]
            nid.szInfoTitle = title[:63]
            nid.dwInfoFlags = 0x0001  # NIIF_INFO
            nid.dwState = 0
            nid.dwStateMask = 0
            ctypes.windll.shell32.Shell_NotifyIconW(0x0001, ctypes.byref(nid))
            nid.uFlags = 0x0007
            nid.szTip = self._tooltip
            ctypes.windll.shell32.Shell_NotifyIconW(0x0001, ctypes.byref(nid))
        except Exception:
            pass

    def remove(self):
        """移除托盘图标"""
        self.icon_visible = False
        if self._pump_id:
            try:
                self.root.after_cancel(self._pump_id)
            except Exception:
                pass
        if self._nid:
            try:
                ctypes.windll.shell32.Shell_NotifyIconW(
                    0x0002, ctypes.byref(self._nid)
                )
            except Exception:
                pass
            self._nid = None
        if self._hwnd:
            try:
                ctypes.windll.user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
