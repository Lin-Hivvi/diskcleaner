# -*- coding: utf-8 -*-
"""
日志管理器模块
===============
- 自动按日期轮转：每天一个文件，保留最多 30 天
- 多级别：DEBUG / INFO / WARNING / ERROR
- 线程安全（threading.Lock）
- 与 GUI 日志文本框双向同步
"""
import os
import time
import threading
from datetime import datetime


class LogManager:
    """
    文件日志管理器（单例模式）

    特性:
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
        self._gui_callback = None
        self._ensure_log_dir()
        self._rotate_old_logs()

    # ---------- 初始化 ----------

    def _resolve_log_dir(self):
        """确定日志目录"""
        base = os.environ.get("TEMP", os.path.expanduser("~"))
        return os.path.join(base, "DiskCleaner", "logs")

    def _ensure_log_dir(self):
        """确保日志目录存在"""
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except Exception:
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
            pass

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
                self._file_handle = open(fpath, "a", encoding="utf-8", buffering=1)
            except Exception:
                return None
        return self._file_handle

    # ---------- 核心日志方法 ----------

    def _write(self, level, message):
        """写入日志（线程安全）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"

        with self._file_lock:
            try:
                fh = self._get_file_handle()
                if fh:
                    fh.write(log_line + "\n")
            except Exception:
                pass

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
