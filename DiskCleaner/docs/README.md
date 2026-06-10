# 🧹 Windows 智能垃圾清理工具 / Windows Smart Disk Cleaner

> 版本: **v0.2** | 🌐 中英双语 | 一键清理 Windows 系统垃圾，释放磁盘空间
> Version: **v0.2** | 🌐 Chinese & English | One-click Windows disk cleanup
> 双击即用，无需安装 Python 或任何依赖
> Double-click to run, no Python or dependencies required

---

## 📦 功能概览 / Features

| 功能 / Feature | 说明 / Description | 是否需要管理员 / Admin Required |
|------|------|:---:|
| 📁 系统临时文件 / System Temp Files | 清理 %TEMP%、%WINDIR%\Temp 等目录 | 部分需管理员 |
| ♻ 回收站 / Recycle Bin | 清空回收站（可查看当前大小） | ⚠ 彻底清空需要 |
| 🌐 浏览器缓存 / Browser Cache | 清理 Chrome / Edge 缓存 | 否 / No |
| 📥 旧下载文件 / Old Downloads | 删除下载文件夹中超过 N 天的文件 | 否 / No |
| 📋 最近访问记录 / Recent Files | 清理 Recent 文件夹快捷方式 | 否 / No |
| 📜 系统日志 / System Logs | 清理 C:\Windows\Logs、.etl、dump 等 | ✅ 需要 / Yes |

**安全机制 / Safety Features：**
- ✅ 默认「移动到回收站」模式——误删可恢复 / Default "Move to Recycle Bin" — recoverable
- ✅ 清理前计算总量并弹窗确认 / Calculates total size and confirms before cleanup
- ✅ 模拟运行模式——只预览不删除 / Simulation mode — preview only, no deletion
- ✅ 每个功能独立扫描，清除前可查看详情 / Each feature scans independently
- ✅ **启动时自动申请管理员权限**（UAC 弹窗），确保完整功能 / Auto-elevates to admin via UAC

**🌐 多语言支持 / Multi-language Support：**
- 自动检测 Windows 系统语言 / Auto-detects Windows system language
- 支持中文和英文 / Supports Chinese and English
- 一键切换，偏好自动保存 / One-click toggle, preference saved
- 扩展新语言只需添加 JSON 文件 / Add new languages via JSON files

---

## 📖 文档索引

| 文档 | 说明 |
|------|------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **设计思路、项目架构、模块详解、打包部署**（开发者必读） |
| [`CHANGELOG.md`](CHANGELOG.md) | **版本历史与更新日志** |
| `README.md` | **快速入门**（本文件） |

---

## 🚀 快速开始 / Quick Start

### 方法一：直接下载已打包的 exe / Download pre-built exe

> 从 Release 页面下载 `DiskCleaner.exe`，双击运行即可。
> Download from Releases page, double-click to run.

### 方法二：自己打包 / Build from source

#### 1️⃣ 环境准备 / Prerequisites

