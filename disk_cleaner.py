# -*- coding: utf-8 -*-
"""
Windows 桌面垃圾清理工具
=========================
基于 tkinter 的 GUI 程序，可打包为独立 .exe
六大清理功能：临时文件、回收站、浏览器缓存、旧文件、最近记录、系统日志
"""

import os
import sys
import time
import math
import json
import glob
import ctypes
import shutil
import threading
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 全局常量
# ============================================================
APP_NAME = "Windows 智能垃圾清理"
APP_VERSION = "0.1"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".disk_cleaner_config.json")

# 权限相关
IS_ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0

# Windows 路径常量
CSIDL_PROFILE = 0x0028
CSIDL_RECENT = 0x0008
CSIDL_LOCAL_APPDATA = 0x001c


def get_shell_folder(csidl):
    """获取 Windows 特殊文件夹路径"""
    from ctypes import windll, create_unicode_buffer
    buf = create_unicode_buffer(260)
    windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def ensure_admin_and_restart():
    """
    检测是否以管理员权限运行；若否，则通过 ShellExecuteW 请求提权重启。
    返回 True 表示当前已是管理员；返回 False 表示已启动提权请求，本进程应退出。
    """
    if IS_ADMIN:
        return True
    try:
        script = sys.argv[0]
        if getattr(sys, 'frozen', False):
            # 打包后的 exe
            exe_path = sys.executable
        else:
            exe_path = sys.executable
            script = os.path.abspath(sys.argv[0])

        params = f'"{script}"'
        if len(sys.argv) > 1:
            params += ' ' + ' '.join(f'"{a}"' for a in sys.argv[1:])

        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, params, None, 1
        )
        if ret <= 32:
            # 用户取消或失败
            return False
        # 正常退出当前进程，让新的管理员进程接管
        sys.exit(0)
    except Exception as e:
        print(f"[警告] 提权失败: {e}")
        return False


# ============================================================
# Windows 系统托盘（纯 ctypes 实现，零外部依赖）
# ============================================================

class WindowsTrayIcon:
    """
    Windows 系统托盘图标
    使用隐藏窗口 + 消息泵，完全融入 tkinter 事件循环
    """

    WM_TRAY_CALLBACK = 0x8000  # WM_USER + 1
    _registered_classes = set()
    _proc_holder = {}  # 防止 WNDPROC 被 GC

    def __init__(self, root, icon_path=None, tooltip=APP_NAME, on_show=None, on_exit=None):
        """
        root: tkinter.Tk 实例
        icon_path: .ico 文件路径（可选，默认使用系统图标）
        tooltip: 鼠标悬浮提示
        on_show: 点击托盘图标显示窗口的回调
        on_exit: 从托盘菜单退出时的回调
        """
        self.root = root
        self.on_show = on_show
        self.on_exit = on_exit
        self.icon_visible = False
        self._nid = None
        self._hwnd = None
        self._class_atom = None
        self._tooltip = tooltip[:127]
        try:
            self._create(icon_path)
            self.icon_visible = True
        except Exception as exc:
            print(f"[托盘] 初始化跳过: {exc}")

    def _load_hicon(self, icon_path):
        """加载 .ico 文件并返回 HICON"""
        if icon_path and os.path.exists(icon_path):
            hicon = ctypes.windll.user32.LoadImageW(
                None, icon_path, 1,  # IMAGE_ICON = 1
                32, 32, 0x00000010   # LR_LOADFROMFILE
            )
            if hicon:
                return hicon
        # 回退到系统默认图标
        return ctypes.windll.user32.LoadIconW(None, 32512)  # IDI_APPLICATION

    def _register_class(self, hinstance):
        """注册隐藏窗口类（幂等）"""
        class_name = f"DiskCleanerTrayClass_{os.getpid()}"
        if class_name in self._registered_classes:
            return class_name

        from ctypes import wintypes
        # 注意：在 64 位 Windows 上，WPARAM/LPARAM/LRESULT 都是 64 位
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
            wintypes.WPARAM, wintypes.LPARAM
        )

        wc = (
            ctypes.c_uint,  # cbSize
            ctypes.c_uint,  # style
            ctypes.c_void_p,  # lpfnWndProc
            ctypes.c_int,  # cbClsExtra
            ctypes.c_int,  # cbWndExtra
            ctypes.c_void_p,  # hInstance
            ctypes.c_void_p,  # hIcon
            ctypes.c_void_p,  # hCursor
            ctypes.c_void_p,  # hbrBackground
            ctypes.c_wchar_p,  # lpszMenuName
            ctypes.c_wchar_p,  # lpszClassName
            ctypes.c_void_p,  # hIconSm
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

        # 设置 DefWindowProcW 的参数类型（64 位兼容）
        ctypes.windll.user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p,    # HWND
            ctypes.c_uint,      # UINT msg
            ctypes.c_ulonglong, # WPARAM
            ctypes.c_longlong,  # LPARAM
        ]
        ctypes.windll.user32.DefWindowProcW.restype = ctypes.c_longlong  # LRESULT

        # 定义窗口过程
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAY_CALLBACK:
                # lparam 的低位是鼠标消息
                mouse_msg = lparam & 0xFFFF
                if mouse_msg in (0x0201, 0x0203):  # WM_LBUTTONDOWN / WM_LBUTTONDBLCLK
                    if self.on_show:
                        self.root.after(0, self.on_show)
                elif mouse_msg == 0x0205:  # WM_RBUTTONUP
                    self.root.after(0, self._show_context_menu)
                return 0
            if msg == 0x0010:  # WM_CLOSE
                return 0
            # 显式类型转换确保 64 位值正确传递
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

        # 创建隐藏窗口
        self._hwnd = ctypes.windll.user32.CreateWindowExW(
            0, class_name, "TrayWindow", 0,
            0, 0, 0, 0, None, None, hinstance, None
        )
        if not self._hwnd:
            raise ctypes.WinError()

        # 加载图标
        hicon = self._load_hicon(icon_path)

        # 设置 NOTIFYICONDATA
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

        # 定期泵消息（融入 tkinter 事件循环）
        self._pump_id = None
        self._start_pump()

    def _start_pump(self):
        """启动消息泵"""
        def _pump():
            if not self.icon_visible:
                return
            msg = ctypes.wintypes.MSG()
            while ctypes.windll.user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, 0x0001  # PM_REMOVE
            ):
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            self._pump_id = self.root.after(100, _pump)
        self._pump_id = self.root.after(100, _pump)

    def _show_context_menu(self):
        """显示右键上下文菜单"""
        try:
            menu = tk.Menu(self.root, tearoff=0, font=("微软雅黑", 9))
            menu.add_command(label="显示窗口", command=self._on_menu_show)
            menu.add_separator()
            menu.add_command(label="退出程序", command=self._on_menu_exit)
            # 在鼠标位置弹出
            try:
                x = self.root.winfo_pointerx()
                y = self.root.winfo_pointery()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()
        except Exception:
            pass

    def _on_menu_show(self):
        """显示主窗口"""
        if self.on_show:
            self.on_show()

    def _on_menu_exit(self):
        """从托盘退出程序"""
        self.remove()
        if self.on_exit:
            self.root.after(0, self.on_exit)
        else:
            self.root.after(50, self.root.destroy)

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
            ctypes.windll.shell32.Shell_NotifyIconW(0x0001, ctypes.byref(nid))  # NIM_MODIFY
            # 恢复 tip
            nid.uFlags = 0x0007  # NIF_MESSAGE | NIF_ICON | NIF_TIP
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
                    0x0002, ctypes.byref(self._nid)  # NIM_DELETE
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


