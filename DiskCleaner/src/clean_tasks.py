# -*- coding: utf-8 -*-
"""
清理任务模块
=============
定义所有清理任务类：
- CleanTask        基础抽象类
- TempFilesTask    系统临时文件
- RecycleBinTask   回收站
- BrowserCacheTask 浏览器缓存
- OldDownloadsTask  下载文件夹旧文件
- RecentFilesTask   最近访问记录
- SystemLogsTask    系统日志
"""
import os
import time
import glob
import ctypes
import shutil
from datetime import datetime
from src.config import get_shell_folder, CSIDL_LOCAL_APPDATA, CSIDL_RECENT
from src.utils import format_size, get_folder_size, send_to_recycle_bin
from src.i18n import t


# ============================================================
# 清理任务基类
# ============================================================

class CleanTask:
    """每个清理任务的基本单元"""

    def __init__(self, key, title, description=""):
        self.key = key                     # 唯一标识
        self.title = title                 # 显示标题
        self.description = description     # 详细描述
        self.enabled = True                # 是否选中
        self.scanned_size = 0              # 扫描出的垃圾大小
        self.scanned_files = 0             # 扫描出的文件数
        self.status = t("scan.status_unscanned")  # 未扫描 | 就绪 | 已完成 | 失败
        self.error_msg = ""

    def scan(self, log_callback=None):
        """扫描垃圾——由子类实现"""
        raise NotImplementedError

    def clean(self, use_recycle_bin=False, log_callback=None):
        """清理垃圾——由子类实现"""
        raise NotImplementedError

    def get_summary(self):
        return t("scan.summary", title=self.title,
                 size=format_size(self.scanned_size), count=self.scanned_files)


# ============================================================
# 1. 系统临时文件
# ============================================================

class TempFilesTask(CleanTask):
    def __init__(self):
        super().__init__("temp_files", t("task.temp_files.title"),
                         t("task.temp_files.desc"))

    def _get_temp_paths(self):
        paths = set()
        paths.add(os.environ.get("TEMP", ""))
        paths.add(os.environ.get("TMP", ""))
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or ""
        if windir:
            paths.add(os.path.join(windir, "Temp"))
        local_app_data = get_shell_folder(CSIDL_LOCAL_APPDATA)
        paths.add(os.path.join(local_app_data, "Temp"))
        return {p for p in paths if p and os.path.exists(p)}

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        self.scanned_size = 0
        self.scanned_files = 0
        temp_paths = self._get_temp_paths()
        for tp in temp_paths:
            if log_callback:
                log_callback(t("task.temp_files.scanning", path=tp))
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
                    log_callback(t("task.temp_files.skip", path=tp, error=e))
        self.status = t("scan.status_ready")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
        temp_paths = self._get_temp_paths()
        total_deleted = 0
        for tp in temp_paths:
            if log_callback:
                log_callback(t("task.temp_files.cleaning", path=tp))
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
                            log_callback(t("task.temp_files.skip_entry",
                                           name=entry.name, error=e))
                        continue
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(t("task.temp_files.skip", path=tp, error=e))
        self.status = t("scan.status_completed")
        if log_callback:
            log_callback(t("task.temp_files.done", count=total_deleted))


# ============================================================
# 2. 回收站
# ============================================================

class RecycleBinTask(CleanTask):
    def __init__(self):
        super().__init__("recycle_bin", t("task.recycle_bin.title"),
                         t("task.recycle_bin.desc"))

    def _query_recycle_bin(self):
        """查询回收站状态"""
        try:
            class SHQUERYRBINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong),
                ]

            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            ret = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
            if ret == 0:
                return info.i64Size, info.i64NumItems
            return 0, 0
        except Exception:
            return 0, 0

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        size, count = self._query_recycle_bin()
        self.scanned_size = size
        self.scanned_files = int(count)
        self.status = t("scan.status_ready")
        if log_callback:
            log_callback(t("task.recycle_bin.scan_result",
                           size=format_size(size), count=int(count)))
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
        try:
            ret = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0)
            if ret != 0:
                raise Exception(f"Error code: {ret}")
            self.status = t("scan.status_completed")
            if log_callback:
                log_callback(t("task.recycle_bin.done"))
        except Exception as e:
            self.status = t("scan.status_failed")
            self.error_msg = str(e)
            if log_callback:
                log_callback(t("task.recycle_bin.failed", error=e))


