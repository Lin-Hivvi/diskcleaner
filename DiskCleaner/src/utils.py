# -*- coding: utf-8 -*-
"""
工具函数模块
=============
- format_size: 字节转为人类可读字符串
- get_folder_size: 递归计算文件夹大小
- get_files_sorted_by_mtime: 按修改时间排序文件
- send_to_recycle_bin: 移动到回收站
- permanently_delete: 永久删除
"""
import os
import math
import glob
import ctypes
import shutil


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
    """递归计算文件夹总大小（带异常保护）

    Args:
        folder_path: 文件夹路径

    Returns:
        int: 字节数
    """
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


def get_files_sorted_by_mtime(folder_path, pattern="*.*"):
    """获取文件夹中符合 pattern 的所有文件，按修改时间排序（旧→新）

    Args:
        folder_path: 文件夹路径
        pattern: 文件匹配模式，如 "*.log"

    Returns:
        list: [(mtime, filepath), ...]
    """
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
    """将文件/文件夹移动到回收站（使用 Shell32.SHFileOperationW）

    Args:
        paths: 文件/文件夹路径列表

    Returns:
        (成功列表, 失败列表): ([str], [(str, error)])
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
                failed.append((p, f"Error code: {result}"))
        except Exception as e:
            failed.append((p, str(e)))
    return succeeded, failed


def permanently_delete(paths, callback=None):
    """永久删除文件/文件夹列表

    Args:
        paths: 文件/文件夹路径列表
        callback: 可选回调 callback(path) 或 callback(path, error=str)

    Returns:
        (成功列表, 失败列表)
    """
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
