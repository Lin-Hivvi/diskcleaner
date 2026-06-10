# -*- coding: utf-8 -*-
"""
国际化／本地化模块 (i18n)
=========================
支持中英文双语，可从 JSON 语言包加载翻译。
提供 t() 快捷函数供主程序调用。

用法：
    from src.i18n import t, set_language, current_lang
    t("app_name")           # → "Windows 智能垃圾清理" / "Windows Smart Disk Cleaner"
    t("task.scan_btn")      # → "🔍 扫描" / "🔍 Scan"
    set_language("en")      # 动态切换
"""

import os
import json
import locale as _locale
import sys

# ============================================================
# 语言包路径
# ============================================================
# i18n.py 在 src/ 下，lang/ 在项目根目录，需要向上两层
_LANG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lang"
)

# ============================================================
# 当前语言状态
# ============================================================
_current_lang = "zh_CN"  # 默认中文
_translations = {}       # 当前语言的翻译字典

# ============================================================
# 可用语言列表
# ============================================================
LANGUAGES = {
    "zh_CN": {"name": "中文", "name_en": "Chinese"},
    "en":    {"name": "English", "name_en": "English"},
}


def detect_system_language():
    """
    检测 Windows 系统 UI 语言。
    返回语言代码，如 "zh_CN", "en"。
    """
    try:
        # 方法1: 通过 ctypes 获取 Windows UI 语言
        import ctypes
        # GetUserDefaultUILanguage() 返回 LANGID
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        # LANGID 的低 10 位是主语言，高 6 位是子语言
        primary = lang_id & 0x3FF
        sub = (lang_id >> 10) & 0x3F

        # 常见语言映射
        if primary == 0x04:      # 中文
            if sub == 0x01:      # 简体中文
                return "zh_CN"
            elif sub == 0x02:    # 繁体中文
                return "zh_CN"   # 暂时也映射到简体
            return "zh_CN"
        elif primary == 0x09:     # 英语
            return "en"
        # 其他语言默认用英文界面
        return "en"
    except Exception:
        pass

    # 方法2: 通过 locale 模块检测
    try:
        sys_lang, sys_enc = _locale.getdefaultlocale()
        if sys_lang:
            if sys_lang.startswith("zh"):
                return "zh_CN"
            else:
                return "en"
    except Exception:
        pass

    return "zh_CN"  # 默认中文


def load_translations(lang_code):
    """
    加载指定语言的语言包。
    先从 lang/{lang_code}.json 加载，若不存在则回退到 lang/en.json。
    """
    path = os.path.join(_LANG_DIR, f"{lang_code}.json")
    if not os.path.exists(path):
        # 回退到英文
        path = os.path.join(_LANG_DIR, "en.json")
        if not os.path.exists(path):
            return {}  # 无语义包可用

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def set_language(lang_code):
    """
    切换语言。
    lang_code: "zh_CN" 或 "en"
    """
    global _current_lang, _translations

    if lang_code not in LANGUAGES:
        lang_code = "zh_CN"

    _current_lang = lang_code
    _translations = load_translations(lang_code)


def current_lang():
    """获取当前语言代码"""
    return _current_lang


def t(key, *args, **kwargs):
    """
    翻译函数：根据 key 查找翻译文本。
    若找不到 key，返回 key 本身（方便调试）。

    支持格式化：
        t("scanning_progress", count="10")
        对应 JSON 中: "scanning_progress": "已扫描 %(count)s 项"
    """
    if not _translations:
        return key

    text = _translations.get(key)
    if text is None:
        return key

    # 支持 % 格式化
    if args or kwargs:
        try:
            return text % (args if args else kwargs)
        except (TypeError, ValueError):
            pass

    return text


def t_fmt(key, **kwargs):
    """
    格式化翻译——明确需要格式化参数的场景。
    """
    return t(key, **kwargs)


def get_available_languages():
    """
    获取所有可用的语言列表。
    返回 [(code, display_name), ...]
    """
    results = []
    for code, info in LANGUAGES.items():
        path = os.path.join(_LANG_DIR, f"{code}.json")
        if os.path.exists(path):
            display = info["name_en"] if _current_lang == "en" else info["name"]
            results.append((code, display))
    if not results:
        results = [("zh_CN", "中文")]
    return results


# ============================================================
# 初始化
# ============================================================
# 检测命令行参数 --lang
_initial_lang = None
for i, arg in enumerate(sys.argv[1:], 1):
    if arg.startswith("--lang="):
        _initial_lang = arg.split("=", 1)[1]
        break
    # 也支持 --lang zh_CN 格式
    if arg == "--lang" and i < len(sys.argv) - 1:
        _initial_lang = sys.argv[i + 1]
        break

if _initial_lang and _initial_lang in LANGUAGES:
    set_language(_initial_lang)
else:
    # 自动检测系统语言
    detected = detect_system_language()
    set_language(detected)
