# -*- coding: utf-8 -*-
"""
应用软件缓存清理模块
=====================
支持清理 微信、QQ、TIM、企业微信、钉钉、飞书、百度网盘、WPS、迅雷
等 Windows 桌面应用的缓存文件，提供文件级选择粒度（每个缓存目录独立勾选）

本模块不依赖 disk_cleaner.py，可独立测试。
"""

import os
import shutil
import ctypes
import time
from ctypes import wintypes


# ============================================================
# 工具函数（独立实现，避免循环导入）
# ============================================================

def _get_folder_size(folder_path):
    """递归计算文件夹总大小"""
    total = 0
    if not os.path.exists(folder_path):
        return 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
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


def _send_to_recycle_bin(paths):
    """将路径列表发送到回收站"""
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
    for p in (paths if isinstance(paths, list) else [paths]):
        try:
            src = p + "\0\0"
            sop = SHFILEOPSTRUCTW(
                hwnd=None, wFunc=FO_DELETE, pFrom=src, pTo=None,
                fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
                fAnyOperationsAborted=False, hNameMappings=None, lpszProgressTitle=None,
            )
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(sop))
            if result == 0:
                succeeded.append(p)
            else:
                failed.append((p, f"Error code: {result}"))
        except Exception as e:
            failed.append((p, str(e)))
    return succeeded, failed


def _permanently_delete(paths):
    """永久删除路径列表"""
    succeeded = []
    failed = []
    for p in (paths if isinstance(paths, list) else [paths]):
        try:
            if not os.path.exists(p):
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            succeeded.append(p)
        except Exception as e:
            failed.append((p, str(e)))
    return succeeded, failed


def format_size(size_bytes):
    """字节转可读字符串（独立实现）"""
    if size_bytes <= 0:
        return "0 B"
    import math
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = min(int(math.floor(math.log(size_bytes, 1024))), len(units) - 1)
    val = size_bytes / (1024 ** i)
    return f"{val:.2f} {units[i]}" if i > 0 else f"{val:.0f} B"


# ============================================================
# 数据类
# ============================================================

class CacheItem:
    """
    单个可清理的缓存项。
    对应一个具体文件或文件夹路径，是整个系统的最小选择单元。
    """
    def __init__(self, key, name, paths, description=""):
        self.key = key                 # 唯一标识 e.g. "wechat_image"
        self.name = name               # 显示名称 e.g. "图片缓存"
        self.paths = paths if isinstance(paths, list) else [paths]
        self.description = description
        self.enabled = True            # 默认选中
        self.scanned_size = 0
        self.scanned_files = 0

    def scan(self):
        """扫描此缓存项，计算总大小和文件数"""
        total = 0
        files = 0
        for p in self.paths:
            if os.path.exists(p):
                if os.path.isfile(p):
                    try:
                        total += os.path.getsize(p)
                        files += 1
                    except (OSError, PermissionError):
                        pass
                elif os.path.isdir(p):
                    total += _get_folder_size(p)
                    try:
                        for _, _, filenames in os.walk(p):
                            files += len(filenames)
                    except (OSError, PermissionError):
                        pass
        self.scanned_size = total
        self.scanned_files = files
        return total

    def clean(self, use_recycle_bin=True):
        """清理此缓存项"""
        for p in self.paths:
            if os.path.exists(p):
                if use_recycle_bin:
                    _send_to_recycle_bin([p])
                else:
                    _permanently_delete([p])
        self.scanned_size = 0
        self.scanned_files = 0

    def actual_path(self):
        """返回实际存在的第一个路径"""
        for p in self.paths:
            if os.path.exists(p):
                return p
        return None

    def exists(self):
        """是否有路径真实存在"""
        return any(os.path.exists(p) for p in self.paths)


