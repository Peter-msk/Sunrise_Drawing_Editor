"""Drawing Editor-specific design tokens and non-Qt layout breakpoints.

Keep page dimensions out of the global stylesheet and independent of the CAD engine.
The breakpoints use *logical Qt pixels*, not physical monitor pixels.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelLayout:
    file_width: int
    layer_width: int
    show_brand: bool
    show_selection_help: bool


def panel_layout(window_width: int) -> PanelLayout:
    """Reserve a usable preview even on a high-DPI, small logical desktop.

    All panes intentionally remain non-draggable: their geometry is stable at
    each breakpoint and the user cannot accidentally collapse a control pane.
    """
    if window_width < 900:
        return PanelLayout(166, 232, False, False)
    if window_width < 1120:
        return PanelLayout(218, 275, False, False)
    if window_width < 1340:
        return PanelLayout(265, 305, True, True)
    return PanelLayout(292, 330, True, True)


@dataclass(frozen=True)
class ThemeTokens:
    background: str
    panel: str
    foreground: str
    muted: str
    border: str
    input_background: str
    hover: str
    selection: str
    canvas: str
    primary: str
    primary_hover: str
    active_text: str


THEMES = {
    'light': ThemeTokens(
        background='#F7F9FC', panel='#FFFFFF', foreground='#243D60',
        muted='#5F7188', border='#DCE3EB', input_background='#FFFFFF',
        hover='#FFF0E4', selection='#FFEDDE', canvas='#E9EEF4',
        primary='#B8480B', primary_hover='#91370A', active_text='#9B390D'),
    'dark': ThemeTokens(
        background='#121B28', panel='#1D2939', foreground='#E9F1FB',
        muted='#ACC0D6', border='#344559', input_background='#253447',
        hover='#3E3A37', selection='#4C3429', canvas='#101A29',
        primary='#B8480B', primary_hover='#91370A', active_text='#FFC49E'),
}