安装 Python 3.8+（[官网下载](https://www.python.org/downloads/)）

#### 2️⃣ 一键打包 / One-click build

```batch
# 双击 build.bat，自动完成所有步骤
# 或者在命令行中执行：
build.bat
```

#### 3️⃣ 手动打包 / Manual build (optional)

```batch
pip install pyinstaller pywin32
pyinstaller DiskCleaner.spec --clean --noconfirm
```

打包完成后的 exe 位于 `dist\DiskCleaner.exe`。

### 🌐 指定语言 / Specify Language

通过命令行参数指定界面语言：
Specify UI language via command line:

```batch
# 英文界面 / English interface
DiskCleaner.exe --lang=en

# 中文界面 / Chinese interface
DiskCleaner.exe --lang=zh_CN
```

不指定时自动检测 Windows 系统语言。
Auto-detects Windows language when not specified.

---

## 🎨 更换图标

1. 准备一个 `.ico` 格式的图标文件（建议 32×32 或 64×64，256 色或 32 位色）
2. 将文件命名为 `icon.ico`，放在项目根目录
3. 重新运行 `build.bat` 打包

**在线图标生成工具推荐：**
- [ConvertICO](https://convertico.com/)
- [icoconverter.com](https://www.icoconverter.com/)
- 任何 PNG → ICO 在线转换器

**使用自己的图片制作图标：**
```batch
# 使用 Python 和 Pillow 库（需安装）
pip install Pillow
python -c "from PIL import Image; img=Image.open('your_image.png'); img.save('icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64)])"
```

---

## ⚙ 详细参数说明

### 旧文件天数设置

在「下载文件夹旧文件」区域的输入框中直接修改数字（默认 30 天），支持 1~999 之间的任意整数。

### 清理模式

- **移动到回收站（安全）** ✅【默认】— 删除的文件可在回收站恢复
- **不勾选 = 永久删除** — 文件直接被删除，不可恢复

> 系统临时文件使用的是永久删除（直接删），这是为了达到清理效果；其他项目默认走回收站。

---

## 🔐 管理员权限

本工具**启动时会自动请求管理员权限**（弹出 UAC 确认窗口），点击「是」即可获得完整功能。

| 情况 | 表现 | 解决办法 |
|------|------|----------|
| UAC 弹窗时点击「是」 | 完整管理员权限，所有功能可用 | — |
| UAC 弹窗时点击「否」 | 降级为普通权限运行，系统日志等功能受限 | 手动重启 exe 并接受 UAC |
| 右键 →「以管理员身份运行」| 跳过 UAC 弹窗，直接以管理员运行 | 如果需要每次都自动提权 |

> 注：部分杀毒软件可能会拦截 UAC 提权请求，请允许程序运行。

---

## 📁 项目文件结构

```
DiskCleaner/
├── disk_cleaner.py      # 主入口（GUI 界面 + main 启动函数）
├── config.py            # 全局常量、权限检测、Windows 特殊文件夹
├── utils.py             # 工具函数（格式化、文件夹大小、回收站操作）
├── clean_tasks.py       # 六大清理任务类（临时文件/回收站/浏览器缓存/旧文件/最近记录/系统日志）
├── tray.py              # 系统托盘图标（纯 ctypes 实现）
├── log_manager.py       # 日志管理器（每日轮转、线程安全）
├── app_cleaner.py       # 应用软件缓存清理（微信/QQ/钉钉/飞书等 10+ 款软件）
├── i18n.py              # 🌐 国际化模块（中英双语翻译引擎）
├── lang/                # 🌐 语言包目录
│   ├── zh_CN.json       # 中文语言包
│   └── en.json          # English language pack
├── DiskCleaner.spec     # PyInstaller 打包配置
├── build.bat            # 一键构建脚本（双击运行）
├── generate_icon.py     # 图标生成器（纯 Python）
├── icon.ico             # 程序图标
├── README.md            # 本说明文件
├── CHANGELOG.md         # 版本更新历史
├── ARCHITECTURE.md      # 设计文档（开发者必读）
└── dist/                # 打包输出目录（运行 build.bat 后生成）
    └── DiskCleaner.exe  # 最终可执行文件
```

---

## 🛠 技术栈 / Tech Stack

- **GUI 框架**: tkinter（Python 标准库）
- **Windows API**: ctypes（直接调用 Shell32, Kernel32）
- **国际化**: 自研 i18n 模块（JSON 语言包 + 自动语言检测）
- **打包工具**: PyInstaller
- **目标平台**: Windows 10/11 x64

---

## ❓ 常见问题

**Q: 打包后的 exe 体积有多大？**
A: 约 8~15 MB（取决于 PyInstaller 版本）。

**Q: 可以在 Windows 7 上运行吗？**
A: 理论支持 Windows 7+，但建议在 Windows 10/11 上使用以获得最佳体验。

**Q: 清理后文件还能恢复吗？**
A: 如果勾选了「移动到回收站」，文件可从回收站恢复。未勾选则永久删除。

**Q: 提示「不是有效的 Win32 应用程序」怎么办？**
A: 确保在 Windows 64 位系统上运行，且已安装 Visual C++ Redistributable。

**Q: 杀毒软件报毒？**
A: PyInstaller 打包的程序可能被某些杀毒软件误报。这是因为打包方式（而非程序本身）的特征。添加信任即可。

**Q: 如何切换语言？ / How to switch language?**
A: 点击窗口标题栏右侧的 🌐 按钮，或在系统托盘右键菜单中选择语言。也可通过命令行 `--lang=en` 或 `--lang=zh_CN` 指定。偏好自动保存。
A: Click the 🌐 button in the title bar, or use the system tray right-click menu. You can also specify via command line `--lang=en` or `--lang=zh_CN`. Preference is auto-saved.

**Q: 如何添加新语言？ / How to add a new language?**
A: 在 `lang/` 目录下创建 `{语言代码}.json`，参考 `en.json` 的格式翻译所有键值。然后在 `i18n.py` 的 `LANGUAGES` 字典中添加条目即可。
A: Create `{language_code}.json` in the `lang/` directory, translate all key-value pairs referencing `en.json` format. Then add an entry in the `LANGUAGES` dict in `i18n.py`.

---

## 📝 许可证

本工具仅供个人学习和使用，免费开源。

---

## 项目截图

运行界面预览（文字版）：

```
┌──────────────────────────────────────────────────────────────┐
│  🧹 Windows 智能垃圾清理 v2.0          [管理员模式]          │
├──────────────────────────────────────────────────────────────┤
│  ☑ 📁 系统临时文件           🔍 扫描         1.23 GB (8912项) │
│  ☑ ♻ 回收站                 🔍 扫描          128.45 MB (342项)│
│  ☑ 🌐 浏览器缓存             🔍 扫描          456.78 MB (2341项)│
│  ☑ 📥 下载文件夹旧文件       🔍 扫描          89.12 MB (56项)  │
│      超过 [ 30 ] 天的文件                                        │
│  ☑ 📋 最近访问记录           🔍 扫描              0 B (0项)    │
│  ☑ 📜 系统日志文件           🔍 扫描          2.34 GB (4012项) │
├──────────────────────────────────────────────────────────────┤
│  [☑全选] [☐全不选] | [🔍扫描全部] [☑移动到回收站(安全)]     │
│                        [模拟运行] [ 🧹 开始清理 ]            │
├──────────────────────────────────────────────────────────────┤
│  ████████████████████████████████████████ 100%               │
│  📊 共可释放空间: 4.21 GB                                    │
├──────────────────────────────────────────────────────────────┤
│ 📋 运行日志                                                   │
│ [10:23:45] 🔍 开始扫描所有项目 ...                            │
│ [10:23:46] 📁 系统临时文件: 1.23 GB (8912 项)                │
│ [10:23:47] ♻ 回收站: 128.45 MB (342 项)                      │
│ [10:23:51] 🌐 浏览器缓存: 456.78 MB (2341 项)                │
│ [10:23:52] 🔍 全部扫描完成！                                  │
└──────────────────────────────────────────────────────────────┘
```