class SoftwareCategory:
    """
    一个软件的缓存分类。
    包含软件名称、图标和其下的多个 CacheItem。
    """
    def __init__(self, key, name, icon, items):
        self.key = key          # 唯一标识 e.g. "wechat"
        self.name = name        # 显示名称 e.g. "微信"
        self.icon = icon        # 图标 e.g. "💬"
        self.items = items      # list of CacheItem
        self.enabled = True     # 软件级别开关
        self._expanded = True   # UI 展开状态

    @property
    def scanned_size(self):
        return sum(i.scanned_size for i in self.items if i.enabled)

    @property
    def scanned_files(self):
        return sum(i.scanned_files for i in self.items if i.enabled)

    @property
    def total_enabled_items(self):
        return sum(1 for i in self.items if i.enabled)

    def scan(self):
        """扫描此软件下所有启用的缓存项"""
        for item in self.items:
            if item.enabled:
                item.scan()

    def clean(self, use_recycle_bin=True):
        """清理此软件下所有启用的缓存项"""
        for item in self.items:
            if item.enabled:
                item.clean(use_recycle_bin)

    def any_exist(self):
        """是否有任何缓存项存在"""
        return any(i.exists() for i in self.items)


# ============================================================
# 各软件路径发现函数
# ============================================================

def _appdata():
    return os.environ.get("APPDATA", "")

def _local_appdata():
    return os.environ.get("LOCALAPPDATA", "")

def _userprofile():
    return os.environ.get("USERPROFILE", "")


def _documents():
    """
    获取用户文档目录（Documents / 文档）

    优先级：
      1. SHGetFolderPathW(CSIDL_PERSONAL) — 最权威，适应任意语言系统
      2. 常见路径名（Documents / 文档）
    """
    # 第 1 优先：Windows API CSIDL_PERSONAL (0x0005)
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0005, None, 0, buf) == 0:
            path = buf.value
            if path and os.path.exists(path):
                return path
    except Exception:
        pass

    # 第 2 优先：常见路径名（兼容中文/英文）
    profile = _userprofile()
    for name in ("Documents", "文档", "我的文档"):
        path = os.path.join(profile, name)
        if os.path.exists(path):
            return path

    # 兜底：返回 c:/Users/xxx/Documents
    return os.path.join(profile, "Documents")


def _scan_dir_sizes(base_dir):
    """扫描一个目录下所有子目录的大小，返回 {name: size_in_bytes}"""
    result = {}
    if not os.path.exists(base_dir):
        return result
    for entry in os.scandir(base_dir):
        if entry.is_dir():
            try:
                sz = _get_folder_size(entry.path)
                if sz > 0:
                    result[entry.name] = sz
            except (OSError, PermissionError):
                pass
    return result


# ============================================================
# 微信 - WeChat（传统版 + xwechat 新架构版）
# ============================================================

def _find_wxid_subdirs(base):
    """在 base 下找到所有包含 'wxid' 的子目录"""
    if not os.path.exists(base):
        return []
    try:
        return [
            os.path.join(base, d.name)
            for d in os.scandir(base)
            if d.is_dir() and "wxid" in d.name
        ]
    except (OSError, PermissionError):
        return []