# ============================================================
# 日志系统
# ============================================================

class LogManager:
    """
    文件日志管理器

    - 自动按日期轮转：每天一个文件，保留最多 LOG_RETAIN_DAYS 天
    - 多级别：DEBUG / INFO / WARNING / ERROR
    - 线程安全（threading.Lock）
    - 与 GUI 日志文本框双向同步
    """

    LOG_RETAIN_DAYS = 30  # 日志文件保留天数

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        self._log_dir = self._resolve_log_dir()
        self._current_date = None
        self._file_handle = None
        self._file_lock = threading.Lock()
        self._gui_callback = None  # 由 DiskCleanerApp 注册
        self._ensure_log_dir()
        self._rotate_old_logs()

    # ---------- 初始化 ----------

    def _resolve_log_dir(self):
        """确定日志目录"""
        base = os.environ.get("TEMP", os.path.expanduser("~"))
        log_dir = os.path.join(base, "DiskCleaner", "logs")
        return log_dir

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except Exception:
            # 回退到用户目录
            fallback = os.path.join(os.path.expanduser("~"), ".disk_cleaner_logs")
            try:
                os.makedirs(fallback, exist_ok=True)
                self._log_dir = fallback
            except Exception:
                pass

    def set_gui_callback(self, callback):
        """注册 GUI 日志回调（由主程序调用）"""
        self._gui_callback = callback

    # ---------- 日志轮转 ----------

    def _rotate_old_logs(self):
        """删除超过保留天数的旧日志文件"""
        try:
            if not os.path.isdir(self._log_dir):
                return
            cutoff = time.time() - self.LOG_RETAIN_DAYS * 86400
            for fname in os.listdir(self._log_dir):
                if not fname.startswith("DiskCleaner_") or not fname.endswith(".log"):
                    continue
                fpath = os.path.join(self._log_dir, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                    if mtime < cutoff:
                        os.remove(fpath)
                except (OSError, PermissionError):
                    continue
        except Exception:
            pass  # 日志轮转失败不应影响主程序

    # ---------- 文件句柄管理 ----------

    def _get_file_handle(self):
        """获取或创建当前日期的日志文件句柄"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None
            self._current_date = today

        if self._file_handle is None:
            fpath = os.path.join(self._log_dir, f"DiskCleaner_{today}.log")
            try:
                self._file_handle = open(
                    fpath, "a", encoding="utf-8", buffering=1
                )
            except Exception:
                return None
        return self._file_handle

    # ---------- 核心日志方法 ----------

    def _write(self, level, message):
        """写入日志（线程安全）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"

        # 写入文件
        with self._file_lock:
            try:
                fh = self._get_file_handle()
                if fh:
                    fh.write(log_line + "\n")
            except Exception:
                pass

        # 回调 GUI（已格式化显示短时间戳）
        if self._gui_callback:
            try:
                short_ts = datetime.now().strftime("%H:%M:%S")
                gui_text = f"[{short_ts}] {message}"
                self._gui_callback(gui_text)
            except Exception:
                pass

    def debug(self, message):
        """调试日志"""
        self._write("DEBUG", message)

    def info(self, message):
        """信息日志"""
        self._write("INFO", message)

    def warning(self, message):
        """警告日志"""
        self._write("WARN", message)

    def error(self, message):
        """错误日志"""
        self._write("ERROR", message)

    def separator(self):
        """写入分隔线"""
        self._write("INFO", "─" * 50)

    # ---------- 查询方法 ----------

    def get_log_dir(self):
        """获取日志文件夹路径"""
        return self._log_dir

    def get_today_log_path(self):
        """获取今日日志文件路径"""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self._log_dir, f"DiskCleaner_{today}.log")

    def get_log_files(self):
        """获取所有日志文件列表（按时间倒序）"""
        if not os.path.isdir(self._log_dir):
            return []
        files = []
        for fname in os.listdir(self._log_dir):
            if fname.startswith("DiskCleaner_") and fname.endswith(".log"):
                fpath = os.path.join(self._log_dir, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                    files.append((mtime, fpath))
                except Exception:
                    continue
        files.sort(reverse=True)
        return [f[1] for f in files]

    def get_log_summary(self):
        """获取日志统计信息"""
        files = self.get_log_files()
        total_size = sum(
            os.path.getsize(f) for f in files if os.path.exists(f)
        )
        return {
            "dir": self._log_dir,
            "file_count": len(files),
            "total_size": total_size,
            "today_log": self.get_today_log_path(),
        }

    # ---------- 关闭 ----------

    def close(self):
        """关闭日志系统"""
        with self._file_lock:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None

    def __del__(self):
        self.close()


# ============================================================
# 工具函数
# ============================================================

def format_size(size_bytes):
    """将字节数转为人类可读的字符串"""
    if size_bytes < 0:
        return "0 B"
    if size_bytes == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = int(math.floor(math.log(size_bytes, 1024))) if size_bytes > 0 else 0
    i = min(i, len(units) - 1)
    val = size_bytes / (1024 ** i)
    return f"{val:.2f} {units[i]}" if i > 0 else f"{val:.0f} B"


def get_folder_size(folder_path):
    """递归计算文件夹总大小（带异常保护）"""
    total = 0
    if not os.path.exists(folder_path):
        return 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            # 跳过目录符号链接避免重复计算
            if os.path.islink(dirpath):
                continue
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if os.path.islink(fp):
                        continue
                    total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    return total


def get_files_sorted_by_mtime(folder_path, pattern="*.*"):
    """获取文件夹中符合 pattern 的所有文件，按修改时间排序（旧→新）"""
    results = []
    if not os.path.exists(folder_path):
        return results
    try:
        for f in glob.glob(os.path.join(folder_path, pattern)):
            try:
                st = os.stat(f)
                results.append((st.st_mtime, f))
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError):
        pass
    results.sort(key=lambda x: x[0])
    return results


