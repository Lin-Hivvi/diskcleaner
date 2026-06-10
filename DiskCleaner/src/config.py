# -*- coding: utf-8 -*-
"""
全局配置与常量模块
===================
- 应用名称/版本
- Windows 特殊文件夹 CSIDL
- 管理员权限检测与提权
"""
import os
import sys
import ctypes
from src.i18n import t

# ============================================================
# 应用信息
# ============================================================
APP_NAME = t("app.name")
APP_VERSION = t("app.version")
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".disk_cleaner_config.json")

# ============================================================
# 权限检测
# ============================================================
IS_ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0

# ============================================================
# Windows 特殊文件夹常量 (CSIDL)
# ============================================================
CSIDL_PROFILE = 0x0028
CSIDL_RECENT = 0x0008
CSIDL_LOCAL_APPDATA = 0x001c


def get_shell_folder(csidl):
    """获取 Windows 特殊文件夹路径

    Args:
        csidl: CSIDL 常量值

    Returns:
        str: 文件夹路径
    """
    from ctypes import windll, create_unicode_buffer
    buf = create_unicode_buffer(260)
    windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def ensure_admin_and_restart():
    """
    检测是否以管理员权限运行；若否，则通过 ShellExecuteW 请求提权重启。

    Returns:
        bool: True 表示当前已是管理员；False 表示已发起提权请求，本进程应退出。
    """
    if IS_ADMIN:
        return True
    try:
        script = sys.argv[0]
        if getattr(sys, 'frozen', False):
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
            return False
        sys.exit(0)
    except Exception as e:
        print(f"[Warning] Privilege escalation failed: {e}")
        return False
