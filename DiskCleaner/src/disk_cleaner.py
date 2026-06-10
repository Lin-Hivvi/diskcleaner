# -*- coding: utf-8 -*-
"""
Windows 桌面垃圾清理工具 — 主入口
====================================
基于 tkinter 的 GUI 程序，可打包为独立 .exe
六大清理功能：临时文件、回收站、浏览器缓存、旧文件、最近记录、系统日志

模块结构:
  disk_cleaner.py   — 主入口（GUI 界面 + main）
  config.py         — 全局常量、权限检测
  utils.py          — 工具函数（格式化、文件操作）
  tray.py           — 系统托盘图标
  log_manager.py    — 日志管理器
  clean_tasks.py    — 清理任务类（6 大模块）
  app_cleaner.py    — 应用软件缓存清理（第三方软件）
  i18n.py           — 国际化支持
"""
import os
import sys
import json
import ctypes
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

from src.i18n import t, set_language, current_lang, LANGUAGES
from src.config import APP_NAME, APP_VERSION, CONFIG_FILE, IS_ADMIN
from src.config import get_shell_folder, CSIDL_LOCAL_APPDATA, CSIDL_RECENT
from src.config import ensure_admin_and_restart
from src.utils import format_size, get_folder_size, send_to_recycle_bin, permanently_delete
from src.tray import WindowsTrayIcon
from src.log_manager import LogManager
from src.clean_tasks import (
    TempFilesTask, RecycleBinTask, BrowserCacheTask,
    OldDownloadsTask, RecentFilesTask, SystemLogsTask,
)
from src.app_cleaner import AppSoftwareTask


# ============================================================
# 主 GUI 应用程序
# ============================================================

class DiskCleanerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(t("app.title", name=APP_NAME, version=APP_VERSION))
        self.root.geometry("820x720")
        self.root.minsize(720, 600)

        # 设置图标（如果有）
        try:
            icon_path = self._resource_path("resources/icon.ico")
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
            AppSoftwareTask(),
            RecentFilesTask(),
            SystemLogsTask(),
        ]

        # 状态变量
        self.is_running = False
        self.use_recycle_bin = tk.BooleanVar(value=True)
        self.minimize_to_tray = tk.BooleanVar(value=True)
        self.task_vars = {}

        # 字体
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

        # 初始化系统托盘
        self._tray_icon = None
        self._init_tray()

        # 启动日志
        self.logger.separator()
        mode_str = t("admin.mode_admin") if IS_ADMIN else t("admin.mode_user")
        self.log(t("admin.startup_log", name=APP_NAME, version=APP_VERSION, mode=mode_str))
        self._log_startup_info()
        self.logger.separator()

    def _resource_path(self, relative_path):
        """获取资源文件路径（兼容 PyInstaller 打包后）"""
        try:
            base_path = sys._MEIPASS
        except Exception:
            # 从 src/ 模块定位到项目根目录
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)

    # ---------- 系统托盘 ----------

    def _init_tray(self):
        """初始化系统托盘（失败时静默跳过）"""
        try:
            icon_path = self._resource_path("resources/icon.ico")
            if not os.path.exists(icon_path):
                icon_path = None

            self._tray_icon = WindowsTrayIcon(
                root=self.root,
                icon_path=icon_path,
                tooltip=t("app.title", name=APP_NAME, version=APP_VERSION),
                on_show=self._restore_from_tray,
                on_exit=self._exit_from_tray,
                on_language=self._toggle_language,
            )
            if self._tray_icon.icon_visible:
                self.log(t("tray.enabled"))
        except Exception:
            self._tray_icon = None

    def _restore_from_tray(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _show_tray_balloon(self, title, text):
        if self._tray_icon and self._tray_icon.icon_visible:
            try:
                self._tray_icon.show_balloon(title, text)
            except Exception:
                pass

    def _exit_from_tray(self):
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
            text=t("app.title_full", name=APP_NAME),
            font=("微软雅黑", 16, "bold"),
            fg="#2B579A"
        )
        title_label.pack(side=tk.LEFT)

        admin_label = tk.Label(
            title_frame,
            text=t("admin.mode") if IS_ADMIN else t("admin.mode_normal"),
            font=("微软雅黑", 9),
            fg="green" if IS_ADMIN else "#888"
        )
        admin_label.pack(side=tk.LEFT, padx=5, pady=(5, 0))

        ver_label = tk.Label(
            title_frame, text=f"v{APP_VERSION}",
            font=("微软雅黑", 8), fg="#999"
        )
        ver_label.pack(side=tk.RIGHT)

        self.lang_btn = tk.Button(
            title_frame,
            text="🌐 " + ("中文" if current_lang() == "en" else "English"),
            font=("微软雅黑", 8),
            bd=1, padx=6, pady=0,
            command=self._toggle_language,
            bg="#f0f0f0"
        )
        self.lang_btn.pack(side=tk.RIGHT, padx=(0, 6))

        if not IS_ADMIN:
            warn_frame = tk.Frame(main_frame, bg="#FFF3CD", bd=1, relief=tk.SOLID)
            warn_frame.pack(fill=tk.X, pady=(0, 8))
            warn_label = tk.Label(
                warn_frame, text=t("admin.warning_text"), bg="#FFF3CD",
                font=("微软雅黑", 9), fg="#856404", justify=tk.LEFT, padx=8, pady=4
            )
            warn_label.pack(fill=tk.X)

        # ============ 可滚动任务列表 ============
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        canvas = tk.Canvas(list_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

        self.task_labels = {}
        self.task_size_vars = {}
        self._app_software_ui = None

        for i, task in enumerate(self.tasks):
            if task.key == "app_software":
                self._build_app_software_card(scroll_frame, task)
                continue

            var = tk.BooleanVar(value=True)
            self.task_vars[task.key] = var

            card = tk.Frame(scroll_frame, bd=1, relief=tk.GROOVE,
                            padx=10, pady=6, bg="#f8f9fa")
            card.pack(fill=tk.X, pady=3)

            row1 = tk.Frame(card, bg="#f8f9fa")
            row1.pack(fill=tk.X)

            cb = tk.Checkbutton(row1, variable=var, bg="#f8f9fa", font=self.label_font)
            cb.pack(side=tk.LEFT)

            title_lbl = tk.Label(row1, text=task.title, font=self.title_font,
                                 bg="#f8f9fa", anchor="w")
            title_lbl.pack(side=tk.LEFT, padx=(0, 5))

            size_var = tk.StringVar(value=t("scan.status_unscanned"))
            size_lbl = tk.Label(row1, textvariable=size_var,
                                font=("微软雅黑", 9), fg="#2B579A",
                                bg="#f8f9fa", width=20, anchor="e")
            size_lbl.pack(side=tk.RIGHT, padx=(5, 5))
            self.task_size_vars[task.key] = size_var

            scan_btn = tk.Button(row1, text=t("scan.btn"),
                                 font=("微软雅黑", 9),
                                 command=lambda t=task: self._scan_single(t),
                                 bg="#E8F0FE", bd=1, padx=8, pady=1)
            scan_btn.pack(side=tk.RIGHT)

            if task.description:
                desc_lbl = tk.Label(card, text=task.description,
                                    font=("微软雅黑", 8), fg="#666",
                                    bg="#f8f9fa", anchor="w", padx=25)
                desc_lbl.pack(fill=tk.X)

            if task.key == "old_downloads":
                days_frame = tk.Frame(card, bg="#f8f9fa", padx=25)
                days_frame.pack(fill=tk.X, pady=(2, 0))
                tk.Label(days_frame, text=t("task.old_downloads.label_over"),
                         font=("微软雅黑", 9), bg="#f8f9fa").pack(side=tk.LEFT)
                self.days_var = tk.StringVar(value="30")
                days_entry = tk.Entry(days_frame, textvariable=self.days_var,
                                      width=5, font=("微软雅黑", 9), justify=tk.CENTER)
                days_entry.pack(side=tk.LEFT, padx=3)
                tk.Label(days_frame, text=t("task.old_downloads.label_days"),
                         font=("微软雅黑", 9), bg="#f8f9fa").pack(side=tk.LEFT)

            self.task_labels[task.key] = title_lbl

        # ============ 底部按钮区 ============
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(btn_frame, text=t("scan.select_all"),
                   command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=t("scan.deselect_all"),
                   command=self._deselect_all).pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(btn_frame, text=t("scan.scan_all"),
                   command=self._scan_all).pack(side=tk.LEFT, padx=2)
        self.recycle_cb = ttk.Checkbutton(btn_frame, text=t("clean.mode_recycle"),
                                          variable=self.use_recycle_bin)
        self.recycle_cb.pack(side=tk.LEFT, padx=2)
        self.tray_cb = ttk.Checkbutton(btn_frame, text=t("tray.minimize"),
                                       variable=self.minimize_to_tray)
        self.tray_cb.pack(side=tk.LEFT, padx=8)

        btn_frame_right = ttk.Frame(btn_frame)
        btn_frame_right.pack(side=tk.RIGHT)

        ttk.Button(btn_frame_right, text=t("scan.simulate"),
                   command=self._simulate_run).pack(side=tk.LEFT, padx=2)

        self.clean_btn = tk.Button(btn_frame_right, text=t("scan.start_clean"),
                                   font=("微软雅黑", 10, "bold"),
                                   bg="#DC3545", fg="white", bd=1,
                                   padx=12, pady=2, command=self._start_cleanup)
        self.clean_btn.pack(side=tk.LEFT, padx=2)

        # ============ 进度条 ============
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 4))

        self.progress_label = tk.Label(main_frame, text=t("progress.ready"),
                                       font=("微软雅黑", 9), fg="#666", anchor="w")
        self.progress_label.pack(fill=tk.X, pady=(0, 4))

        # ============ 日志文本框 ============
        log_frame = ttk.LabelFrame(main_frame, text=t("log.panel_title"), padding=3)
        log_frame.pack(fill=tk.BOTH, expand=True)

        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_text_frame, height=8, font=self.log_font,
                                wrap=tk.WORD, state=tk.DISABLED,
                                bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
        log_scroll = ttk.Scrollbar(log_text_frame, orient=tk.VERTICAL,
                                   command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(log_btn_frame, text=t("log.clear"),
                   command=self._clear_log).pack(side=tk.LEFT, padx=1)
        ttk.Button(log_btn_frame, text=t("log.export"),
                   command=self._export_log).pack(side=tk.LEFT, padx=1)
        ttk.Button(log_btn_frame, text=t("log.open_folder"),
                   command=self._open_log_folder).pack(side=tk.LEFT, padx=1)

    # ---------- 应用软件缓存卡片（带子项详情） ----------

    def _get_app_software_task(self):
        for t_ in self.tasks:
            if t_.key == "app_software":
                return t_
        return None

    def _build_app_software_card(self, parent, task):
        var = tk.BooleanVar(value=True)
        self.task_vars[task.key] = var

        card = tk.Frame(parent, bd=1, relief=tk.GROOVE, padx=10, pady=6, bg="#f8f9fa")
        card.pack(fill=tk.X, pady=3)

        row1 = tk.Frame(card, bg="#f8f9fa")
        row1.pack(fill=tk.X)

        cb = tk.Checkbutton(row1, variable=var, bg="#f8f9fa", font=self.label_font)
        cb.pack(side=tk.LEFT)

        title_lbl = tk.Label(row1, text=task.title, font=self.title_font,
                             bg="#f8f9fa", anchor="w")
        title_lbl.pack(side=tk.LEFT, padx=(0, 5))

        size_var = tk.StringVar(value=t("scan.status_unscanned"))
        size_lbl = tk.Label(row1, textvariable=size_var,
                            font=("微软雅黑", 9), fg="#2B579A",
                            bg="#f8f9fa", width=20, anchor="e")
        size_lbl.pack(side=tk.RIGHT, padx=(5, 5))
        self.task_size_vars[task.key] = size_var

        scan_btn = tk.Button(row1, text=t("scan.btn"), font=("微软雅黑", 9),
                             command=lambda: self._scan_single(task),
                             bg="#E8F0FE", bd=1, padx=8, pady=1)
        scan_btn.pack(side=tk.RIGHT)

        if task.description:
            desc_lbl = tk.Label(card, text=task.description,
                                font=("微软雅黑", 8), fg="#666",
                                bg="#f8f9fa", anchor="w", padx=25)
            desc_lbl.pack(fill=tk.X)

        if not task.categories:
            empty_lbl = tk.Label(card, text=t("app_software.none_found"),
                                 font=("微软雅黑", 9), fg="#888",
                                 bg="#f8f9fa", padx=25)
            empty_lbl.pack(fill=tk.X, pady=4)
            return

        sub_frame = tk.Frame(card, bg="#eef0f4", bd=0, padx=6, pady=4)
        sub_frame.pack(fill=tk.X, padx=18, pady=4)

        ui = {
            "task": task,
            "cat_vars": {},
            "item_vars": {},
            "cat_size_labels": {},
            "item_size_labels": {},
            "cat_expand_btns": {},
            "cat_item_container": {},
        }
        self._app_software_ui = ui

        for cat in task.categories:
            self._build_one_app_category(sub_frame, cat, ui)

    def _build_one_app_category(self, parent, cat, ui):
        cat_var = tk.BooleanVar(value=cat.enabled)
        ui["cat_vars"][cat.key] = cat_var

        hdr = tk.Frame(parent, bg="#e2e6ed", bd=0, padx=6, pady=2)
        hdr.pack(fill=tk.X, pady=1)

        expand_symbol = "▼" if cat._expanded else "▶"
        exp_btn = tk.Button(hdr, text=expand_symbol,
                            font=("Consolas", 8), bd=0, padx=3, pady=0,
                            bg="#e2e6ed", cursor="hand2",
                            command=lambda c=cat: self._toggle_app_category(c))
        exp_btn.pack(side=tk.LEFT)
        ui["cat_expand_btns"][cat.key] = exp_btn

        cat_cb = tk.Checkbutton(hdr, variable=cat_var, bg="#e2e6ed",
                                font=("微软雅黑", 9),
                                command=lambda c=cat: self._on_cat_check(c))
        cat_cb.pack(side=tk.LEFT)

        cat_lbl = tk.Label(hdr, text=f"{cat.icon} {cat.name}",
                           font=("微软雅黑", 9, "bold"), bg="#e2e6ed", anchor="w")
        cat_lbl.pack(side=tk.LEFT, padx=(2, 5))

        cat_size_var = tk.StringVar(value="")
        cat_size_lbl = tk.Label(hdr, textvariable=cat_size_var,
                                font=("微软雅黑", 8), fg="#555",
                                bg="#e2e6ed", anchor="e", width=16)
        cat_size_lbl.pack(side=tk.RIGHT, padx=(5, 2))
        ui["cat_size_labels"][cat.key] = cat_size_lbl

        cat_scan_btn = tk.Button(hdr, text=t("scan.btn"),
                                 font=("微软雅黑", 8), bd=1, padx=4,
                                 command=lambda c=cat: self._scan_app_category(c),
                                 bg="#E8F0FE")
        cat_scan_btn.pack(side=tk.RIGHT, padx=2)

        items_frame = tk.Frame(parent, bg="#f5f6fa", bd=0)
        ui["cat_item_container"][cat.key] = items_frame

        for item in cat.items:
            self._build_one_cache_item(items_frame, item, cat, ui)

        if cat._expanded:
            items_frame.pack(fill=tk.X)

    def _build_one_cache_item(self, parent, item, cat, ui):
        item_var = tk.BooleanVar(value=item.enabled)
        ui["item_vars"][(cat.key, item.key)] = item_var

        row = tk.Frame(parent, bg="#f5f6fa", padx=22, pady=1)
        row.pack(fill=tk.X)

        cb = tk.Checkbutton(row, variable=item_var, bg="#f5f6fa",
                            font=("微软雅黑", 9),
                            command=lambda: self._on_item_check(cat))
        cb.pack(side=tk.LEFT)

        desc = f" — {item.description}" if item.description else ""
        tk.Label(row, text=f"📄 {item.name}{desc}",
                 font=("微软雅黑", 9), fg="#444", bg="#f5f6fa",
                 anchor="w").pack(side=tk.LEFT, padx=2)

        sz_var = tk.StringVar(value="")
        sz_lbl = tk.Label(row, textvariable=sz_var,
                          font=("微软雅黑", 8), fg="#666",
                          bg="#f5f6fa", anchor="e", width=16)
        sz_lbl.pack(side=tk.RIGHT, padx=2)
        ui["item_size_labels"][(cat.key, item.key)] = sz_lbl

    def _toggle_app_category(self, cat):
        cat._expanded = not cat._expanded
        ui = self._app_software_ui
        if not ui:
            return
        container = ui["cat_item_container"].get(cat.key)
        btn = ui["cat_expand_btns"].get(cat.key)
        if container:
            if cat._expanded:
                container.pack(fill=tk.X)
                if btn:
                    btn.config(text="▼")
            else:
                container.pack_forget()
                if btn:
                    btn.config(text="▶")

    def _on_cat_check(self, cat):
        ui = self._app_software_ui
        if not ui:
            return
        cat_enabled = ui["cat_vars"][cat.key].get()
        cat.enabled = cat_enabled
        for item in cat.items:
            item.enabled = cat_enabled
            k = (cat.key, item.key)
            if k in ui["item_vars"]:
                ui["item_vars"][k].set(cat_enabled)

    def _on_item_check(self, cat):
        ui = self._app_software_ui
        if not ui:
            return
        for item in cat.items:
            k = (cat.key, item.key)
            if k in ui["item_vars"]:
                item.enabled = ui["item_vars"][k].get()

    def _scan_app_category(self, cat):
        task = self._get_app_software_task()
        if not task:
            return
        if self.is_running:
            messagebox.showinfo(t("msg.running_title"), t("msg.running_text"))
            return
        self.log(f"  📱 开始扫描: {cat.icon} {cat.name}")
        self.log(f"    检测路径: {cat.key}")
        self.is_running = True

        def _do():
            try:
                task.scan_category(cat.key,
                                   log_callback=lambda msg: self.log(msg))
                self.root.after(0, self._refresh_app_software_sizes)
            except Exception as e:
                self.log(f"  ❌ 扫描失败: {e}")
            finally:
                self.is_running = False
                self.root.after(0, self._sync_app_software_main_size)

        threading.Thread(target=_do, daemon=True).start()

    def _refresh_app_software_sizes(self):
        ui = self._app_software_ui
        if not ui:
            return
        task = ui["task"]
        for cat in task.categories:
            if cat.key in ui["cat_size_labels"]:
                if cat.scanned_size > 0:
                    ui["cat_size_labels"][cat.key].config(
                        text=format_size(cat.scanned_size))
                else:
                    ui["cat_size_labels"][cat.key].config(text="")
            for item in cat.items:
                k = (cat.key, item.key)
                if k in ui["item_size_labels"]:
                    if item.scanned_size > 0:
                        ui["item_size_labels"][k].config(
                            text=format_size(item.scanned_size))
                    else:
                        ui["item_size_labels"][k].config(text="")

    def _sync_app_software_main_size(self):
        task = self._get_app_software_task()
        if not task:
            return
        sv = self.task_size_vars.get("app_software")
        if not sv:
            return
        total = task.get_total_size()
        count = task.get_enabled_item_count()
        if total > 0:
            sv.set(f"{format_size(total)} ({count} 项)")
        else:
            sv.set("0 B")

    # ---------- 日志 ----------

    def log(self, message):
        self.logger.info(message)

    def _gui_log_append(self, formatted_message):
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
            filetypes=[(t("filetype.text"), "*.txt"), (t("filetype.all"), "*.*")],
            title=t("log.export_title")
        )
        if file_path:
            try:
                content = self.log_text.get(1.0, tk.END)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log(t("log.export_done", path=file_path))
            except Exception as e:
                messagebox.showerror(t("log.export_failed"),
                                     t("log.export_error", error=e))

    def _open_log_folder(self):
        log_dir = self.logger.get_log_dir()
        if not os.path.isdir(log_dir):
            messagebox.showinfo(t("msg.running_title"), t("log.folder_not_created"))
            return
        try:
            os.startfile(log_dir)
        except Exception:
            try:
                subprocess.Popen(["explorer", log_dir])
            except Exception as e:
                messagebox.showerror(t("log.folder_error"),
                                     t("log.folder_error_text", error=e))

    def _log_startup_info(self):
        info = self.logger.get_log_summary()
        self.log(t("log.startup_dir", path=info['dir']))
        self.log(t("log.startup_files", count=info['file_count'],
                   size=format_size(info['total_size'])))
        if info['file_count'] > 0:
            self.log(t("log.startup_today", path=info['today_log']))

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
                t("scan.size_format", size=format_size(task.scanned_size),
                  count=task.scanned_files)
            )
        else:
            self.task_size_vars[task.key].set(t("scan.zero_bytes"))

    def _scan_single(self, task):
        if self.is_running:
            messagebox.showinfo(t("msg.running_title"), t("msg.running_text"))
            return
        if task.key == "old_downloads":
            try:
                days = int(self.days_var.get().strip())
                if days < 1:
                    raise ValueError
                task.days = days
            except ValueError:
                messagebox.showwarning(t("msg.invalid_days_title"),
                                       t("msg.invalid_days_text"))
                return

        self.log(t("scan.single_start", title=task.title))
        self.is_running = True
        self.root.update_idletasks()

        def _do_scan():
            try:
                task.scan(log_callback=lambda msg: self.log(msg))
                self.root.after(0, lambda: self._update_task_size(task))
                if task.key == "app_software":
                    self.root.after(0, self._refresh_app_software_sizes)
                    self.root.after(0, self._sync_app_software_main_size)
                self.log(t("scan.single_done", summary=task.get_summary()))
            except Exception as e:
                self.log(t("scan.single_failed", error=e))
            finally:
                self.is_running = False

        threading.Thread(target=_do_scan, daemon=True).start()

    def _scan_all(self):
        if self.is_running:
            messagebox.showinfo(t("msg.running_title"), t("msg.running_text"))
            return
        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t_ in self.tasks:
                if t_.key == "old_downloads":
                    t_.days = days
        except ValueError:
            messagebox.showwarning(t("msg.invalid_days_title"),
                                   t("msg.invalid_days_text"))
            return

        self.log(f"{'='*50}")
        self.log(t("scan.all_start"))
        self.is_running = True
        self.progress_label.config(text=t("progress.scanning"))
        self.progress_var.set(0)
        self.root.update_idletasks()

        total_tasks = len([t_ for t_ in self.tasks if t_.enabled])

        def _do_scan_all():
            completed = 0
            for task in self.tasks:
                if not self.task_vars[task.key].get():
                    continue
                self.root.after(0, lambda t_=task: self.progress_label.config(
                    text=t("scan.all_progress", title=t_.title)))
                try:
                    task.scan(log_callback=lambda msg: self.log(msg))
                    self.root.after(0, lambda t_=task: self._update_task_size(t_))
                    self.log(t("scan.single_done", summary=task.get_summary()))
                except Exception as e:
                    self.log(t("scan.all_failed", title=task.title, error=e))
                completed += 1
                pct = int(completed / total_tasks * 100) if total_tasks else 100
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, lambda: self.progress_label.config(text=t("scan.all_done")))
            self.root.after(0, lambda: self.progress_var.set(100))
            self.log(t("scan.all_complete"))
            self.log(f"{'='*50}")
            self.is_running = False
            self.root.after(0, self._refresh_app_software_sizes)
            self.root.after(0, self._sync_app_software_main_size)

        threading.Thread(target=_do_scan_all, daemon=True).start()

    def _start_cleanup(self):
        if self.is_running:
            messagebox.showinfo(t("msg.running_title"), t("msg.running_text"))
            return

        selected = [t_ for t_ in self.tasks if self.task_vars[t_.key].get()]
        if not selected:
            messagebox.showwarning(t("msg.no_selection_title"),
                                   t("msg.no_selection_text"))
            return

        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t_ in self.tasks:
                if t_.key == "old_downloads":
                    t_.days = days
        except ValueError:
            messagebox.showwarning(t("msg.invalid_days_title"),
                                   t("msg.invalid_days_text"))
            return

        need_scan = [t_ for t_ in selected
                     if t_.scanned_size == 0 and t_.status != t("scan.status_ready")]
        if need_scan:
            result = messagebox.askyesno(
                t("msg.scan_first_title"),
                t("msg.scan_first_text",
                  tasks=", ".join(t_.title for t_ in need_scan))
            )
            if result:
                self.log(t("clean.restart_as_admin"))
                return

        total_size = sum(t_.scanned_size for t_ in selected)
        use_recycle = self.use_recycle_bin.get()

        mode_str = (t("clean.mode_recycle_short") if use_recycle
                    else t("clean.mode_permanent"))
        items_str = chr(10).join(
            t("clean.confirm_item", title=t_.title,
              size=format_size(t_.scanned_size))
            for t_ in selected
        )
        confirm = messagebox.askyesno(
            t("clean.confirm_title"),
            t("clean.confirm_text", count=len(selected),
              size=format_size(total_size), mode=mode_str, items=items_str),
            icon=messagebox.WARNING
        )
        if not confirm:
            self.log(t("clean.cancelled"))
            return

        from clean_tasks import SystemLogsTask
        if not IS_ADMIN:
            for t_ in selected:
                if isinstance(t_, SystemLogsTask):
                    ret = messagebox.askyesno(
                        t("admin.restart_confirm_title"),
                        t("admin.restart_confirm_text")
                    )
                    if ret:
                        self._restart_as_admin()
                        return
                    break

        self.log(f"{'='*50}")
        self.log(t("clean.start", mode=mode_str))
        self.is_running = True
        self.clean_btn.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.progress_label.config(text=t("progress.cleaning"))
        self.root.update_idletasks()

        def _do_clean():
            completed = 0
            total = len(selected)
            for task in selected:
                self.root.after(0, lambda t_=task: self.progress_label.config(
                    text=t("clean.progress", title=t_.title)))
                try:
                    task.clean(use_recycle_bin=use_recycle,
                               log_callback=lambda msg: self.log(msg))
                except Exception as e:
                    self.log(t("clean.failed", title=task.title, error=e))
                completed += 1
                pct = int(completed / total * 100) if total else 100
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, self._on_cleanup_done)

        threading.Thread(target=_do_clean, daemon=True).start()

    def _on_cleanup_done(self):
        self.progress_label.config(text=t("progress.done"))
        self.progress_var.set(100)
        self.clean_btn.config(state=tk.NORMAL)
        self.log(t("clean.done"))
        self.log(f"{'='*50}")
        self.is_running = False

        self._show_tray_balloon(
            t("clean.complete_balloon_title"),
            t("clean.complete_balloon_text")
        )

        self.log(t("clean.rescanning"))
        threading.Thread(target=self._rescan_after_cleanup, daemon=True).start()

    def _rescan_after_cleanup(self):
        for task in self.tasks:
            if self.task_vars[task.key].get():
                try:
                    task.scan()
                    self.root.after(0, lambda t_=task: self._update_task_size(t_))
                except Exception:
                    pass
        self.root.after(0, self._refresh_app_software_sizes)
        self.root.after(0, self._sync_app_software_main_size)
        self.root.after(0, lambda: self.log(t("clean.status_updated")))

    def _simulate_run(self):
        if self.is_running:
            messagebox.showinfo(t("msg.running_title"), t("msg.running_text"))
            return

        selected = [t_ for t_ in self.tasks if self.task_vars[t_.key].get()]
        if not selected:
            messagebox.showwarning(t("msg.no_selection_title"),
                                   t("msg.no_selection_text"))
            return

        try:
            days = int(self.days_var.get().strip())
            if days < 1:
                raise ValueError
            for t_ in self.tasks:
                if t_.key == "old_downloads":
                    t_.days = days
        except ValueError:
            messagebox.showwarning(t("msg.invalid_days_title"),
                                   t("msg.invalid_days_text"))
            return

        self.log(f"{'='*50}")
        self.log(t("simulate.title"))
        self.is_running = True
        self.progress_var.set(0)
        self.progress_label.config(text=t("simulate.progress", title="..."))
        self.root.update_idletasks()

        total_tasks = len(selected)

        def _do_simulate():
            completed = 0
            grand_total = 0
            for task in selected:
                self.root.after(0, lambda t_=task: self.progress_label.config(
                    text=t("simulate.progress", title=t_.title)))
                try:
                    size = task.scan(log_callback=lambda msg: self.log(msg))
                    grand_total += size
                    self.root.after(0, lambda t_=task: self._update_task_size(t_))
                    self.log(t("simulate.item", title=task.title, size=format_size(size)))
                except Exception as e:
                    self.log(t("simulate.item_error", title=task.title, error=e))
                completed += 1
                pct = int(completed / total_tasks * 100) if total_tasks else 0
                self.root.after(0, lambda v=pct: self.progress_var.set(v))
            self.root.after(0, lambda: self.progress_var.set(100))
            self.root.after(0, lambda: self.progress_label.config(text=t("simulate.done")))
            self.log(f"{'='*50}")
            self.log(t("simulate.summary", size=format_size(grand_total)))
            self.log(t("simulate.hint"))
            self.log(f"{'='*50}")
            self.is_running = False
            self.root.after(0, self._refresh_app_software_sizes)
            self.root.after(0, self._sync_app_software_main_size)

        threading.Thread(target=_do_simulate, daemon=True).start()

    def _on_close(self):
        self._save_config()
        if (self._tray_icon and self._tray_icon.icon_visible
                and self.minimize_to_tray.get()):
            try:
                self.root.withdraw()
                self._tray_icon.show_balloon(
                    t("tray.minimized_title", name=APP_NAME),
                    t("tray.minimized_text"))
                return
            except Exception:
                pass
        self.logger.info(t("log.app_exit"))
        self.logger.close()
        if self._tray_icon:
            self._tray_icon.remove()
        self.root.destroy()

    def _restart_as_admin(self):
        self.log(t("admin.restarting"))
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
            self.log(t("admin.restart_failed", error=e))
            self.root.destroy()
        self.root.destroy()

    def _toggle_language(self):
        new_lang = "en" if current_lang() == "zh_CN" else "zh_CN"
        set_language(new_lang)
        self.lang_btn.config(
            text="🌐 " + ("中文" if new_lang == "en" else "English")
        )
        result = messagebox.askyesno(
            "切换语言 / Switch Language" if new_lang == "en" else "切换语言",
            "语言已切换。是否立即重启程序以应用新语言界面？\n\n"
            "Language switched. Restart now to apply?"
        )
        if result:
            self._save_config()
            self.logger.close()
            if self._tray_icon:
                self._tray_icon.remove()
            script = sys.argv[0]
            if getattr(sys, 'frozen', False):
                exe = sys.executable
            else:
                exe = sys.executable
                script = os.path.abspath(sys.argv[0])
            subprocess.Popen([exe, script, f"--lang={new_lang}"])
            self.root.destroy()

    # ---------- 配置保存/加载 ----------

    def _save_config(self):
        try:
            config = {
                "use_recycle_bin": self.use_recycle_bin.get(),
                "minimize_to_tray": self.minimize_to_tray.get(),
                "old_download_days": (self.days_var.get()
                                      if hasattr(self, 'days_var') else "30"),
                "language": current_lang(),
                "enabled_tasks": {
                    t_.key: self.task_vars[t_.key].get() for t_ in self.tasks
                }
            }
            app_task = self._get_app_software_task()
            if app_task:
                config["app_software_state"] = app_task.save_state()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_config(self):
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
            if "language" in config and config["language"] != current_lang():
                set_language(config["language"])
            if "enabled_tasks" in config:
                for key, enabled in config["enabled_tasks"].items():
                    if key in self.task_vars:
                        self.task_vars[key].set(enabled)
            app_state = config.get("app_software_state")
            if app_state:
                app_task = self._get_app_software_task()
                if app_task:
                    app_task.load_state(app_state)
        except Exception:
            pass


# ============================================================
# 程序入口
# ============================================================

def main():
    # 自动申请管理员权限（用户点击「否」则降级以普通权限运行）
    ensure_admin_and_restart()

    app = DiskCleanerApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()
