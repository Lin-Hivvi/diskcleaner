# 🧹 Windows 智能垃圾清理工具 — 设计文档

> **版本**: 0.1
> **目标平台**: Windows 10/11 x64
> **技术栈**: Python 3.8+ / tkinter / ctypes / PyInstaller
> **许可证**: MIT

---

## 目录

1. [设计思路](#1-设计思路)
2. [项目架构](#2-项目架构)
3. [模块详解](#3-模块详解)
4. [使用说明](#4-使用说明)
5. [打包部署](#5-打包部署)
6. [常见问题](#6-常见问题)

---

## 1. 设计思路

### 1.1 为什么做这个工具？

Windows 系统在使用过程中会积累大量垃圾文件：临时文件、浏览器缓存、系统日志、回收站残留等。这些文件占用磁盘空间，影响系统性能。市面上的清理工具要么收费、要么捆绑软件、要么需要联网。本工具的使命是：

> **一个绿色、免费、开源、单文件、无需安装的 Windows 垃圾清理工具。**

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| 🥇 **安全第一** | 默认启用「移动到回收站」模式，误删可恢复；删除前弹窗确认总量 |
| 🚀 **零依赖** | 不依赖 .NET Framework 或任何第三方 Python 包，ctypes 直接调用 Win32 API |
| 📦 **单文件分发** | PyInstaller 打包为单个 .exe，双击即用，无需 Python 环境 |
| 🧩 **模块化** | 每个清理功能独立成类，可单独扫描/清理，便于扩展 |
| 🖥 **桌面原生** | 使用 Windows 原生 GUI 框架 tkinter，轻量且兼容性好 |
| 🔒 **权限感知** | 自动检测管理员权限，按需提权 |


### 1.3 功能取舍

**实现的功能：**
- 系统临时文件、回收站、浏览器缓存、旧下载文件、最近记录、系统日志
- 扫描/清理分离，模拟运行预览
- 进度条 + 实时日志
- 系统托盘 + 气泡通知
- 自动提权

**刻意不做的功能（保持工具轻量）：**
- ❌ 注册表清理（风险高，易导致系统不稳定）
- ❌ 重复文件查找（计算量大，不适合本工具定位）
- ❌ 大文件分析（需要文件系统深度扫描，与轻量理念冲突）
- ❌ 开机自启动（入侵性强，留给用户自己决定）
- ❌ 联网/云功能（绿色单文件，不上传任何数据）

---

## 2. 项目架构

### 2.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        disk_cleaner.py                           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    GUI 层 (tkinter)                    │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │       │
│  │  │ 任务卡片 │ │ 按钮栏   │ │ 进度条   │ │ 日志框  │ │       │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │       │
│  └──────────────────────┬───────────────────────────────┘       │
│                         │                                       │
│  ┌──────────────────────▼───────────────────────────────┐       │
│  │              控制层 (DiskCleanerApp)                   │       │
│  │  线程管理 · 事件调度 · 配置持久化 · 托盘管理          │       │
│  └───────┬──────────┬──────────┬────────────────────────┘       │
│          │          │          │                                │
│  ┌───────▼──┐ ┌─────▼────┐ ┌─▼──────────┐                      │
│  │ 清理任务  │ │ Windows  │ │ 配置持久化  │                      │
│  │  引擎     │ │ 系统托盘  │ │ (JSON文件)  │                      │
│  └───────┬──┘ └──────────┘ └────────────┘                      │
│          │                                                      │
│  ┌───────▼──────────────────────────────────────┐               │
│  │            工具函数层                           │               │
│  │  format_size · get_folder_size ·              │               │
│  │  send_to_recycle_bin · permanently_delete    │               │
│  └───────┬──────────────────────────────────────┘               │
│          │                                                      │
│  ┌───────▼──────────────────────────────────────┐               │
│  │            Win32 API 层 (ctypes)              │               │
│  │  Shell32 · Kernel32 · User32                 │               │
│  │  SHFileOperation · Shell_NotifyIcon · ...    │               │
│  └──────────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
DiskCleaner/
├── disk_cleaner.py      # 主程序（1760 行，含全部代码）
├── build.bat            # 一键打包脚本
├── generate_icon.py     # 图标生成器（纯 Python）
├── version_info.txt     # exe 版本元数据
├── icon.ico             # 程序图标
├── .gitignore           # Git 忽略规则
├── README.md            # 快速入门说明
├── ARCHITECTURE.md      # 本文件 — 设计文档
└── dist/
    └── DiskCleaner.exe  # 构建产物
```

### 2.3 类关系图

```
CleanTask (抽象基类)
├── TempFilesTask      # 系统临时文件
├── RecycleBinTask      # 回收站
├── BrowserCacheTask    # 浏览器缓存
├── OldDownloadsTask    # 下载文件夹旧文件
├── RecentFilesTask     # 最近访问记录
└── SystemLogsTask      # 系统日志

WindowsTrayIcon         # 系统托盘（纯 ctypes 实现）

DiskCleanerApp          # 主应用程序（控制层）
```

---

## 3. 模块详解

### 3.1 清理任务引擎 (`CleanTask` 基类)

每个清理功能都继承自 `CleanTask`，实现统一的接口：

```python
class CleanTask:
    def scan(self, log_callback=None) -> int:
        """扫描并返回垃圾字节数"""
    def clean(self, use_recycle_bin=False, log_callback=None):
        """执行清理"""
```

**设计要点：**
- `scan()` 和 `clean()` 分离，让用户先预览再决定
- `log_callback` 注入模式，不直接依赖 GUI，便于测试
- 每个任务有自己的 `key`、`title`、`description`，UI 通过反射渲染

**各任务实现细节：**

| 任务 | 扫描方式 | 清理方式 | 特殊处理 |
|------|---------|---------|---------|
| 临时文件 | `os.scandir` + `get_folder_size` 递归 | `os.remove` / `shutil.rmtree` | 多路径合并（%TEMP%、%TMP%、%WinDir%\Temp） |
| 回收站 | `SHQueryRecycleBinW` API | `SHEmptyRecycleBinW` API | 直接调用原生 API，比遍历文件快百倍 |
| 浏览器缓存 | `os.walk` 遍历 Cache 目录 | 逐文件删除 | 兼容 Chrome 和 Edge 的新旧缓存路径 |
| 旧下载文件 | `os.scandir` + mtime 过滤 | 按天过滤删除 | 用户自定义天数 |
| 最近记录 | `os.scandir` 统计 .lnk | `SHAddToRecentDocs` API + 文件删除 | API 和物理删除双重清理 |
| 系统日志 | `os.walk` 遍历多路径 | `os.remove` | 多路径扫描，遇权限不足优雅跳过 |

### 3.2 Windows 系统托盘 (`WindowsTrayIcon`)

**纯 ctypes 实现，零外部依赖。**

实现原理：
1. 使用 `RegisterClassExW` 注册一个隐藏窗口类
2. `CreateWindowExW` 创建不可见窗口（用于接收消息）
3. `Shell_NotifyIconW(NIM_ADD)` 添加托盘图标
4. 通过 `PeekMessageW` + `DispatchMessageW` 在 tkinter 事件循环中泵消息
5. 消息回调中解析鼠标事件（左键点击显示窗口，右键弹出菜单）
6. `Shell_NotifyIconW(NIM_DELETE)` 退出时移除图标

**关键设计决策：**
- ❌ **不使用 `pystray`** — 它是外部依赖，增加打包体积；且与 `--onefile` 模式兼容性不好
- ✅ **融入 tkinter 事件循环** — 通过 `root.after(100, _pump)` 周期性泵消息，无需独立线程
- ✅ **WNDPROC 64 位兼容** — 显式指定 `argtypes` 和 `restype` 避免溢出

### 3.3 权限管理 (`ensure_admin_and_restart`)

```python
if not ensure_admin_and_restart():
    pass  # 用户拒绝 UAC，以普通权限继续
```

**流程：**
1. `IsUserAnAdmin()` 检测当前是否为管理员
2. 若不是 → `ShellExecuteW( runas )` 请求 UAC 提权重启
3. 用户点「是」→ 原进程 `sys.exit(0)`，新管理员进程启动
4. 用户点「否」→ 原进程以普通权限继续运行

**为什么放在 `main()` 而不是 `__init__`？**
- 避免 tkinter 初始化后再重启导致资源泄露
- 确保 GUI 还没出现时就能完成提权

### 3.4 配置持久化

配置保存在 `~/.disk_cleaner_config.json`，包含：
- `use_recycle_bin` — 是否启用回收站模式
- `minimize_to_tray` — 是否最小化到托盘
- `old_download_days` — 旧文件天数
- `enabled_tasks` — 每个任务的选中状态

保存时机：窗口关闭 / 从托盘退出时。
加载时机：程序启动时。

### 3.5 线程模型

```
主线程 (tkinter)
  ├── UI 渲染 & 事件响应
  ├── 消息泵 (PeekMessage for tray)
  └── 日志更新

工作线程 (daemon=True)
  ├── scan() / clean() 执行
  └── 通过 root.after(0, callback) 回到主线程更新 UI
```

**为什么用 `daemon=True`？**
- 主窗口关闭时自动退出，不会残留僵尸线程
- 用 `self.is_running` 互斥锁防止操作冲突

---

## 4. 使用说明

### 4.1 快速开始

```
双击 dist/DiskCleaner.exe
```

程序启动后会自动请求管理员权限（UAC 弹窗），点击「是」获得完整功能。

### 4.2 界面导航

```
┌──────────────────────────────────────────────────────────────┐
│  🧹 Windows 智能垃圾清理 v2.0          [管理员模式]          │  ← 标题栏
├──────────────────────────────────────────────────────────────┤
│  ⚠ 当前未以管理员身份运行 ...                               │  ← 警告条（仅普通权限时显示）
├──────────────────────────────────────────────────────────────┤
│  ☑ 📁 系统临时文件           🔍 扫描         1.23 GB       │  ← 任务卡片（可滚动）
│  ☑ ♻ 回收站                 🔍 扫描          128 MB        │
│  ☑ 🌐 浏览器缓存             🔍 扫描          457 MB        │
│  ☑ 📥 下载文件夹旧文件       🔍 扫描           89 MB        │
│      超过 [ 30 ] 天的文件                                    │  ← 天数输入框
│  ☑ 📋 最近访问记录           🔍 扫描              0 B       │
│  ☑ 📜 系统日志文件           🔍 扫描          2.34 GB       │
├──────────────────────────────────────────────────────────────┤
│  [☑全选] [☐全不选] | [🔍扫描全部]                          │
│  [☑移动到回收站(安全)]  [☑最小化到托盘]                     │  ← 底部工具栏
│                        [模拟运行] [ 🧹 开始清理 ]           │
├──────────────────────────────────────────────────────────────┤
│  ████████████████████████ 80%                                │  ← 进度条
│  正在清理: 系统临时文件                                      │  ← 状态文字
├──────────────────────────────────────────────────────────────┤
│ 📋 运行日志                                                  │  ← 日志输出（可滚动/导出）
│ [15:30:22] 🔍 开始扫描所有项目 ...                            │
│ [15:30:25] ✅ 扫描完成！共可释放 4.21 GB                       │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 操作流程

**标准流程：**
1. 勾选要清理的项目
2. 点击「🔍 扫描全部」查看可释放空间
3. 可点击「模拟运行」预览效果（不删除）
4. 确认后点击「🧹 开始清理」

**安全模式：**
- 默认勾选「移动到回收站（安全）」— 所有操作可逆
- 取消勾选 = 永久删除（不可恢复），建议确认后再操作

**系统托盘：**
- 关闭窗口 → 最小化到托盘
- 双击托盘图标 → 恢复窗口
- 右键托盘图标 → 显示窗口 / 退出程序
- 清理完成后自动弹出气泡通知

### 4.4 各平台兼容性

| 平台 | 支持情况 | 说明 |
|------|---------|------|
| Windows 11 | ✅ 完全支持 | 已验证 |
| Windows 10 | ✅ 完全支持 | 主要目标平台 |
| Windows 8/8.1 | ✅ 基本支持 | 未完整测试 |
| Windows 7 | ⚠ 部分支持 | 需要安装 KB2533623 更新 |
| 32 位系统 | ⚠ 需自行打包 | x86 版本 PyInstaller |

---

## 5. 打包部署

### 5.1 环境要求

- Windows 10/11 x64
- Python 3.8+（[官网下载](https://www.python.org/downloads/)）
- 安装 PyInstaller：`pip install pyinstaller`

### 5.2 打包命令

```batch
REM 方法一：双击 build.bat（推荐）
build.bat

REM 方法二：手动执行
pyinstaller --onefile --noconsole ^
    --name "DiskCleaner" ^
    --add-data "icon.ico;." ^
    --version-file "version_info.txt" ^
    --hidden-import queue ^
    --clean --noconfirm ^
    disk_cleaner.py
```

### 5.3 PyInstaller 参数详解

| 参数 | 说明 |
|------|------|
| `--onefile` | 打包为单个 exe 文件 |
| `--noconsole` | 隐藏控制台窗口（纯 GUI 程序） |
| `--add-data "icon.ico;."` | 将图标文件打包进 exe，运行时解压到当前目录 |
| `--version-file` | 给 exe 添加版本信息（右键→属性可见） |
| `--hidden-import` | 显式声明 PyInstaller 可能遗漏的模块 |
| `--clean` | 每次构建前清理缓存 |
| `--noconfirm` | 覆盖输出目录不询问 |

### 5.4 输出产物

```
dist/DiskCleaner.exe    ~13 MB  最终可执行文件
```

该 exe 可在任何 **Windows 10/11 x64** 电脑上直接运行，无需安装 Python 或任何运行时。

### 5.5 版本信息说明

`version_info.txt` 文件定义了 exe 的文件版本、产品名称、描述等元数据，在 Windows 资源管理器中右键 → 属性 → 详细信息中可见。

### 5.6 替换图标

1. 准备 `256×256` 或 `32×32` 的 `.ico` 文件（可用 [ConvertICO](https://convertico.com/) 在线转换）
2. 覆盖 `icon.ico`
3. 重新运行 `build.bat`

---

## 6. 常见问题

### Q: 为什么选择 tkinter 而不是 Qt/WPF？

tkinter 是 Python 标准库的一部分，打包后不会增加额外体积。Qt (PyQt/PySide) 打包后会增加 50-100 MB 体积，且部署更复杂。对于工具类软件，tkinter 的「够用」比 Qt 的「强大」更合适。

### Q: 为什么不用 `os.startfile()` 或 `subprocess` 来清空回收站？

`SHEmptyRecycleBinW` 是 Windows 原生 API，比任何间接调用都快且稳定。同样，`SHQueryRecycleBinW` 可以直接获取回收站大小和文件数，无需遍历文件系统。

### Q: `--onefile` 打包后 exe 启动慢怎么办？

`--onefile` 模式会在首次启动时自解压到临时目录。以下方法可优化：
- 使用 `--onedir` 模式（启动更快，但输出为文件夹）
- 排除不必要的包（`--exclude`）
- 首次启动稍等片刻，后续在同一台机器上会更快（Windows 文件缓存）

### Q: 杀毒软件报毒？

PyInstaller 打包的程序可能被某些杀毒软件误报，原因是：
1. PyInstaller 使用了代码打包技术（类似于压缩壳）
2. 程序调用了 Win32 API（Shell32、Kernel32 等）

**解决方案：** 向杀毒软件添加信任排除项，或使用源码运行（`python disk_cleaner.py`）。

### Q: 如何添加新的清理任务？

1. 继承 `CleanTask` 实现 `scan()` 和 `clean()` 方法
2. 在 `DiskCleanerApp.__init__` 的 `self.tasks` 列表中添加实例
3. 如需特殊 UI 控件（如下载天数的输入框），在 `_build_ui()` 中添加条件渲染

示例：
```python
class MyNewTask(CleanTask):
    def __init__(self):
        super().__init__("my_key", "📦 我的清理项", "描述")

    def scan(self, log_callback=None):
        # ... 实现扫描逻辑
        return size

    def clean(self, use_recycle_bin=False, log_callback=None):
        # ... 实现清理逻辑

# 在 DiskCleanerApp.__init__ 中：
self.tasks = [
    # ... 已有任务
    MyNewTask(),
]
```

---

## 附录：Windows API 参考

本工具直接调用的 Win32 API：

| API | 用途 | 所在模块 |
|-----|------|---------|
| `Shell32.SHGetFolderPathW` | 获取系统特殊文件夹路径 | 工具函数 |
| `Shell32.SHFileOperationW` | 移动文件到回收站 | `send_to_recycle_bin` |
| `Shell32.SHQueryRecycleBinW` | 查询回收站信息 | `RecycleBinTask` |
| `Shell32.SHEmptyRecycleBinW` | 清空回收站 | `RecycleBinTask` |
| `Shell32.SHAddToRecentDocs` | 清除最近文档记录 | `RecentFilesTask` |
| `Shell32.ShellExecuteW` | 以管理员身份重启 | `ensure_admin_and_restart` |
| `Shell32.Shell_NotifyIconW` | 系统托盘通信 | `WindowsTrayIcon` |
| `User32.RegisterClassExW` | 注册窗口类 | `WindowsTrayIcon` |
| `User32.CreateWindowExW` | 创建隐藏窗口 | `WindowsTrayIcon` |
| `User32.DefWindowProcW` | 默认窗口过程 | `WindowsTrayIcon` |
| `User32.LoadImageW` | 加载图标资源 | `WindowsTrayIcon` |
| `User32.LoadIconW` | 加载系统默认图标 | `WindowsTrayIcon` |
| `User32.PeekMessageW` | 泵消息 | `WindowsTrayIcon` |
| `User32.DispatchMessageW` | 分发消息 | `WindowsTrayIcon` |
| `User32.DestroyWindow` | 销毁窗口 | `WindowsTrayIcon` |
| `Kernel32.GetModuleHandleW` | 获取模块句柄 | `WindowsTrayIcon` |
| `Shell32.IsUserAnAdmin` | 权限检测 | 全局 |

---

> **文档版本**: 1.0
> **最后更新**: 2026-06-09
> **项目地址**: `C:\Users\Lenovo\Desktop\DiskCleaner\`