def send_to_recycle_bin(paths):
    """
    将文件/文件夹移动到回收站（使用 Shell32.SHFileOperationW）
    返回 (成功列表, 失败列表)
    """
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.INT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 0x0003
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_SILENT = 0x0004
    FOF_NOERRORUI = 0x0400

    succeeded = []
    failed = []

    for p in paths:
        try:
            # SHFileOperation 要求双 null 结尾
            src = p + "\0\0"
            sop = SHFILEOPSTRUCTW(
                hwnd=None,
                wFunc=FO_DELETE,
                pFrom=src,
                pTo=None,
                fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
                fAnyOperationsAborted=False,
                hNameMappings=None,
                lpszProgressTitle=None,
            )
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(sop))
            if result == 0:
                succeeded.append(p)
            else:
                failed.append((p, f"错误码: {result}"))
        except Exception as e:
            failed.append((p, str(e)))
    return succeeded, failed


def permanently_delete(paths, callback=None):
    """永久删除文件/文件夹列表"""
    succeeded = []
    failed = []
    for p in paths:
        try:
            if not os.path.exists(p):
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            succeeded.append(p)
            if callback:
                callback(p)
        except Exception as e:
            failed.append((p, str(e)))
            if callback:
                callback(p, error=str(e))
    return succeeded, failed


# ============================================================
# 清理任务定义
# ============================================================

class CleanTask:
    """每个清理任务的基本单元"""

    def __init__(self, key, title, description=""):
        self.key = key          # 唯一标识
        self.title = title      # 显示标题
        self.description = description   # 详细描述
        self.enabled = True     # 是否选中
        self.scanned_size = 0   # 扫描出的垃圾大小
        self.scanned_files = 0  # 扫描出的文件数
        self.status = "未扫描"  # 未扫描 | 就绪 | 已完成 | 失败
        self.error_msg = ""

    def scan(self, log_callback=None):
        """扫描垃圾——由子类实现"""
        raise NotImplementedError

    def clean(self, use_recycle_bin=False, log_callback=None):
        """清理垃圾——由子类实现"""
        raise NotImplementedError

    def get_summary(self):
        return f"{self.title}: {format_size(self.scanned_size)} ({self.scanned_files} 项)"


# ---- 1. 系统临时文件 ----

class TempFilesTask(CleanTask):
    def __init__(self):
        super().__init__("temp_files", "📁 系统临时文件", "清理 %TEMP% 目录下的临时文件")

    def _get_temp_paths(self):
        paths = set()
        # %TEMP%
        paths.add(os.environ.get("TEMP", ""))
        paths.add(os.environ.get("TMP", ""))
        # %WINDIR%\Temp
        windir = os.environ.get("WINDIR", "C:\\Windows")
        paths.add(os.path.join(windir, "Temp"))
        # 当前用户 Local\Temp
        local_app_data = get_shell_folder(CSIDL_LOCAL_APPDATA)
        paths.add(os.path.join(local_app_data, "Temp"))
        return {p for p in paths if p and os.path.exists(p)}

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        temp_paths = self._get_temp_paths()
        for tp in temp_paths:
            if log_callback:
                log_callback(f"  扫描临时目录: {tp}")
            # 快速计算——仅统计顶层文件 + 估算子目录
            try:
                for entry in os.scandir(tp):
                    try:
                        if entry.is_file():
                            sz = entry.stat().st_size
                            self.scanned_size += sz
                            self.scanned_files += 1
                        elif entry.is_dir():
                            sz = get_folder_size(entry.path)
                            self.scanned_size += sz
                            self.scanned_files += 1
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 无法访问 {tp}: {e}")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        temp_paths = self._get_temp_paths()
        total_deleted = 0
        for tp in temp_paths:
            if log_callback:
                log_callback(f"  清理临时目录: {tp}")
            try:
                for entry in os.scandir(tp):
                    try:
                        if use_recycle_bin:
                            r, _ = send_to_recycle_bin([entry.path])
                            if r:
                                total_deleted += 1
                        else:
                            if entry.is_dir():
                                shutil.rmtree(entry.path, ignore_errors=True)
                                total_deleted += 1
                            else:
                                os.remove(entry.path)
                                total_deleted += 1
                    except (OSError, PermissionError) as e:
                        if log_callback:
                            log_callback(f"  ⚠ 跳过: {entry.name} — {e}")
                        continue
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 无法遍历 {tp}: {e}")
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 临时文件清理完毕，共处理 {total_deleted} 项")


# ---- 2. 回收站 ----

class RecycleBinTask(CleanTask):
    def __init__(self):
        super().__init__("recycle_bin", "♻ 回收站", "清空回收站")

    def _query_recycle_bin(self):
        """查询回收站状态"""
        try:
            # 使用 SHEmptyRecycleBin 的先查询大小
            # 通过 IRecycleBin 接口获取更准确的大小
            import ctypes
            # 方法1: 使用 SHQueryRecycleBin
            class SHQUERYRBINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong),
                ]

            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            # 空字符串代表所有驱动器
            ret = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
            if ret == 0:
                return info.i64Size, info.i64NumItems
            return 0, 0
        except Exception:
            return 0, 0

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        size, count = self._query_recycle_bin()
        self.scanned_size = size
        self.scanned_files = int(count)
        self.status = "就绪"
        if log_callback:
            log_callback(f"  回收站: {format_size(size)}, 共 {int(count)} 项")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        try:
            # SHEmptyRecycleBinW — 0 表示所有驱动器
            ret = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0)
            if ret != 0:
                raise Exception(f"清空回收站失败，错误码: {ret}")
            self.status = "已完成"
            if log_callback:
                log_callback("  ✅ 回收站已清空")
        except Exception as e:
            self.status = "失败"
            self.error_msg = str(e)
            if log_callback:
                log_callback(f"  ❌ 清空回收站失败: {e}")


# ---- 3. 浏览器缓存 ----