def _discover_classic_wechat():
    r"""
    传统微信 (WeChat) 缓存目录发现。

    典型路径：
      %APPDATA%\Tencent\WeChat\[wxid_xxx]\FileStorage\
      %USERPROFILE%\Documents\WeChat Files\[wxid_xxx]\FileStorage\
    """
    candidates = [
        os.path.join(_appdata(), "Tencent", "WeChat"),
        os.path.join(_local_appdata(), "Tencent", "WeChat"),
        os.path.join(_documents(), "WeChat Files"),
        os.path.join(_documents(), "Tencent", "WeChat Files"),
    ]
    items = []
    for base in candidates:
        if not os.path.exists(base):
            continue
        wxid_dirs = _find_wxid_subdirs(base)
        for d in wxid_dirs:
            fs = os.path.join(d, "FileStorage")
            if not os.path.exists(fs):
                continue
            tag = d.replace(":", "").replace("\\", "/")[-20:]
            items += [
                CacheItem(f"wc_img_{tag}",   "图片缓存",   os.path.join(fs, "Image"),   "聊天中的图片文件"),
                CacheItem(f"wc_vid_{tag}",   "视频缓存",   os.path.join(fs, "Video"),   "聊天中的视频文件"),
                CacheItem(f"wc_voi_{tag}",   "语音缓存",   os.path.join(fs, "Voice"),   "语音消息缓存"),
                CacheItem(f"wc_file_{tag}",  "接收文件",   os.path.join(fs, "File"),    "通过微信接收的文件"),
                CacheItem(f"wc_emo_{tag}",   "表情缓存",   os.path.join(fs, "Emotion"), "表情图片缓存"),
                CacheItem(f"wc_avt_{tag}",   "头像缓存",   os.path.join(fs, "Avatar"),  "联系人头像"),
                CacheItem(f"wc_log_{tag}",   "日志文件",   os.path.join(d, "Log"),      "运行日志"),
            ]
        # 兜底：没有 wxid 目录时直接扫基础目录
        if not wxid_dirs:
            for sub in ["FileStorage", "Log", "Cache"]:
                p = os.path.join(base, sub)
                if os.path.exists(p):
                    items.append(CacheItem(f"wc_{sub.lower()}", f"微信{_name_cn(sub)}", p))
    return items


def _discover_xwechat():
    r"""
    新版微信 (xwechat/"小微信") 缓存目录发现。

    xwechat 是微信的新架构版本，路径完全不同：
      安装目录: %APPDATA%\Tencent\xwechat\
      数据目录: %USERPROFILE%\Documents\xwechat_files\[wxid_xxx]\
    """
    install_base = os.path.join(_appdata(), "Tencent", "xwechat")
    data_base = os.path.join(_documents(), "xwechat_files")
    items = []

    # ── 安装目录 ──
    if os.path.exists(install_base):
        for sub, name, desc in [
            ("log",      "运行日志",   "应用运行日志"),
            ("update",   "更新缓存",   "自动更新下载包"),
            ("crashinfo","崩溃转储",   "崩溃日志/内存转储"),
        ]:
            p = os.path.join(install_base, sub)
            if os.path.exists(p):
                items.append(CacheItem(f"xwc_{sub}", name, p, desc))

    # ── 数据目录 ──
    if not os.path.exists(data_base):
        return items

    wxid_dirs = _find_wxid_subdirs(data_base)
    # 也可能在 all_users 下
    all_users = os.path.join(data_base, "all_users")
    if os.path.exists(all_users):
        wxid_dirs += _find_wxid_subdirs(all_users)

    for d in wxid_dirs:
        tag = d.replace(":", "").replace("\\", "/")[-16:]

        # 通用缓存 / 临时文件（安全清理）
        for sub, name, desc in [
            ("cache",            "应用缓存",     "通用缓存数据"),
            ("temp",             "临时文件",     "临时缓存文件"),
            ("apm_record",       "性能记录",     "应用性能监控日志"),
        ]:
            p = os.path.join(d, sub)
            if os.path.exists(p):
                items.append(CacheItem(f"xwc_{sub}_{tag}", name, p, desc))

        # 聊天消息附件（用户数据，默认关闭）
        msg_dir = os.path.join(d, "msg")
        if os.path.exists(msg_dir):
            for sub, name, desc in [
                ("attach", "聊天附件", "聊天中的附件文件"),
                ("file",   "接收文件", "通过微信接收的文件"),
                ("video",  "视频文件", "聊天中的视频文件"),
            ]:
                p = os.path.join(msg_dir, sub)
                if os.path.exists(p):
                    ci = CacheItem(f"xwc_msg_{sub}_{tag}", name, p, desc)
                    ci.enabled = False  # 用户数据默认不选，由用户自主决定
                    items.append(ci)

        # 业务缓存（安全清理，会重新下载）
        biz_dir = os.path.join(d, "business")
        if os.path.exists(biz_dir):
            for sub, name, desc in [
                ("emoticon", "表情缓存", "表情图片缓存（会重新下载）"),
                ("xweb",     "网页缓存", "内置浏览器网页缓存"),
                ("sns",      "朋友圈缓存","朋友圈图片/数据缓存"),
            ]:
                p = os.path.join(biz_dir, sub)
                if os.path.exists(p):
                    items.append(CacheItem(f"xwc_biz_{sub}_{tag}", name, p, desc))

        # 头像缓存
        headimg = os.path.join(d, "db_storage", "head_image")
        if os.path.exists(headimg):
            items.append(CacheItem(f"xwc_head_{tag}", "头像缓存", headimg, "联系人头像缓存"))

        # 资源文件缓存
        resource_dir = os.path.join(d, "resource")
        if os.path.exists(resource_dir):
            items.append(CacheItem(f"xwc_res_{tag}", "资源文件缓存", resource_dir, "应用资源文件缓存"))

    return items


