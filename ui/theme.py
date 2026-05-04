"""Shared UI theme tokens."""

from __future__ import annotations

THEMES = {
    "dark": {
        "bg": "#0f1115",
        "panel": "#11141a",
        "surface": "#171a21",
        "surface2": "#1c1f28",
        "hover": "#252a36",
        "border": "#2a313a",
        "text": "#e6eaf2",
        "muted": "#8b95a1",
        "muted2": "#6c7680",
        "accent": "#62d2a2",
        "danger": "#e66b6b",
        "warning": "#f4b942",
        "info": "#5aa9e6",
    },
    "light": {
        "bg": "#f4f6fa",
        "panel": "#f8fafc",
        "surface": "#ffffff",
        "surface2": "#eef2f7",
        "hover": "#e5ebf3",
        "border": "#cfd8e3",
        "text": "#172033",
        "muted": "#526070",
        "muted2": "#7a8696",
        "accent": "#1e7e5a",
        "danger": "#c53030",
        "warning": "#9a6b00",
        "info": "#2563a8",
    },
}


def normalize_theme(theme: str | None) -> str:
    return "light" if str(theme or "").strip().lower() == "light" else "dark"


def tokens(theme: str | None) -> dict[str, str]:
    return THEMES[normalize_theme(theme)]


def app_stylesheet(theme: str | None) -> str:
    t = tokens(theme)
    return f"""
    QMainWindow, QWidget {{ background: {t['bg']}; color: {t['text']}; }}
    QLabel {{ color: {t['text']}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QComboBox {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; selection-background-color: {t['hover']};
    }}
    QPushButton {{
        background: {t['surface2']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 10px;
    }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QTabWidget::pane {{ border: 1px solid {t['border']}; }}
    QTabBar::tab {{ background: {t['surface2']}; color: {t['muted']}; padding: 8px 12px; }}
    QTabBar::tab:selected {{ background: {t['surface']}; color: {t['text']}; }}
    """


def settings_panel_stylesheet(theme: str | None) -> str:
    t = tokens(theme)
    return f"""
    SettingsPanel {{ background: {t['panel']}; }}
    QGroupBox {{
        font-size: 13px; font-weight: 600; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 8px; margin-top: 18px; padding: 16px 16px 16px 28px; background: {t['surface']};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 28px; padding: 0 6px; color: {t['accent']}; }}
    QLabel {{ color: {t['muted2']}; font-size: 12px; }}
    QLineEdit, QComboBox {{
        background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 10px;
        color: {t['text']}; font-size: 13px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QComboBox::drop-down {{ border: none; padding-right: 6px; }}
    QComboBox QAbstractItemView {{
        background: {t['surface2']}; border: 1px solid {t['border']}; color: {t['text']}; selection-background-color: {t['hover']};
    }}
    QPushButton {{
        background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 14px;
        color: {t['text']}; font-size: 12px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: {t['panel']}; width: 8px; border-radius: 4px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QFrame#rtspCard {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 12px; }}
    QLabel#statusOk {{ color: {t['accent']}; font-size: 11px; font-weight: 600; }}
    QLabel#statusOff {{ color: {t['danger']}; font-size: 11px; font-weight: 600; }}
    QLabel#statusTesting {{ color: {t['warning']}; font-size: 11px; font-weight: 600; }}
    QLabel#sectionHeader {{ color: {t['accent']}; font-size: 13px; font-weight: 700; padding: 4px 0px; }}
    QLabel#badge {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 2px 10px; color: {t['text']}; font-size: 11px; }}
    QCheckBox {{ color: {t['muted2']}; font-size: 12px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {t['border']}; background: {t['surface2']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}
    QWidget#sectionAccent {{ background: {t['accent']}; border-radius: 2px; min-width: 3px; max-width: 3px; }}
    """