class BrowserCacheTask(CleanTask):
    def __init__(self):
        super().__init__("browser_cache", "🌐 浏览器缓存", "清理 Chrome / Edge 浏览器缓存")

    def _get_browser_cache_dirs(self):
        local_app_data = get_shell_folder(CSIDL_LOCAL_APPDATA)
        dirs = []
        # Chrome
        chrome_cache = os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "Cache")
        chrome_code_cache = os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "Code Cache")
        dirs.extend([chrome_cache, chrome_code_cache])
        # Edge
        edge_cache = os.path.join(local_app_data, "Microsoft", "Edge", "User Data", "Default", "Cache")
        edge_code_cache = os.path.join(local_app_data, "Microsoft", "Edge", "User Data", "Default", "Code Cache")
        dirs.extend([edge_cache, edge_code_cache])
        # Chrome 缓存存储 (新版)
        chrome_cache_storage = os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "CacheStorage")
        edge_cache_storage = os.path.join(local_app_data, "Microsoft", "Edge", "User Data", "Default", "CacheStorage")
        dirs.extend([chrome_cache_storage, edge_cache_storage])
        return [d for d in dirs if os.path.exists(d)]

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        dirs = self._get_browser_cache_dirs()
        if not dirs:
            self.status = "就绪"
            if log_callback:
                log_callback("  未检测到 Chrome/Edge 浏览器缓存")
            return 0
        for d in dirs:
            if log_callback:
                log_callback(f"  扫描缓存: {d}")
            # 快速统计大小（走 scandir 减少遍历）
            try:
                dir_size = 0
                file_count = 0
                for dirpath, dirnames, filenames in os.walk(d):
                    if os.path.islink(dirpath):
                        continue
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            if os.path.islink(fp):
                                continue
                            dir_size += os.path.getsize(fp)
                            file_count += 1
                        except (OSError, PermissionError):
                            continue
                self.scanned_size += dir_size
                self.scanned_files += file_count
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 无法访问 {d}: {e}")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        dirs = self._get_browser_cache_dirs()
        count = 0
        for d in dirs:
            try:
                for entry in os.scandir(d):
                    try:
                        if use_recycle_bin:
                            send_to_recycle_bin([entry.path])
                        else:
                            if entry.is_dir():
                                shutil.rmtree(entry.path, ignore_errors=True)
                            else:
                                os.remove(entry.path)
                        count += 1
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 跳过目录 {d}: {e}")
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 浏览器缓存清理完毕，处理 {count} 项")


# ---- 4. 下载文件夹旧文件 ----

class OldDownloadsTask(CleanTask):
    def __init__(self):
        super().__init__("old_downloads", "📥 下载文件夹旧文件",
                         "删除下载文件夹中超过 N 天的文件")
        self.days = 30  # 默认 30 天

    def _get_downloads_path(self):
        # 通过注册表或 Shell 获取 Downloads 路径
        try:
            # 方法1: 通过 FOLDERID_Downloads
            import ctypes
            from ctypes import wintypes
            GUID = ctypes.c_ubyte * 16
            FOLDERID_Downloads = GUID(
                0x374d, 0x29a0, 0x4c, 0x9a, 0xbd, 0x43, 0xa5, 0x76,
                0xb8, 0x7a, 0x78, 0x5c, 0x99, 0x71, 0x59, 0x1a
            )
            # 使用已知路径方式
            profile = os.environ.get("USERPROFILE", "")
            downloads = os.path.join(profile, "Downloads")
            if os.path.exists(downloads):
                return downloads
        except Exception:
            pass
        # 回退
        profile = os.environ.get("USERPROFILE", "")
        dl = os.path.join(profile, "Downloads")
        return dl if os.path.exists(dl) else None

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        dl_path = self._get_downloads_path()
        if not dl_path:
            self.status = "就绪"
            if log_callback:
                log_callback("  ⚠ 未找到下载文件夹")
            return 0
        if log_callback:
            log_callback(f"  扫描: {dl_path} (超过 {self.days} 天的文件)")
        cutoff = time.time() - self.days * 86400
        try:
            for entry in os.scandir(dl_path):
                try:
                    if entry.is_file():
                        mtime = entry.stat().st_mtime
                        if mtime < cutoff:
                            self.scanned_size += entry.stat().st_size
                            self.scanned_files += 1
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as e:
            if log_callback:
                log_callback(f"  ⚠ 无法扫描下载文件夹: {e}")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        dl_path = self._get_downloads_path()
        if not dl_path:
            self.status = "已完成"
            return 0
        cutoff = time.time() - self.days * 86400
        count = 0
        for entry in os.scandir(dl_path):
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    if use_recycle_bin:
                        send_to_recycle_bin([entry.path])
                    else:
                        os.remove(entry.path)
                    count += 1
            except (OSError, PermissionError):
                continue
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 已删除 {count} 个旧文件（超过 {self.days} 天）")


# ---- 5. 最近访问记录 ----

class RecentFilesTask(CleanTask):
    def __init__(self):
        super().__init__("recent_files", "📋 最近访问记录", "清理 Recent 文件夹中的快捷方式")

    def _get_recent_path(self):
        return get_shell_folder(CSIDL_RECENT)

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        recent = self._get_recent_path()
        if not recent or not os.path.exists(recent):
            self.status = "就绪"
            return 0
        if log_callback:
            log_callback(f"  扫描: {recent}")
        try:
            for entry in os.scandir(recent):
                try:
                    if entry.is_file():
                        self.scanned_files += 1
                        self.scanned_size += entry.stat().st_size
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as e:
            if log_callback:
                log_callback(f"  ⚠ 无法访问: {e}")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        recent = self._get_recent_path()
        if not recent or not os.path.exists(recent):
            self.status = "已完成"
            return
        count = 0
        try:
            # 方法1: 使用 Shell API 清除最近文档
            ctypes.windll.shell32.SHAddToRecentDocs(2, None)  # SHARD_DELETE
            if log_callback:
                log_callback("  📋 最近文档记录已清除（API）")
        except Exception:
            pass
        # 额外清理 .lnk 文件
        try:
            for entry in os.scandir(recent):
                try:
                    if entry.is_file():
                        if use_recycle_bin:
                            send_to_recycle_bin([entry.path])
                        else:
                            os.remove(entry.path)
                        count += 1
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as e:
            if log_callback:
                log_callback(f"  ⚠ 清理时出错: {e}")
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 最近记录已清理（删除 {count} 个快捷方式）")


# ---- 6. 系统日志 ----