def discover_wechat():
    r"""
    统一发现所有微信版本的缓存目录。

    同时支持：
      - 传统微信 (WeChat): %APPDATA%\Tencent\WeChat + Documents\WeChat Files
      - 新架构微信 (xwechat): %APPDATA%\Tencent\xwechat + Documents\xwechat_files
    """
    items = _discover_classic_wechat() + _discover_xwechat()
    return _dedup_items(items)


def _name_cn(name):
    """英文目录名 -> 中文描述"""
    mapping = {
        "Image": "图片", "Video": "视频", "Voice": "语音",
        "File": "文件", "Emotion": "表情", "Avatar": "头像",
        "Log": "日志", "Cache": "缓存", "Temp": "临时文件",
        "FileStorage": "文件存储",
    }
    return mapping.get(name, name)


def _dedup_items(items):
    """根据 paths 去重 CacheItem（路径相同的不重复添加）"""
    seen_paths = set()
    result = []
    for item in items:
        paths_tuple = tuple(sorted(str(p) for p in item.paths))
        if paths_tuple not in seen_paths:
            seen_paths.add(paths_tuple)
            result.append(item)
    return result


# ============================================================
# QQ
# ============================================================

def discover_qq():
    r"""
    QQ 缓存目录发现。

    支持：
      - 经典版: %APPDATA%\Tencent\QQ\[QQ号码]\
      - QQ NT 版: %LOCALAPPDATA%\Tencent\QQ\UserData\QQ号码\
      - 通用临时目录: %APPDATA%\Tencent\QQ\STemp
    """
    candidates = [
        os.path.join(_appdata(), "Tencent", "QQ"),
        os.path.join(_local_appdata(), "Tencent", "QQ"),
        os.path.join(_local_appdata(), "Tencent", "QQ", "UserData"),
    ]
    items = []

    for base in candidates:
        if not os.path.exists(base):
            continue
        try:
            # 查找 QQ 号目录（纯数字）
            qq_dirs = [os.path.join(base, d.name) for d in os.scandir(base)
                       if d.is_dir() and d.name.isdigit()]
        except (OSError, PermissionError):
            qq_dirs = []

        for d in qq_dirs:
            items += [
                CacheItem("qq_image",      "图片缓存",     os.path.join(d, "Image"),      "聊天图片"),
                CacheItem("qq_file_recv",  "接收文件",     os.path.join(d, "FileRecv"),   "接收的文件"),
                CacheItem("qq_custom_face","表情缓存",     [os.path.join(d, "CustomFace"),
                                                           os.path.join(d, "Face")],     "聊天表情"),
                CacheItem("qq_headimg",    "头像缓存",     os.path.join(d, "HeadImg"),    "联系人头像"),
                CacheItem("qq_video",      "视频缓存",     os.path.join(d, "Video"),      "聊天视频"),
                CacheItem("qq_record",     "语音缓存",     os.path.join(d, "Record"),     "语音消息"),
                CacheItem("qq_log",        "日志文件",     os.path.join(d, "Log"),        "运行日志"),
                CacheItem("qq_update",     "更新缓存",     os.path.join(d, "Update"),     "自动更新下载包"),
            ]

    # 全局临时目录（不特定于某个 QQ 号）
    stemp = os.path.join(_appdata(), "Tencent", "QQ", "STemp")
    if os.path.exists(stemp):
        items.append(CacheItem("qq_stemp", "安装临时文件", stemp, "QQ 安装/更新临时文件"))

    global_panel = os.path.join(_appdata(), "Tencent", "QQ", "Global", "Panel")
    if os.path.exists(global_panel):
        items.append(CacheItem("qq_panel", "面板缓存", global_panel, "QQ 面板/界面缓存"))

    return _dedup_items(items)


