"""
Language definitions.

Previously used for Gradio i18n. Now only provides the LANGUAGES list
used by the web UI frontend (js/i18n.js handles the actual i18n).
"""

LANGUAGES = [
    ("English", "en"),
    ("简体中文", "zh"),
    ("繁體中文", "zh-TW"),
    ("日本語", "ja"),
    ("한국인", "ko"),
    ("Français", "fr"),
    ("Deutsch", "de"),
    ("Español", "es"),
    ("Русский", "ru"),
    ("Italiano", "it"),
    ("Português", "pt"),
]


def _(text):
    """No-op gettext stub."""
    return text