# ============================================================
# 3. 浏览器缓存
# ============================================================

class BrowserCacheTask(CleanTask):
    def __init__(self):
        super().__init__("browser_cache", t("task.browser_cache.title"),
                         t("task.browser_cache.desc"))

    def _get_browser_cache_dirs(self):
        local_app_data = get_shell_folder(CSIDL_LOCAL_APPDATA)
        dirs = []
        # Chrome
        chrome_cache = os.path.join(local_app_data, "Google", "Chrome",
                                    "User Data", "Default", "Cache")
        chrome_code_cache = os.path.join(local_app_data, "Google", "Chrome",
                                         "User Data", "Default", "Code Cache")
        dirs.extend([chrome_cache, chrome_code_cache])
        # Edge
        edge_cache = os.path.join(local_app_data, "Microsoft", "Edge",
                                  "User Data", "Default", "Cache")
        edge_code_cache = os.path.join(local_app_data, "Microsoft", "Edge",
                                       "User Data", "Default", "Code Cache")
        dirs.extend([edge_cache, edge_code_cache])
        # 新版缓存存储
        chrome_cache_storage = os.path.join(local_app_data, "Google", "Chrome",
                                            "User Data", "Default", "CacheStorage")
        edge_cache_storage = os.path.join(local_app_data, "Microsoft", "Edge",
                                          "User Data", "Default", "CacheStorage")
        dirs.extend([chrome_cache_storage, edge_cache_storage])
        return [d for d in dirs if os.path.exists(d)]

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        self.scanned_size = 0
        self.scanned_files = 0
        dirs = self._get_browser_cache_dirs()
        if not dirs:
            self.status = t("scan.status_ready")
            if log_callback:
                log_callback(t("task.browser_cache.not_found"))
            return 0
        for d in dirs:
            if log_callback:
                log_callback(t("task.browser_cache.scanning", path=d))
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
                    log_callback(t("task.browser_cache.skip", path=d, error=e))
        self.status = t("scan.status_ready")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
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
                    log_callback(t("task.browser_cache.skip_dir", path=d, error=e))
        self.status = t("scan.status_completed")
        if log_callback:
            log_callback(t("task.browser_cache.done", count=count))


# ============================================================
# 4. 下载文件夹旧文件
# ============================================================

class OldDownloadsTask(CleanTask):
    def __init__(self):
        super().__init__("old_downloads", t("task.old_downloads.title"),
                         t("task.old_downloads.desc"))
        self.days = 30  # 默认 30 天

    def _get_downloads_path(self):
        profile = os.environ.get("USERPROFILE", "")
        # 同时兼容中文（下载）和英文（Downloads）系统
        for name in ("Downloads", "下载"):
            path = os.path.join(profile, name)
            if os.path.exists(path):
                return path
        return None

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        self.scanned_size = 0
        self.scanned_files = 0
        dl_path = self._get_downloads_path()
        if not dl_path:
            self.status = t("scan.status_ready")
            if log_callback:
                log_callback(t("task.old_downloads.not_found"))
            return 0
        if log_callback:
            log_callback(t("task.old_downloads.scanning",
                           path=dl_path, days=self.days))
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
                log_callback(t("task.old_downloads.scan_failed", error=e))
        self.status = t("scan.status_ready")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
        dl_path = self._get_downloads_path()
        if not dl_path:
            self.status = t("scan.status_completed")
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
        self.status = t("scan.status_completed")
        if log_callback:
            log_callback(t("task.old_downloads.done", count=count, days=self.days))


# ============================================================
# 5. 最近访问记录
# ============================================================