# ============================================================
# TIM
# ============================================================

def discover_tim():
    """TIM 缓存目录"""
    base = os.path.join(_appdata(), "Tencent", "TIM")
    if not os.path.exists(base):
        return []
    try:
        tim_dirs = [os.path.join(base, d.name) for d in os.scandir(base)
                    if d.is_dir() and d.name.isdigit()]
    except (OSError, PermissionError):
        tim_dirs = []
    items = []
    for d in tim_dirs:
        items += [
            CacheItem("tim_image",      "图片缓存",   os.path.join(d, "Image"),      "聊天图片"),
            CacheItem("tim_file_recv",  "接收文件",   os.path.join(d, "FileRecv"),   "接收的文件"),
            CacheItem("tim_custom_face","表情缓存",   [os.path.join(d, "CustomFace"),
                                                       os.path.join(d, "Face")],     "聊天表情"),
            CacheItem("tim_headimg",    "头像缓存",   os.path.join(d, "HeadImg"),    "联系人头像"),
            CacheItem("tim_video",      "视频缓存",   os.path.join(d, "Video"),      "聊天视频"),
            CacheItem("tim_log",        "日志文件",   os.path.join(d, "Log"),        "运行日志"),
        ]
    return items


# ============================================================
# 企业微信 - WXWork / WeCom
# ============================================================

def discover_wework():
    """
    企业微信缓存目录发现。

    实际存在的可清理目录（依据真实用户系统调查）：
      - upgrade:   更新下载包（最大！可达数 GB）
      - wmpf_Applet: 小程序框架缓存
      - cef:       Chromium 浏览器内核缓存
      - WeChatOCR: OCR 识别模型缓存
      - patch:     补丁文件
      - AIModel:   AI 模型缓存
      - Log:       运行日志
      - Network:   网络数据缓存
      - Applet:    小程序缓存
      - compatible_cef: 兼容 CEF 缓存
    """
    base = os.path.join(_appdata(), "Tencent", "WXWork")
    if not os.path.exists(base):
        return []
    items = [
        CacheItem("wework_upgrade",      "更新下载包", os.path.join(base, "upgrade"),
                  "自动更新下载的安装包（安全清理）"),
        CacheItem("wework_wmpf_applet",  "小程序框架缓存", os.path.join(base, "wmpf_Applet"),
                  "小程序运行框架产生的缓存数据"),
        CacheItem("wework_cef",          "浏览器内核缓存", os.path.join(base, "cef"),
                  "Chromium 嵌入式浏览器缓存（可安全清理）"),
        CacheItem("wework_wechat_ocr",   "OCR 识别缓存", os.path.join(base, "WeChatOCR"),
                  "图片文字识别模型缓存（可重新下载）"),
        CacheItem("wework_patch",        "补丁文件", os.path.join(base, "patch"),
                  "历史补丁备份（安全清理）"),
        CacheItem("wework_ai_model",     "AI 模型缓存", os.path.join(base, "AIModel"),
                  "AI 功能模型文件缓存"),
        CacheItem("wework_log",          "运行日志", os.path.join(base, "Log"),
                  "程序运行日志"),
        CacheItem("wework_network",      "网络数据缓存", os.path.join(base, "Network"),
                  "网络请求缓存数据"),
        CacheItem("wework_applet",       "小程序缓存", os.path.join(base, "Applet"),
                  "小程序缓存数据"),
        CacheItem("wework_compatible_cef","兼容 CEF 缓存", os.path.join(base, "compatible_cef"),
                  "兼容模式浏览器缓存"),
    ]
    return [i for i in items if i.exists()]