class SystemLogsTask(CleanTask):
    def __init__(self):
        super().__init__("system_logs", "📜 系统日志文件",
                         "清理 Windows 系统日志和临时日志文件（可能需要管理员权限）")

    def _get_log_paths(self):
        paths = []
        windir = os.environ.get("WINDIR", "C:\\Windows")
        # Windows 日志目录
        logs_dir = os.path.join(windir, "Logs")
        if os.path.exists(logs_dir):
            paths.append(logs_dir)
        # CBS 日志（可能非常大）
        cbs = os.path.join(windir, "Logs", "CBS")
        if os.path.exists(cbs):
            paths.append(cbs)
        # Panther 日志
        panther = os.path.join(windir, "Panther")
        if os.path.exists(panther):
            paths.append(panther)
        # SoftwareDistribution 日志（下载缓存）
        soft_dist = os.path.join(windir, "SoftwareDistribution", "Download")
        if os.path.exists(soft_dist):
            paths.append(soft_dist)
        # .etl 日志文件（Windows 根目录下）
        try:
            for f in os.scandir(windir):
                if f.is_file() and f.name.lower().endswith('.etl'):
                    paths.append(f.path)
        except (OSError, PermissionError):
            pass
        # 性能日志
        perf_logs = os.path.join(windir, "Performance", "Winstore", "Diag")
        if os.path.exists(perf_logs):
            paths.append(perf_logs)
        # 内存转储文件
        memory_dmp = os.path.join(windir, "memory.dmp")
        if os.path.exists(memory_dmp):
            paths.append(memory_dmp)
        minidump_dir = os.path.join(windir, "Minidump")
        if os.path.exists(minidump_dir):
            paths.append(minidump_dir)
        return paths

    def scan(self, log_callback=None):
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        paths = self._get_log_paths()
        for p in paths:
            if log_callback:
                log_callback(f"  扫描: {p}")
            try:
                if os.path.isfile(p):
                    sz = os.path.getsize(p)
                    self.scanned_size += sz
                    self.scanned_files += 1
                elif os.path.isdir(p):
                    sz = get_folder_size(p)
                    self.scanned_size += sz
                    # 估算文件数
                    try:
                        for _, _, files in os.walk(p):
                            self.scanned_files += len(files)
                    except (OSError, PermissionError):
                        pass
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 无法访问: {e}")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = "清理中..."
        paths = self._get_log_paths()
        count = 0
        for p in paths:
            try:
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                        count += 1
                        if log_callback:
                            log_callback(f"  已删除: {p}")
                    except (OSError, PermissionError) as e:
                        if log_callback:
                            log_callback(f"  ⚠ 无法删除 {p}: {e}")
                elif os.path.isdir(p):
                    for dirpath, dirnames, filenames in os.walk(p, topdown=False):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            try:
                                os.remove(fp)
                                count += 1
                            except (OSError, PermissionError):
                                continue
                        for d in dirnames:
                            dp = os.path.join(dirpath, d)
                            try:
                                os.rmdir(dp)
                            except (OSError, PermissionError):
                                continue
                    if log_callback:
                        log_callback(f"  已清理: {p}")
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(f"  ⚠ 跳过 {p}: {e}")
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 系统日志清理完毕，处理 {count} 个文件")


# ============================================================
# 主 GUI 应用程序
# ============================================================

class DiskCleanerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("820x720")
        self.root.minsize(720, 600)

        # 设置图标（如果有）
        try:
            icon_path = self._resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        # 初始化清理任务列表
        self.tasks = [
            TempFilesTask(),
            RecycleBinTask(),
            BrowserCacheTask(),
            OldDownloadsTask(),
            RecentFilesTask(),
            SystemLogsTask(),
        ]

        # 状态变量
        self.is_running = False
        self.use_recycle_bin = tk.BooleanVar(value=True)
        self.minimize_to_tray = tk.BooleanVar(value=True)  # 最小化到托盘
        self.task_vars = {}   # key -> tk.BooleanVar

        # 日志字体
        self.log_font = ("Consolas", 9)
        self.label_font = ("微软雅黑", 10)
        self.title_font = ("微软雅黑", 11, "bold")

        # 初始化日志系统（单例）
        self.logger = LogManager()
        self.logger.set_gui_callback(self._gui_log_append)

        self._build_ui()
        self._load_config()

        # 关闭窗口时的处理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 初始化系统托盘（可选）
        self._tray_icon = None
        self._init_tray()

        # 启动日志
        self.logger.separator()
        self.log(f"🚀 {APP_NAME} v{APP_VERSION} 启动 ({'管理员' if IS_ADMIN else '普通用户'}模式)")
        self._log_startup_info()
        self.logger.separator()

    def _resource_path(self, relative_path):
        """获取资源文件路径（兼容打包后）"""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)

    # ---------- 系统托盘 ----------

    def _init_tray(self):
        """初始化系统托盘（失败时静默跳过）"""
        try:
            icon_path = self._resource_path("icon.ico")
            if not os.path.exists(icon_path):
                icon_path = None

            self._tray_icon = WindowsTrayIcon(
                root=self.root,
                icon_path=icon_path,
                tooltip=f"{APP_NAME} v{APP_VERSION}",
                on_show=self._restore_from_tray,
                on_exit=self._exit_from_tray,
            )
            if self._tray_icon.icon_visible:
                self.log("🔹 系统托盘已启用（关闭窗口将最小化到托盘）")
        except Exception:
            self._tray_icon = None

    def _restore_from_tray(self):
        """从托盘恢复窗口"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _show_tray_balloon(self, title, text):
        """显示托盘气泡通知"""
        if self._tray_icon and self._tray_icon.icon_visible:
            try:
                self._tray_icon.show_balloon(title, text)
            except Exception:
                pass

    def _exit_from_tray(self):
        """从托盘菜单退出——保存配置后完全退出"""
        self._save_config()
        if self._tray_icon:
            self._tray_icon.remove()
        self.root.destroy()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        # 主容器
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ============ 标题区 ============
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 8))

        title_label = tk.Label(
            title_frame,
            text=f"🧹 {APP_NAME}",
            font=("微软雅黑", 16, "bold"),
            fg="#2B579A"
        )
        title_label.pack(side=tk.LEFT)

        # 管理员标识
        admin_label = tk.Label(
            title_frame,
            text=" [管理员模式]" if IS_ADMIN else " [普通用户模式]",
            font=("微软雅黑", 9),
            fg="green" if IS_ADMIN else "#888"
        )
        admin_label.pack(side=tk.LEFT, padx=5, pady=(5, 0))

        # 版本信息
        ver_label = tk.Label(
            title_frame,
            text=f"v{APP_VERSION}",
            font=("微软雅黑", 8),
            fg="#999"
        )
        ver_label.pack(side=tk.RIGHT)

        # 安全提示条
        if not IS_ADMIN:
            warn_frame = tk.Frame(main_frame, bg="#FFF3CD", bd=1, relief=tk.SOLID)
            warn_frame.pack(fill=tk.X, pady=(0, 8))
            warn_text = (
                "⚠ 当前未以管理员身份运行，部分功能（系统日志清理、回收站彻底清空）可能受限。\n"
                "建议重启程序并选择「以管理员身份运行」以获得完整功能。"
            )
            warn_label = tk.Label(
                warn_frame, text=warn_text, bg="#FFF3CD",
                font=("微软雅黑", 9), fg="#856404", justify=tk.LEFT, padx=8, pady=4
            )
            warn_label.pack(fill=tk.X)

        # ============ 可滚动任务列表 ============
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Canvas + Scrollbar 实现滚动
        canvas = tk.Canvas(list_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 鼠标滚轮滚动
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        # ====== 构建每个任务卡片 ======
        self.task_labels = {}   # key -> tk.Label
        self.task_size_vars = {}  # key -> tk.StringVar

        for i, task in enumerate(self.tasks):
            var = tk.BooleanVar(value=True)
            self.task_vars[task.key] = var

            # 卡片容器
            card = tk.Frame(scroll_frame, bd=1, relief=tk.GROOVE, padx=10, pady=6, bg="#f8f9fa")
            card.pack(fill=tk.X, pady=3)

            # 第一行：复选框 + 标题 + 大小标签 + 扫描按钮
            row1 = tk.Frame(card, bg="#f8f9fa")
            row1.pack(fill=tk.X)

            cb = tk.Checkbutton(
                row1, variable=var, bg="#f8f9fa",
                font=self.label_font
            )
            cb.pack(side=tk.LEFT)

            title_lbl = tk.Label(
                row1, text=task.title, font=self.title_font,
                bg="#f8f9fa", anchor="w"
            )
            title_lbl.pack(side=tk.LEFT, padx=(0, 5))

            size_var = tk.StringVar(value="未扫描")
            size_lbl = tk.Label(
                row1, textvariable=size_var,
                font=("微软雅黑", 9), fg="#2B579A",
                bg="#f8f9fa", width=20, anchor="e"
            )
            size_lbl.pack(side=tk.RIGHT, padx=(5, 5))
            self.task_size_vars[task.key] = size_var

            scan_btn = tk.Button(
                row1, text="🔍 扫描",
                font=("微软雅黑", 9),
                command=lambda t=task: self._scan_single(t),
                bg="#E8F0FE", bd=1, padx=8, pady=1
            )
            scan_btn.pack(side=tk.RIGHT)

            # 第二行：描述
            if task.description:
                desc_lbl = tk.Label(
                    card, text=task.description,
                    font=("微软雅黑", 8), fg="#666",
                    bg="#f8f9fa", anchor="w", padx=25
                )
                desc_lbl.pack(fill=tk.X)

            # 如果是旧文件任务，额外显示天数输入
            if task.key == "old_downloads":
                days_frame = tk.Frame(card, bg="#f8f9fa", padx=25)
                days_frame.pack(fill=tk.X, pady=(2, 0))
                tk.Label(
                    days_frame, text="超过", font=("微软雅黑", 9),
                    bg="#f8f9fa"
                ).pack(side=tk.LEFT)
                self.days_var = tk.StringVar(value="30")
                days_entry = tk.Entry(
                    days_frame, textvariable=self.days_var,
                    width=5, font=("微软雅黑", 9), justify=tk.CENTER
                )
                days_entry.pack(side=tk.LEFT, padx=3)
                tk.Label(
                    days_frame, text="天的文件", font=("微软雅黑", 9),
                    bg="#f8f9fa"
                ).pack(side=tk.LEFT)

            self.task_labels[task.key] = title_lbl

        # ============ 底部按钮区 ============
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(btn_frame, text="☑ 全选",
                   command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="☐ 全不选",
                   command=self._deselect_all).pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(btn_frame, text="🔍 扫描全部",
                   command=self._scan_all).pack(side=tk.LEFT, padx=2)
        # 回收站模式
        self.recycle_cb = ttk.Checkbutton(
            btn_frame, text="移动到回收站（安全）",
            variable=self.use_recycle_bin
        )
        self.recycle_cb.pack(side=tk.LEFT, padx=2)
        # 最小化到托盘
        self.tray_cb = ttk.Checkbutton(
            btn_frame, text="最小化到托盘",
            variable=self.minimize_to_tray
        )
        self.tray_cb.pack(side=tk.LEFT, padx=8)

        btn_frame_right = ttk.Frame(btn_frame)
        btn_frame_right.pack(side=tk.RIGHT)

        ttk.Button(btn_frame_right, text="模拟运行（仅预览）",
                   command=self._simulate_run).pack(side=tk.LEFT, padx=2)

        self.clean_btn = tk.Button(
            btn_frame_right, text="🧹 开始清理",
            font=("微软雅黑", 10, "bold"),
            bg="#DC3545", fg="white", bd=1,
            padx=12, pady=2,
            command=self._start_cleanup
        )
        self.clean_btn.pack(side=tk.LEFT, padx=2)

        # ============ 进度条 ============
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            main_frame, variable=self.progress_var, maximum=100
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 4))

        self.progress_label = tk.Label(
            main_frame, text="就绪", font=("微软雅黑", 9), fg="#666",
            anchor="w"
        )
        self.progress_label.pack(fill=tk.X, pady=(0, 4))

        # ============ 日志文本框 ============
        log_frame = ttk.LabelFrame(main_frame, text="📋 运行日志", padding=3)
        log_frame.pack(fill=tk.BOTH, expand=True)

        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_text_frame, height=8, font=self.log_font,
            wrap=tk.WORD, state=tk.DISABLED,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        log_scroll = ttk.Scrollbar(log_text_frame, orient=tk.VERTICAL,
                                   command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志快捷操作栏
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(log_btn_frame, text="🧹 清空日志",
                   command=self._clear_log).pack(side=tk.LEFT, padx=1)
        ttk.Button(log_btn_frame, text="📄 导出日志",
                   command=self._export_log).pack(side=tk.LEFT, padx=1)
        ttk.Button(log_btn_frame, text="📂 日志文件夹",
                   command=self._open_log_folder).pack(side=tk.LEFT, padx=1)

    # ---------- 日志 ----------

    def log(self, message):
        """向日志文本框追加一条消息（主线程委托给 self.logger）"""
        self.logger.info(message)

    def _gui_log_append(self, formatted_message):
        """由 LogManager 回调——将格式化后的日志追加到 GUI（主线程安全）"""
        def _append():
            try:
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, formatted_message + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
                self.root.update_idletasks()
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.root.after(0, _append)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _export_log(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            title="导出日志"
        )
        if file_path:
            try:
                content = self.log_text.get(1.0, tk.END)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log(f"📄 日志已导出到: {file_path}")
            except Exception as e:
                messagebox.showerror("导出失败", f"无法导出日志:\n{e}")

    def _open_log_folder(self):
        """在资源管理器中打开日志文件夹"""
        log_dir = self.logger.get_log_dir()
        if not os.path.isdir(log_dir):
            messagebox.showinfo("提示", "日志文件夹尚未创建。")
            return
        try:
            os.startfile(log_dir)
        except Exception:
            try:
                subprocess.Popen(["explorer", log_dir])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开日志文件夹:\n{e}")

    def _log_startup_info(self):
        """启动时记录系统信息到日志"""
        info = self.logger.get_log_summary()
        self.log(f"📁 日志目录: {info['dir']}")
        self.log(f"📄 日志文件: {info['file_count']} 个，共 {format_size(info['total_size'])}")
        if info['file_count'] > 0:
            self.log(f"📌 今日日志: {info['today_log']}")

    # ---------- 按钮回调 ----------

    def _select_all(self):
        for var in self.task_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.task_vars.values():
            var.set(False)

    def _update_task_size(self, task):
        if task.scanned_size > 0:
            self.task_size_vars[task.key].set(
                f"{format_size(task.scanned_size)} ({task.scanned_files} 项)"
            )
        else:
            self.task_size_vars[task.key].set("0 B")

    def _scan_single(self, task):
        if self.is_running:
            messagebox.showinfo("提示", "当前有任务正在执行，请稍候。")
            return
        # 读取旧文件天数
        if task.key == "old_downloads":
            try:
                days = int(self.days_var.get().strip())
                if days < 1:
                    raise ValueError
                task.days = days
            except ValueError:
                messagebox.showwarning("输入错误", "请输入有效的天数（正整数）")
                return

        self.log(f"🔍 开始扫描: {task.title} ...")
        self.is_running = True
        self.root.update_idletasks()

        def _do_scan():
            try:
                task.scan(log_callback=lambda msg: self.log(msg))
                self.root.after(0, lambda: self._update_task_size(task))
                self.log(f"✅ {task.get_summary()}")
            except Exception as e:
                self.log(f"❌ 扫描失败: {e}")
            finally:
                self.is_running = False

        threading.Thread(target=_do_scan, daemon=True).start()

    def _scan_all(self):
        if self.is_running:
            messagebox.showinfo("提示", "当前有任务正在执行，请稍候。")
            return
        # 读取旧文件天数
        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t in self.tasks:
                if t.key == "old_downloads":
                    t.days = days
        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的天数（正整数）")
            return

        self.log(f"{'='*50}")
        self.log(f"🔍 开始扫描所有项目 ...")
        self.is_running = True
        self.progress_label.config(text="正在扫描...")
        self.progress_var.set(0)
        self.root.update_idletasks()

        total_tasks = len([t for t in self.tasks if t.enabled])

        def _do_scan_all():
            completed = 0
            for task in self.tasks:
                if not self.task_vars[task.key].get():
                    continue
                self.root.after(0, lambda: self.progress_label.config(
                    text=f"正在扫描: {task.title}"
                ))
                try:
                    task.scan(log_callback=lambda msg: self.log(msg))
                    self.root.after(0, lambda t=task: self._update_task_size(t))
                    self.log(f"✅ {task.get_summary()}")
                except Exception as e:
                    self.log(f"❌ {task.title} 扫描失败: {e}")
                completed += 1
                pct = int(completed / total_tasks * 100) if total_tasks else 100
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, lambda: self.progress_label.config(text="扫描完成"))
            self.root.after(0, lambda: self.progress_var.set(100))
            self.log(f"🔍 全部扫描完成！")
            self.log(f"{'='*50}")
            self.is_running = False

        threading.Thread(target=_do_scan_all, daemon=True).start()

    def _start_cleanup(self):
        """开始清理"""
        if self.is_running:
            messagebox.showinfo("提示", "当前有任务正在执行，请稍候。")
            return

        # 检查是否有选中的任务
        selected = [t for t in self.tasks if self.task_vars[t.key].get()]
        if not selected:
            messagebox.showwarning("提示", "请至少选择一个清理项目。")
            return

        # 读取天数
        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t in self.tasks:
                if t.key == "old_downloads":
                    t.days = days
        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的天数（正整数）")
            return

        # 先确保每个选中的任务都扫描过
        need_scan = [t for t in selected if t.scanned_size == 0 and t.status != "就绪"]
        if need_scan:
            result = messagebox.askyesno(
                "提示",
                f"以下项目尚未扫描: {', '.join(t.title for t in need_scan)}\n"
                "是否先执行扫描？\n\n"
                "点击「否」则跳过这些项目直接清理已扫描的部分。"
            )
            if result:
                self.log("请先点击「扫描全部」获取垃圾大小信息。")
                return

        # 计算总大小
        total_size = sum(t.scanned_size for t in selected)
        use_recycle = self.use_recycle_bin.get()

        # 确认对话框
        mode_str = "移动到回收站" if use_recycle else "永久删除"
        confirm = messagebox.askyesno(
            "确认清理",
            f"即将清理 {len(selected)} 个项目，总计 {format_size(total_size)}。\n\n"
            f"模式: {mode_str}\n"
            f"{chr(10).join(f'  · {t.title}: {format_size(t.scanned_size)}' for t in selected)}\n\n"
            "确定要继续吗？",
            icon=messagebox.WARNING
        )
        if not confirm:
            self.log("⏹ 用户取消了清理操作")
            return

        # 管理员权限检查——系统日志需要管理员
        if not IS_ADMIN:
            for t in selected:
                if isinstance(t, SystemLogsTask):
                    ret = messagebox.askyesno(
                        "权限不足",
                        "清理「系统日志文件」需要管理员权限。\n"
                        "是否以管理员身份重新启动程序？\n\n"
                        "（重启后所有清理功能将完整可用）"
                    )
                    if ret:
                        self._restart_as_admin()
                        return
                    break

        self.log(f"{'='*50}")
        self.log(f"🧹 开始清理 ... (模式: {mode_str})")
        self.is_running = True
        self.clean_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.progress_label.config(text="正在清理...")
        self.root.update_idletasks()

        def _do_clean():
            completed = 0
            total = len(selected)
            for task in selected:
                self.root.after(0, lambda t=task: self.progress_label.config(
                    text=f"正在清理: {t.title}"
                ))
                try:
                    task.clean(
                        use_recycle_bin=use_recycle,
                        log_callback=lambda msg: self.log(msg)
                    )
                except Exception as e:
                    self.log(f"❌ {task.title} 清理失败: {e}")
                completed += 1
                pct = int(completed / total * 100) if total else 100
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, self._on_cleanup_done)

        threading.Thread(target=_do_clean, daemon=True).start()

    def _on_cleanup_done(self):
        self.progress_label.config(text="清理完成")
        self.progress_var.set(100)
        self.clean_btn.config(state=tk.NORMAL)
        self.log("✅ 清理任务全部完成！")
        self.log(f"{'='*50}")
        self.is_running = False

        # 托盘气泡通知
        self._show_tray_balloon(
            "🧹 清理完成！",
            f"垃圾清理任务已全部执行完毕。"
        )

        # 完成后自动重新扫描大小
        self.log("🔄 正在重新扫描以更新状态...")
        threading.Thread(target=self._rescan_after_cleanup, daemon=True).start()

    def _rescan_after_cleanup(self):
        """清理后重新扫描，更新显示大小"""
        for task in self.tasks:
            if self.task_vars[task.key].get():
                try:
                    task.scan()
                    self.root.after(0, lambda t=task: self._update_task_size(t))
                except Exception:
                    pass
        self.root.after(0, lambda: self.log("📊 状态已更新"))

    def _simulate_run(self):
        """模拟运行——只扫描并显示将要删除的内容，不实际删除"""
        if self.is_running:
            messagebox.showinfo("提示", "当前有任务正在执行，请稍候。")
            return

        selected = [t for t in self.tasks if self.task_vars[t.key].get()]
        if not selected:
            messagebox.showwarning("提示", "请至少选择一个清理项目。")
            return

        # 读取天数
        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t in self.tasks:
                if t.key == "old_downloads":
                    t.days = days
        except ValueError:
            messagebox.showwarning("输入错误", "请输入有效的天数（正整数）")
            return

        self.log(f"{'='*50}")
        self.log("📋 [模拟运行] 开始预览——不会删除任何文件")
        self.is_running = True
        self.progress_var.set(0)
        self.progress_label.config(text="模拟扫描中...")
        self.root.update_idletasks()

        total_tasks = len(selected)

        def _do_simulate():
            completed = 0
            grand_total = 0
            for task in selected:
                self.root.after(0, lambda t=task: self.progress_label.config(
                    text=f"[模拟] 扫描: {t.title}"
                ))
                try:
                    size = task.scan(log_callback=lambda msg: self.log(msg))
                    grand_total += size
                    self.root.after(0, lambda t=task: self._update_task_size(t))
                    self.log(f"  📌 将清理 {task.title}: {format_size(size)}")
                except Exception as e:
                    self.log(f"  ⚠ {task.title}: {e}")
                completed += 1
                pct = int(completed / total_tasks * 100) if total_tasks else 0
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, lambda: self.progress_var.set(100))
            self.root.after(0, lambda: self.progress_label.config(text="模拟完成"))
            self.log(f"{'='*50}")
            self.log(f"📊 [模拟] 共可释放空间: {format_size(grand_total)}")
            self.log("💡 点击「开始清理」将实际删除这些文件")
            self.log(f"{'='*50}")
            self.is_running = False

        threading.Thread(target=_do_simulate, daemon=True).start()

    def _on_close(self):
        """窗口关闭时的处理——若托盘可用则最小化到托盘，否则退出"""
        self._save_config()
        if (self._tray_icon and self._tray_icon.icon_visible
                and self.minimize_to_tray.get()):
            try:
                self.root.withdraw()  # 隐藏到托盘
                self._tray_icon.show_balloon(
                    f"{APP_NAME}",
                    "程序已最小化到系统托盘\n双击图标可重新显示窗口"
                )
                return
            except Exception:
                pass
        # 没有托盘时直接退出
        self.logger.info("🛑 程序退出")
        self.logger.close()
        if self._tray_icon:
            self._tray_icon.remove()
        self.root.destroy()

    def _restart_as_admin(self):
        """以管理员身份重启程序"""
        self.log("🔄 正在以管理员身份重启...")
        self._save_config()
        self.logger.close()
        try:
            script = sys.argv[0]
            if getattr(sys, 'frozen', False):
                exe = sys.executable
            else:
                exe = sys.executable
                script = os.path.abspath(sys.argv[0])
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, f'"{script}"', None, 1
            )
        except Exception as e:
            self.log(f"❌ 重启失败: {e}")
            self.root.destroy()
        self.root.destroy()

    # ---------- 配置保存/加载 ----------

    def _save_config(self):
        """保存用户配置"""
        try:
            config = {
                "use_recycle_bin": self.use_recycle_bin.get(),
                "minimize_to_tray": self.minimize_to_tray.get(),
                "old_download_days": self.days_var.get() if hasattr(self, 'days_var') else "30",
                "enabled_tasks": {
                    t.key: self.task_vars[t.key].get() for t in self.tasks
                }
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f)
        except Exception:
            pass

    def _load_config(self):
        """加载用户配置"""
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "use_recycle_bin" in config:
                self.use_recycle_bin.set(config["use_recycle_bin"])
            if "minimize_to_tray" in config:
                self.minimize_to_tray.set(config["minimize_to_tray"])
            if "old_download_days" in config and hasattr(self, 'days_var'):
                self.days_var.set(config["old_download_days"])
            if "enabled_tasks" in config:
                for key, enabled in config["enabled_tasks"].items():
                    if key in self.task_vars:
                        self.task_vars[key].set(enabled)
        except Exception:
            pass


# ============================================================
# 程序入口
# ============================================================

def main():
    # ===== 自动申请管理员权限 =====
    # 若当前非管理员，自动以管理员身份重启（弹 UAC 确认框）
    # 用户点击「否」则降级以普通权限运行
    if not ensure_admin_and_restart():
        # 用户拒绝了 UAC 提权请求，以普通权限继续运行
        pass

    app = DiskCleanerApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()
