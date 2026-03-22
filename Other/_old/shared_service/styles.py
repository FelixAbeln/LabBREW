from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AppPalette:
    window_bg: str = "#f3f5f7"
    text: str = "#1f2937"
    panel_bg: str = "#ffffff"
    panel_border: str = "#d0d7de"
    value_bg: str = "#f8fafc"
    value_border: str = "#dbe2ea"
    input_border: str = "#c8d1da"
    button_bg: str = "#d1d5db"
    button_hover_bg: str = "#c5cad3"
    button_border: str = "#b8c0cc"
    header_bg: str = "#123b64"
    header_text: str = "#ffffff"
    tab_bg: str = "#e7edf3"
    tab_border: str = "#c3ced8"
    confirm_bg: str = "#dcfce7"
    confirm_text: str = "#166534"
    confirm_border: str = "#86efac"
    success_bg: str = "#16a34a"
    success_text: str = "#ffffff"
    warning_bg: str = "#facc15"
    warning_text: str = "#111827"
    neutral_bg: str = "#d1d5db"
    neutral_text: str = "#111827"
    blink_on_bg: str = "#22c55e"
    blink_on_text: str = "#ffffff"
    blink_off_bg: str = "#bbf7d0"
    blink_off_text: str = "#166534"


def build_main_window_stylesheet(palette: AppPalette | None = None) -> str:
    p = palette or AppPalette()
    return f"""
    QMainWindow, QWidget {{ background: {p.window_bg}; color: {p.text}; }}
    QGroupBox {{ font-weight: 600; border: 1px solid {p.panel_border}; border-radius: 8px; margin-top: 12px; padding-top: 12px; background: {p.panel_bg}; }}
    QLabel {{ background: transparent; }}
    QGroupBox QLabel[role="value"] {{ background: {p.value_bg}; border: 1px solid {p.value_border}; border-radius: 6px; padding: 4px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
    QLineEdit, QComboBox, QTextEdit, QTableWidget {{
        background: {p.panel_bg}; border: 1px solid {p.input_border}; border-radius: 6px; padding: 4px;
    }}
    QPushButton {{
        background: {p.button_bg}; color: {p.neutral_text}; border: 1px solid {p.button_border}; border-radius: 8px; padding: 8px 16px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {p.button_hover_bg}; }}
    QHeaderView::section {{ background: {p.header_bg}; color: {p.header_text}; padding: 6px; border: none; font-weight: 600; }}
    QTabWidget::pane {{ background: {p.panel_bg}; border: 1px solid {p.tab_border}; border-radius: 8px; top: -1px; }}
    QTabBar::tab {{ background: {p.tab_bg}; padding: 8px 16px; border: 1px solid {p.tab_border}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; min-width: 120px; }}
    QTabBar::tab:selected {{ background: {p.panel_bg}; margin-bottom: -1px; }}
    QTextEdit {{ background: {p.panel_bg}; }}
    QLabel#LogTitle {{ font-weight: 600; }}
    QLabel#SectionTitle {{ font-weight: 600; }}
    """


def build_status_banner_stylesheet(palette: AppPalette | None = None) -> str:
    p = palette or AppPalette()
    return (
        f"background: {p.confirm_bg}; color: {p.confirm_text}; border: 1px solid {p.confirm_border}; "
        "border-radius: 8px; padding: 10px; font-weight: 700;"
    )


def button_role_stylesheet(role: str, blink_on: bool = False, palette: AppPalette | None = None) -> str:
    p = palette or AppPalette()
    mapping = {
        "green": (p.success_bg, p.success_text),
        "yellow": (p.warning_bg, p.warning_text),
        "grey": (p.neutral_bg, p.neutral_text),
        "blink": ((p.blink_on_bg if blink_on else p.blink_off_bg), (p.blink_on_text if blink_on else p.blink_off_text)),
    }
    bg, fg = mapping[role]
    return f"background: {bg}; color: {fg}; border: 1px solid #94a3b8; border-radius: 8px; padding: 8px 16px; font-weight: 700;"