# ============================================================
# 钉钉 - DingTalk
# ============================================================

def discover_dingtalk():
    """钉钉缓存目录（支持 Roaming 和 Local 路径）"""
    candidates = [
        os.path.join(_appdata(), "DingTalk"),
        os.path.join(_appdata(), "DingDing"),
        os.path.join(_local_appdata(), "DingTalk"),
    ]
    for base in candidates:
        if not os.path.exists(base):
            continue
        items = [
            CacheItem("dingtalk_log",      "运行日志", [os.path.join(base, "log"),
                                                        os.path.join(base, "logs")], "运行日志"),
            CacheItem("dingtalk_cache",    "应用缓存", [os.path.join(base, "cache"),
                                                        os.path.join(base, "Cache")], "应用数据缓存"),
            CacheItem("dingtalk_download", "下载文件", [os.path.join(base, "download"),
                                                        os.path.join(base, "Download")], "下载的临时文件"),
            CacheItem("dingtalk_image",    "图片缓存", [os.path.join(base, "image"),
                                                        os.path.join(base, "Image")], "聊天图片缓存"),
        ]
        return [i for i in items if i.exists()]
    return []


# ============================================================
# 飞书 - Feishu / Lark
# ============================================================

def discover_feishu():
    """飞书 / Lark 缓存目录"""
    candidates = [
        os.path.join(_appdata(), "Feishu"),
        os.path.join(_appdata(), "Lark"),
        os.path.join(_appdata(), "Lark Technologies", "Lark"),
        os.path.join(_appdata(), "Bytenext", "Feishu"),
        os.path.join(_local_appdata(), "Feishu"),
        os.path.join(_local_appdata(), "Lark"),
    ]
    for base in candidates:
        if not os.path.exists(base):
            continue
        items = [
            CacheItem("feishu_cache", "应用缓存", [os.path.join(base, "cache"),
                                                   os.path.join(base, "Cache")], "应用数据缓存"),
            CacheItem("feishu_log",   "日志文件", [os.path.join(base, "logs"),
                                                   os.path.join(base, "Logs")], "运行日志"),
            CacheItem("feishu_temp",  "临时文件", [os.path.join(base, "temp"),
                                                   os.path.join(base, "Temp")], "临时缓存文件"),
        ]
        return [i for i in items if i.exists()]
    return []


# ============================================================
# 百度网盘 - Baidu NetDisk
# ============================================================

def discover_baidunetdisk():
    """百度网盘缓存目录"""
    candidates = [
        os.path.join(_appdata(), "Baidu", "BaiduNetDisk"),
        os.path.join(_appdata(), "Baidu", "BaiduNetDisk", "users"),
        os.path.join(_local_appdata(), "Baidu", "BaiduNetDisk"),
    ]
    for base in candidates:
        if not os.path.exists(base):
            continue
        items = [
            CacheItem("baidu_cache", "下载缓存", [os.path.join(base, "cache"),
                                                  os.path.join(base, "Cache")], "文件预览和下载缓存"),
            CacheItem("baidu_log",   "日志文件", [os.path.join(base, "logs"),
                                                  os.path.join(base, "Logs")], "运行日志"),
            CacheItem("baidu_thumb", "缩略图缓存",
                      [os.path.join(base, "thumb", "Thumb"),
                       os.path.join(base, "Thumbnails")], "文件缩略图缓存"),
        ]
        return [i for i in items if i.exists()]
    return []


# ============================================================
# WPS Office
# ============================================================