class RecentFilesTask(CleanTask):
    def __init__(self):
        super().__init__("recent_files", t("task.recent_files.title"),
                         t("task.recent_files.desc"))

    def _get_recent_path(self):
        return get_shell_folder(CSIDL_RECENT)

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        self.scanned_size = 0
        self.scanned_files = 0
        recent = self._get_recent_path()
        if not recent or not os.path.exists(recent):
            self.status = t("scan.status_ready")
            return 0
        if log_callback:
            log_callback(t("task.recent_files.scanning", path=recent))
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
                log_callback(t("task.recent_files.scan_failed", error=e))
        self.status = t("scan.status_ready")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
        recent = self._get_recent_path()
        if not recent or not os.path.exists(recent):
            self.status = t("scan.status_completed")
            return
        count = 0
        try:
            ctypes.windll.shell32.SHAddToRecentDocs(2, None)
            if log_callback:
                log_callback(t("task.recent_files.done_api"))
        except Exception:
            pass
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
                log_callback(t("task.recent_files.clean_error", error=e))
        self.status = t("scan.status_completed")
        if log_callback:
            log_callback(t("task.recent_files.done", count=count))


# ============================================================
# 6. 系统日志
# ============================================================

class SystemLogsTask(CleanTask):
    def __init__(self):
        super().__init__("system_logs", t("task.system_logs.title"),
                         t("task.system_logs.desc"))

    def _get_log_paths(self):
        paths = []
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or ""
        if not windir:
            return paths
        logs_dir = os.path.join(windir, "Logs")
        if os.path.exists(logs_dir):
            paths.append(logs_dir)
        cbs = os.path.join(windir, "Logs", "CBS")
        if os.path.exists(cbs):
            paths.append(cbs)
        panther = os.path.join(windir, "Panther")
        if os.path.exists(panther):
            paths.append(panther)
        soft_dist = os.path.join(windir, "SoftwareDistribution", "Download")
        if os.path.exists(soft_dist):
            paths.append(soft_dist)
        try:
            for f in os.scandir(windir):
                if f.is_file() and f.name.lower().endswith('.etl'):
                    paths.append(f.path)
        except (OSError, PermissionError):
            pass
        perf_logs = os.path.join(windir, "Performance", "Winstore", "Diag")
        if os.path.exists(perf_logs):
            paths.append(perf_logs)
        memory_dmp = os.path.join(windir, "memory.dmp")
        if os.path.exists(memory_dmp):
            paths.append(memory_dmp)
        minidump_dir = os.path.join(windir, "Minidump")
        if os.path.exists(minidump_dir):
            paths.append(minidump_dir)
        return paths

    def scan(self, log_callback=None):
        self.status = t("scan.status_scanning")
        self.scanned_size = 0
        self.scanned_files = 0
        paths = self._get_log_paths()
        for p in paths:
            if log_callback:
                log_callback(t("task.system_logs.scanning", path=p))
            try:
                if os.path.isfile(p):
                    sz = os.path.getsize(p)
                    self.scanned_size += sz
                    self.scanned_files += 1
                elif os.path.isdir(p):
                    sz = get_folder_size(p)
                    self.scanned_size += sz
                    try:
                        for _, _, files in os.walk(p):
                            self.scanned_files += len(files)
                    except (OSError, PermissionError):
                        pass
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(t("task.system_logs.skip", error=e))
        self.status = t("scan.status_ready")
        return self.scanned_size

    def clean(self, use_recycle_bin=False, log_callback=None):
        self.status = t("scan.status_cleaning")
        paths = self._get_log_paths()
        count = 0
        for p in paths:
            try:
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                        count += 1
                        if log_callback:
                            log_callback(t("task.system_logs.deleted", path=p))
                    except (OSError, PermissionError) as e:
                        if log_callback:
                            log_callback(t("task.system_logs.delete_failed",
                                           path=p, error=e))
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
                        log_callback(t("task.system_logs.cleaned", path=p))
            except (OSError, PermissionError) as e:
                if log_callback:
                    log_callback(t("task.system_logs.skip_entry", path=p, error=e))
        self.status = t("scan.status_completed")
        if log_callback:
            log_callback(t("task.system_logs.done", count=count))