def discover_wps():
    """WPS Office 缓存和临时目录"""
    candidates = [
        os.path.join(_appdata(), "Kingsoft", "WPS Office"),
        os.path.join(_local_appdata(), "Kingsoft", "WPS Office"),
    ]
    items = []
    for base in candidates:
        if not os.path.exists(base):
            continue
        # 查找版本目录（名称含数字的目录）
        try:
            entries = list(os.scandir(base))
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if any(c.isdigit() for c in entry.name):
                vpath = entry.path
                for sub in ["cache", "Cache", "temp", "Temp", "update", "Update"]:
                    p = os.path.join(vpath, sub)
                    if os.path.exists(p):
                        items.append(CacheItem(
                            f"wps_{entry.name[:8]}", f"{entry.name[:12]} 缓存", p
                        ))
        # addons 目录（插件安装包）
        addons = os.path.join(base, "addons")
        if os.path.exists(addons):
            items.append(CacheItem("wps_addons", "插件缓存", addons, "WPS 插件安装包缓存"))
        break  # 只处理第一个找到的基础路径
    return items


def discover_wps_cloud():
    """WPS 云文档缓存"""
    base = os.path.join(_documents(), "Kingsoft", "WPS Cloud")
    if not os.path.exists(base):
        return []
    items = [
        CacheItem("wps_cloud_cache", "WPS 云缓存",
                  os.path.join(base, "cache"), "WPS 云文档同步缓存"),
    ]
    return [i for i in items if i.exists()]


# ============================================================
# 迅雷 - Thunder
# ============================================================

def discover_thunder():
    """迅雷 (Thunder) 缓存目录"""
    candidates = [
        os.path.join(_appdata(), "Thunder Network", "Thunder"),
        os.path.join(_appdata(), "Thunder Network", "Thunder", "Profiles"),
        os.path.join(_local_appdata(), "Thunder", "Thunder"),
    ]
    for base in candidates:
        if not os.path.exists(base):
            continue
        items = [
            CacheItem("thunder_cache", "下载缓存", [os.path.join(base, "Cache"),
                                                    os.path.join(base, "cache")], "下载临时缓存"),
            CacheItem("thunder_log",   "日志文件", [os.path.join(base, "Log"),
                                                    os.path.join(base, "log")], "运行日志"),
            CacheItem("thunder_temp",  "临时文件", [os.path.join(base, "Temp"),
                                                    os.path.join(base, "temp")], "临时数据"),
        ]
        return [i for i in items if i.exists()]
    return []


# ============================================================
# 软件定义注册表 —— 新增软件只需在此添加
# ============================================================

SOFTWARE_DEFINITIONS = [
    ("wechat",      "微信",     "💬", discover_wechat),
    ("qq",          "QQ",       "🐧", discover_qq),
    ("tim",         "TIM",      "🕐", discover_tim),
    ("wework",      "企业微信", "🏢", discover_wework),
    ("dingtalk",    "钉钉",     "📌", discover_dingtalk),
    ("feishu",      "飞书",     "📘", discover_feishu),
    ("baidunetdisk","百度网盘", "☁️", discover_baidunetdisk),
    ("wps",         "WPS Office", "📝", discover_wps),
    ("wps_cloud",   "WPS 云服务","☁️", discover_wps_cloud),
    ("thunder",     "迅雷",     "⚡", discover_thunder),
]


def discover_all_categories():
    """
    自动发现所有已安装软件的缓存目录。
    返回: list of SoftwareCategory（仅包含实际存在的）
    """
    categories = []
    for key, name, icon, discover_fn in SOFTWARE_DEFINITIONS:
        try:
            items = discover_fn()
        except Exception:
            continue
        if items:
            categories.append(SoftwareCategory(key, name, icon, items))
    return categories


# ============================================================
# 统一清理任务接口（与 disk_cleaner.py 的 CleanTask 协议兼容）
# ============================================================

class AppSoftwareTask:
    """
    应用软件缓存清理任务（适配 disk_cleaner.py 的任务接口）

    包含多个 SoftwareCategory，每个又包含多个 CacheItem，
    实现文件级的自由选择。
    """
    def __init__(self):
        self.key = "app_software"
        self.title = "📱 应用软件缓存"
        self.description = "清理微信/QQ/钉钉/飞书等应用产生的缓存和数据文件（支持逐项选择）"
        self.enabled = True
        self.status = "未扫描"
        self.error_msg = ""
        self.scanned_size = 0
        self.scanned_files = 0
        self.categories = discover_all_categories()

    def get_summary(self):
        return f"{self.title}: {format_size(self.scanned_size)} ({self.scanned_files} 项)"

    # ----- 兼容 CleanTask 的 scan / clean 接口 -----

    def scan(self, log_callback=None):
        """扫描所有启用的软件缓存"""
        self.status = "扫描中..."
        self.scanned_size = 0
        self.scanned_files = 0
        for cat in self.categories:
            if not cat.enabled:
                continue
            if log_callback:
                log_callback(f"  📱 扫描: {cat.icon} {cat.name}")
            cat.scan()
            self.scanned_size += cat.scanned_size
            self.scanned_files += cat.scanned_files
            if log_callback:
                log_callback(f"     → {format_size(cat.scanned_size)} ({len([i for i in cat.items if i.enabled])} 项)")
        self.status = "就绪"
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        """清理所有启用的软件缓存项"""
        self.status = "清理中..."
        total_count = 0
        for cat in self.categories:
            if not cat.enabled:
                continue
            if log_callback:
                log_callback(f"  🧹 清理: {cat.icon} {cat.name}")
            cat.clean(use_recycle_bin)
            enabled_items = [i for i in cat.items if i.enabled]
            total_count += len(enabled_items)
            if log_callback:
                log_callback(f"     ✅ {len(enabled_items)} 项已清理")
        self.scanned_size = 0
        self.scanned_files = 0
        self.status = "已完成"
        if log_callback:
            log_callback(f"  ✅ 应用软件缓存清理完毕，共处理 {total_count} 项")

    # ----- 逐项扫描/清理（供 UI 中单软件扫描按钮使用）-----

    def scan_category(self, cat_key, log_callback=None):
        """扫描单个软件分类"""
        for cat in self.categories:
            if cat.key == cat_key and cat.enabled:
                cat.scan()
                # 更新 totals
                self.scanned_size = sum(c.scanned_size for c in self.categories if c.enabled)
                self.scanned_files = sum(c.scanned_files for c in self.categories if c.enabled)
                if log_callback:
                    log_callback(f"  📱 {cat.icon} {cat.name}: {format_size(cat.scanned_size)}")
                return cat.scanned_size
        return 0

    # ----- 配置持久化 -----

    def save_state(self):
        """导出各项选中状态为可序列化的 dict"""
        state = {}
        for cat in self.categories:
            for item in cat.items:
                state[f"{cat.key}.{item.key}"] = item.enabled
            state[f"{cat.key}._enabled"] = cat.enabled
            state[f"{cat.key}._expanded"] = cat._expanded
        return state

    def load_state(self, state):
        """从 dict 恢复各项选中状态"""
        if not state:
            return
        for cat in self.categories:
            cat.enabled = state.get(f"{cat.key}._enabled", True)
            cat._expanded = state.get(f"{cat.key}._expanded", True)
            for item in cat.items:
                k = f"{cat.key}.{item.key}"
                if k in state:
                    item.enabled = state[k]

    # ----- 统计 -----

    def get_enabled_software_count(self):
        """获取启用的软件数"""
        return sum(1 for c in self.categories if c.enabled)

    def get_enabled_item_count(self):
        """获取启用的缓存项数"""
        return sum(c.total_enabled_items for c in self.categories if c.enabled)

    def get_total_size(self):
        """获取所有软件的总扫描大小"""
        return sum(c.scanned_size for c in self.categories if c.enabled)
