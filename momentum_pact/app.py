from __future__ import annotations

import argparse
import calendar
import ctypes
import os
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from .framework import (
    AccountabilityError,
    AccountabilityStore,
    classify_commitment,
    format_countdown,
    format_due_in,
    format_when,
    now_local,
    parse_datetime,
)
from .paths import DEFAULT_DATA_PATH


WINDOW_TITLE = "Momentum Pact"

COLORS = {
    # Mountain rice: night, ravine, stone, mist, snow, and aurora.
    "background": "#050a10",
    "panel": "#09131b",
    "panel_alt": "#17232d",
    "border": "#22333e",
    "text": "#d5e0e6",
    "muted": "#9dafbb",
    "tagline": "#35434c",
    "accent": "#5aafa2",
    "panel_hover": "#2a3b46",
    "selection": "#243b43",
    "trough": "#071019",
    "accent_text": "#050a10",
    "accent_hover": "#69c9ba",
    "danger_hover": "#26171b",
    # Near-neon signal colors against the restrained mountain-night surfaces.
    "overdue": "#ff4057",
    "due_soon": "#ffd166",
    "check_in_due": "#c99cff",
    "planned": "#9dafbb",
    "in_progress": "#66c2ff",
    "completed": "#63e6a6",
    "triaged": "#71838f",
}

FONT_THEME = {
    "ui_family": "Segoe UI",
    "mono_family": "Consolas",
    "scale": 1.0,
}


def themed_font(size: int, weight: str = "normal", *, mono: bool = False) -> tuple:
    """Build a font tuple from the centralized family and scale settings."""
    family_key = "mono_family" if mono else "ui_family"
    scaled_size = max(1, round(size * float(FONT_THEME["scale"])))
    return (FONT_THEME[family_key], scaled_size, weight)


def ui_font(size: int, weight: str = "normal") -> tuple:
    return themed_font(size, weight)


def mono_font(size: int, weight: str = "normal") -> tuple:
    return themed_font(size, weight, mono=True)


def child_window_geometry(
    parent: tk.Misc,
    width: int,
    height: int,
    anchor: tk.Widget | None = None,
) -> str:
    """Attach a child to its trigger, falling back to parent-centered placement."""
    parent.update_idletasks()
    if anchor is None:
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        return f"{width}x{height}+{x}+{y}"

    anchor.update_idletasks()
    anchor_left = anchor.winfo_rootx()
    anchor_top = anchor.winfo_rooty()
    anchor_right = anchor_left + anchor.winfo_width()
    anchor_bottom = anchor_top + anchor.winfo_height()
    parent_center = parent.winfo_rootx() + parent.winfo_width() / 2
    anchor_center = anchor_left + anchor.winfo_width() / 2
    x = anchor_left if anchor_center <= parent_center else anchor_right - width
    y = anchor_bottom

    screen_left = parent.winfo_vrootx()
    screen_top = parent.winfo_vrooty()
    screen_right = screen_left + parent.winfo_vrootwidth()
    screen_bottom = screen_top + parent.winfo_vrootheight()
    if y + height > screen_bottom:
        y = anchor_top - height
    x = min(max(x, screen_left), max(screen_left, screen_right - width))
    y = min(max(y, screen_top), max(screen_top, screen_bottom - height))
    return f"{width}x{height}+{x}+{y}"


def apply_windows_window_theme(window: tk.Misc) -> None:
    """Match native Windows title bars and borders to the dashboard palette."""
    if os.name != "nt":
        return

    def colorref(hex_color: str) -> int:
        red, green, blue = bytes.fromhex(hex_color.removeprefix("#"))
        return red | (green << 8) | (blue << 16)

    try:
        window.update_idletasks()
        client_handle = window.winfo_id()
        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        parent_handle = get_parent(ctypes.c_void_p(client_handle))
        window_handle = parent_handle or client_handle
        dwm = ctypes.windll.dwmapi

        dark_mode = ctypes.c_int(1)
        for attribute in (20, 19):
            result = dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(window_handle),
                attribute,
                ctypes.byref(dark_mode),
                ctypes.sizeof(dark_mode),
            )
            if result == 0:
                break

        native_colors = {
            34: COLORS["border"],
            35: COLORS["background"],
            36: COLORS["text"],
        }
        for attribute, color in native_colors.items():
            value = ctypes.c_uint(colorref(color))
            dwm.DwmSetWindowAttribute(
                ctypes.c_void_p(window_handle),
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except (AttributeError, OSError, tk.TclError):
        pass


class AccountabilityApp:
    def __init__(
        self,
        root: tk.Tk,
        data_path: Path = DEFAULT_DATA_PATH,
        window_title: str = WINDOW_TITLE,
    ):
        self.root = root
        self.data_path = data_path
        self.window_title = window_title
        self.store = AccountabilityStore(data_path)
        self.current_filter = tk.StringVar(value="All")
        self.clock_var = tk.StringVar()
        self.summary_vars = {
            key: tk.StringVar(value="0")
            for key in ("overdue", "due_soon", "check_in_due", "active", "completed")
        }
        self.detail_title = tk.StringVar(value="Select a commitment")
        self.detail_meta = tk.StringVar(value="")
        self.countdown_var = tk.StringVar(value="—")
        self.commitment_progress_var = tk.StringVar(value="NO WIN CONDITIONS YET")
        self.linked_goal_var = tk.StringVar(value="No linked goal")
        self.goal_action_var = tk.StringVar(value="Link goal")
        self.archive_action_var = tk.StringVar(value="Archive commitment")
        self._condition_vars: list[tk.BooleanVar] = []
        self._last_status_refresh_minute: str | None = None
        self._selected_item_id: str | None = None
        self._pane_resize_pending = False
        self._history_scroll_active = False

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()
        self.refresh()
        self._fit_initial_layout()
        self._tick()

    def _configure_window(self) -> None:
        self.root.title(self.window_title)
        icon_path = Path(__file__).parent / "assets" / "momentum-pact.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        apply_windows_window_theme(self.root)
        self.root.geometry("1600x900")
        self.root.minsize(860, 560)
        self.root.configure(bg=COLORS["background"])

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            relief="flat",
            rowheight=46,
            font=ui_font(11),
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["panel"])],
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel_alt"],
            foreground=COLORS["muted"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            relief="flat",
            font=ui_font(10, "bold"),
            padding=(12, 13),
        )
        style.map("Treeview.Heading", background=[("active", COLORS["panel_alt"])])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["panel_alt"],
            background=COLORS["panel_alt"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLORS["panel_alt"])],
            background=[
                ("readonly", COLORS["panel_alt"]),
                ("active", COLORS["panel_hover"]),
            ],
            foreground=[("readonly", COLORS["text"])],
            selectbackground=[("readonly", COLORS["panel_alt"])],
            selectforeground=[("readonly", COLORS["text"])],
            arrowcolor=[("readonly", COLORS["text"])],
            bordercolor=[
                ("focus", COLORS["accent"]),
                ("readonly", COLORS["border"]),
            ],
        )
        style.layout(
            "Mountain.Vertical.TScrollbar",
            [
                (
                    "Vertical.Scrollbar.trough",
                    {
                        "sticky": "ns",
                        "children": [
                            (
                                "Vertical.Scrollbar.thumb",
                                {"expand": "1", "sticky": "nswe"},
                            )
                        ],
                    },
                )
            ],
        )
        style.configure(
            "Mountain.Vertical.TScrollbar",
            troughcolor=COLORS["trough"],
            background=COLORS["border"],
            bordercolor=COLORS["trough"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            relief="flat",
            width=11,
        )
        style.map(
            "Mountain.Vertical.TScrollbar",
            background=[
                ("pressed", COLORS["accent_hover"]),
                ("active", COLORS["accent"]),
            ],
        )
        for widget_class in ("Entry", "Text", "Listbox", "Spinbox"):
            self.root.option_add(f"*{widget_class}.highlightThickness", 1)
            self.root.option_add(
                f"*{widget_class}.highlightBackground", COLORS["border"]
            )
            self.root.option_add(
                f"*{widget_class}.highlightColor", COLORS["accent"]
            )
            self.root.option_add(f"*{widget_class}.borderWidth", 0)
        self.root.option_add("*Button.highlightThickness", 0)
        self.root.option_add("*Button.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.background", COLORS["panel_alt"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add(
            "*TCombobox*Listbox.selectBackground", COLORS["selection"]
        )
        self.root.option_add("*TCombobox*Listbox.selectForeground", COLORS["text"])
        style.configure(
            "Goal.Horizontal.TProgressbar",
            troughcolor=COLORS["trough"],
            background=COLORS["accent"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            thickness=8,
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["background"], padx=28, pady=22)
        header.pack(fill="x")
        title_group = tk.Frame(header, bg=COLORS["background"])
        title_group.pack(side="left")
        tk.Label(
            title_group,
            text="Momentum.",
            bg=COLORS["background"],
            fg=COLORS["tagline"],
            font=ui_font(25, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            textvariable=self.clock_var,
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=mono_font(15),
        ).pack(side="right", anchor="n", pady=8)

        summary = tk.Frame(self.root, bg=COLORS["background"], padx=24)
        summary.pack(fill="x")
        cards = (
            ("overdue", "OVERDUE", COLORS["overdue"]),
            ("due_soon", "DUE SOON", COLORS["due_soon"]),
            ("check_in_due", "CHECK-INS", COLORS["check_in_due"]),
            ("active", "ACTIVE", COLORS["in_progress"]),
            ("completed", "COMPLETED", COLORS["completed"]),
        )
        for column, (key, label, color) in enumerate(cards):
            summary.grid_columnconfigure(column, weight=1)
            card = tk.Frame(
                summary,
                bg=COLORS["panel"],
                highlightbackground=COLORS["border"],
                highlightthickness=1,
                padx=16,
                pady=12,
            )
            card.grid(row=0, column=column, sticky="ew", padx=5)
            tk.Label(
                card,
                textvariable=self.summary_vars[key],
                bg=COLORS["panel"],
                fg=color,
                font=ui_font(22, "bold"),
            ).pack(anchor="w")
            tk.Label(
                card,
                text=label,
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=ui_font(9, "bold"),
            ).pack(anchor="w")

        toolbar = tk.Frame(self.root, bg=COLORS["background"], padx=28, pady=16)
        toolbar.pack(fill="x")
        self.add_commitment_button = self._button(
            toolbar, "+ Commitment", self.open_add_commitment, accent=True
        )
        self.add_commitment_button.pack(side="left", padx=(0, 8))
        self.add_goal_button = self._button(toolbar, "+ Goal", self.open_add_goal)
        self.add_goal_button.pack(side="left", padx=4)
        self._button(toolbar, "Reopen", self.reopen).pack(side="left", padx=4)

        tk.Label(
            toolbar,
            text="VIEW",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=ui_font(9, "bold"),
        ).pack(side="right", padx=(12, 6))
        filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.current_filter,
            values=("Open", "Overdue", "Check-ins", "All", "Archived"),
            state="readonly",
            width=12,
        )
        self.filter_box = filter_box
        filter_box.pack(side="right")
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        content = tk.PanedWindow(
            self.root,
            orient="horizontal",
            bg=COLORS["border"],
            sashwidth=8,
            bd=0,
            relief="flat",
        )
        content.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self.content = content
        content.bind("<Configure>", self._schedule_pane_fit, add="+")

        list_panel = tk.Frame(content, bg=COLORS["panel"], padx=8, pady=8)
        detail_shell = tk.Frame(content, bg=COLORS["panel"])
        detail_canvas = tk.Canvas(
            detail_shell,
            bg=COLORS["panel"],
            bd=0,
            highlightthickness=0,
        )
        detail_scrollbar = ttk.Scrollbar(
            detail_shell,
            orient="vertical",
            command=detail_canvas.yview,
            style="Mountain.Vertical.TScrollbar",
        )
        detail_canvas.configure(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)
        detail_panel = tk.Frame(
            detail_canvas, bg=COLORS["panel"], padx=20, pady=26
        )
        self.detail_canvas_window = detail_canvas.create_window(
            (0, 0), window=detail_panel, anchor="nw"
        )
        self.list_panel = list_panel
        self.detail_shell = detail_shell
        self.detail_canvas = detail_canvas
        self.detail_panel = detail_panel
        detail_panel.bind("<Configure>", self._update_detail_scrollregion)
        detail_canvas.bind("<Configure>", self._resize_detail_content)
        self.root.bind_all("<MouseWheel>", self._on_detail_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_detail_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_detail_mousewheel, add="+")
        content.add(list_panel, minsize=480, stretch="always")
        content.add(detail_shell, minsize=360, stretch="always")

        columns = ("state", "title", "due_in")
        self.tree = ttk.Treeview(
            list_panel,
            columns=columns,
            show="tree headings",
            selectmode="browse",
        )
        self.selection_marker = tk.PhotoImage(master=self.root, width=4, height=28)
        self.selection_marker.put(COLORS["accent"], to=(0, 0, 4, 28))
        self.tree.heading("#0", text="")
        self.tree.column(
            "#0", width=34, minwidth=34, stretch=False, anchor="center"
        )
        headings = {
            "state": ("STATE", 125),
            "title": ("COMMITMENT", 360),
            "due_in": ("DUE IN", 155),
        }
        for key, (label, width) in headings.items():
            self.tree.heading(key, text=label)
            self.tree.column(
                key,
                width=width,
                minwidth=120 if key == "title" else 90,
                stretch=key == "title",
            )
        for tag in COLORS:
            if tag in {
                "overdue",
                "due_soon",
                "check_in_due",
                "planned",
                "in_progress",
                "completed",
                "triaged",
            }:
                self.tree.tag_configure(tag, foreground=COLORS[tag])
        self.tree.tag_configure(
            "check_in_due",
            foreground=COLORS["check_in_due"],
        )
        vertical_scrollbar = ttk.Scrollbar(
            list_panel,
            orient="vertical",
            command=self.tree.yview,
            style="Mountain.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=vertical_scrollbar.set)
        list_panel.grid_rowconfigure(0, weight=1)
        list_panel.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection)
        self.tree.bind("<Up>", lambda _event: self._move_tree_selection(-1))
        self.tree.bind("<Down>", lambda _event: self._move_tree_selection(1))
        self.tree.bind("<Double-1>", lambda _event: self.open_check_in())

        detail_header = tk.Frame(detail_panel, bg=COLORS["panel"])
        detail_header.pack(fill="x")
        tk.Label(
            detail_header,
            text="COMMITMENT DETAIL",
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            font=ui_font(9, "bold"),
        ).pack(side="left")
        self.check_in_button = tk.Button(
            detail_header,
            text="Check In",
            command=self.open_check_in,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["accent"],
            disabledforeground=COLORS["muted"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=4,
            pady=0,
        )
        self.check_in_button.pack(side="right")
        tk.Label(
            detail_panel,
            textvariable=self.detail_title,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(18, "bold"),
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(8, 4))
        tk.Label(
            detail_panel,
            textvariable=self.detail_meta,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=ui_font(10),
            justify="left",
        ).pack(anchor="w", pady=(0, 14))
        countdown_panel = tk.Frame(
            detail_panel,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        countdown_panel.pack(fill="x", pady=(0, 18))
        tk.Label(
            countdown_panel,
            text="TIME REMAINING · DAYS:HOURS:MINUTES:SECONDS",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=ui_font(8, "bold"),
        ).pack(anchor="w")
        self.countdown_label = tk.Label(
            countdown_panel,
            textvariable=self.countdown_var,
            bg=COLORS["panel_alt"],
            fg=COLORS["accent"],
            font=mono_font(18, "bold"),
        )
        self.countdown_label.pack(anchor="w", pady=(4, 0))
        self.commitment_progress_panel = tk.Frame(
            detail_panel,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        self.commitment_progress_panel.pack(fill="x", pady=(0, 18))
        progress_header = tk.Frame(
            self.commitment_progress_panel, bg=COLORS["panel_alt"]
        )
        progress_header.pack(fill="x")
        tk.Label(
            progress_header,
            text="COMMITMENT WIN CONDITIONS · SUBTASKS",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=ui_font(8, "bold"),
        ).pack(side="left")
        self.add_condition_button = tk.Button(
            progress_header,
            text="+ Add",
            command=self.open_add_win_condition,
            bg=COLORS["panel_alt"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_hover"],
            activeforeground=COLORS["accent"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(8, "bold"),
        )
        self.add_condition_button.pack(side="right")
        tk.Label(
            self.commitment_progress_panel,
            textvariable=self.commitment_progress_var,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=ui_font(11, "bold"),
        ).pack(anchor="w", pady=(6, 7))
        self.commitment_progress_bar = ttk.Progressbar(
            self.commitment_progress_panel,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="Goal.Horizontal.TProgressbar",
        )
        self.commitment_progress_bar.pack(fill="x", pady=(0, 8))
        self.conditions_frame = tk.Frame(
            self.commitment_progress_panel, bg=COLORS["panel_alt"]
        )
        self.conditions_frame.pack(fill="x")
        self.mark_done_button = tk.Button(
            self.commitment_progress_panel,
            text="✓ DONE :)",
            command=self.mark_done,
            bg=COLORS["accent"],
            fg=COLORS["accent_text"],
            activebackground=COLORS["accent_hover"],
            activeforeground=COLORS["accent_text"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(11, "bold"),
            padx=16,
            pady=11,
        )
        self.goal_panel = tk.Frame(detail_panel, bg=COLORS["panel"])
        self.goal_panel.pack(fill="x", pady=(0, 18))
        goal_header = tk.Frame(self.goal_panel, bg=COLORS["panel"])
        goal_header.pack(fill="x")
        tk.Label(
            goal_header,
            text="GOAL",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(10),
        ).pack(side="left")
        goal_actions = tk.Frame(goal_header, bg=COLORS["panel"])
        goal_actions.pack(side="right")
        self.revise_goal_button = tk.Button(
            goal_actions,
            text="Revise Goal",
            command=self.open_revise_goal,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["accent"],
            disabledforeground=COLORS["muted"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=4,
            pady=0,
        )
        self.revise_goal_button.pack(side="left", padx=(0, 8))
        self.goal_action_button = tk.Button(
            goal_actions,
            textvariable=self.goal_action_var,
            command=self.open_link_goal,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["accent"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=4,
            pady=0,
        )
        self.goal_action_button.pack(side="left")
        tk.Label(
            self.goal_panel,
            textvariable=self.linked_goal_var,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(11),
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self.dependency_panel = tk.Frame(detail_panel, bg=COLORS["panel"])
        self.dependency_panel.pack(fill="x", pady=(0, 18))
        dependency_header = tk.Frame(self.dependency_panel, bg=COLORS["panel"])
        dependency_header.pack(fill="x")
        tk.Label(
            dependency_header,
            text="DEPENDENCIES",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(10),
        ).pack(side="left")
        self.dependency_action_button = tk.Button(
            dependency_header,
            text="+ Link",
            command=self.open_add_dependency,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["accent"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=4,
            pady=0,
        )
        self.dependency_action_button.pack(side="right")
        self.dependencies_frame = tk.Frame(
            self.dependency_panel, bg=COLORS["panel"]
        )
        self.dependencies_frame.pack(fill="x", pady=(6, 0))

        history_panel = tk.Frame(
            detail_panel,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        self.history_panel = history_panel
        history_panel.pack(fill="x")
        history_label = tk.Label(
            history_panel,
            text="INFORMATION & HISTORY",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=ui_font(8, "bold"),
        )
        history_label.pack(anchor="w", pady=(0, 8))
        history_content = tk.Frame(history_panel, bg=COLORS["panel_alt"])
        history_content.pack(fill="both", expand=True)
        self.detail_text = tk.Text(
            history_content,
            width=42,
            height=12,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=ui_font(11),
            spacing1=3,
            spacing3=8,
            padx=0,
            pady=0,
        )
        history_scrollbar = ttk.Scrollbar(
            history_content,
            orient="vertical",
            command=self.detail_text.yview,
            style="Mountain.Vertical.TScrollbar",
        )
        self.detail_text.configure(yscrollcommand=history_scrollbar.set)
        history_scrollbar.pack(side="right", fill="y")
        self.detail_text.pack(side="left", fill="both", expand=True)
        self.detail_text.configure(state="disabled")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.detail_text.bind(sequence, self._on_history_area_mousewheel)
            history_scrollbar.bind(sequence, self._on_history_area_mousewheel)
        for widget in (
            history_panel,
            history_label,
            history_content,
            self.detail_text,
        ):
            widget.bind("<Button-1>", self._toggle_history_scroll, add="+")
        history_scrollbar.bind(
            "<Button-1>", self._activate_history_scroll, add="+"
        )
        self.root.bind_all(
            "<Button-1>", self._update_history_scroll_selection, add="+"
        )

        commitment_actions = tk.Frame(detail_panel, bg=COLORS["panel"])
        commitment_actions.pack(fill="x", pady=(12, 0))
        self.triage_commitment_button = tk.Button(
            commitment_actions,
            text="Triage commitment",
            command=self.triage_selected_commitment,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["text"],
            disabledforeground=COLORS["border"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=8,
            pady=4,
        )
        self.triage_commitment_button.pack(side="left")
        self.delete_commitment_button = tk.Button(
            commitment_actions,
            text="Delete commitment",
            command=self.delete_selected_commitment,
            bg=COLORS["panel"],
            fg=COLORS["overdue"],
            activebackground=COLORS["danger_hover"],
            activeforeground=COLORS["overdue"],
            disabledforeground=COLORS["muted"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=8,
            pady=4,
        )
        self.delete_commitment_button.pack(side="right")
        self.archive_commitment_button = tk.Button(
            commitment_actions,
            textvariable=self.archive_action_var,
            command=self.archive_selected_commitment,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            activebackground=COLORS["panel_alt"],
            activeforeground=COLORS["accent"],
            disabledforeground=COLORS["border"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=8,
            pady=4,
        )
        self.archive_commitment_button.pack(side="right", padx=(0, 10))

        footer = tk.Label(
            self.root,
            text="N new commitment   ·   C check in   ·   D done   ·   R refresh   ·   F11 fullscreen",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=ui_font(9),
        )
        footer.pack(pady=(0, 10))

    def _button(
        self, parent: tk.Widget, text: str, command, accent: bool = False
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent"] if accent else COLORS["panel_alt"],
            fg=COLORS["accent_text"] if accent else COLORS["text"],
            activebackground=(
                COLORS["accent_hover"] if accent else COLORS["panel_hover"]
            ),
            activeforeground=COLORS["accent_text"] if accent else COLORS["text"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(10, "bold"),
            padx=14,
            pady=8,
        )

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", lambda _event: self.root.attributes("-fullscreen", False))
        self.root.bind("<Control-q>", lambda _event: self.root.destroy())
        self.root.bind("<n>", lambda _event: self.open_add_commitment())
        self.root.bind("<c>", lambda _event: self.open_check_in())
        self.root.bind("<d>", lambda _event: self.mark_done())
        self.root.bind("<r>", lambda _event: self.refresh())

    def _fit_initial_layout(self) -> None:
        """Choose a centered default size for the overview and detail panes."""
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        column_width = sum(
            self.tree.column(column)["width"]
            for column in ("state", "title", "due_in")
        )
        list_width = column_width + 66
        detail_width = max(440, self.detail_panel.winfo_reqwidth())
        outer_spacing = 28 * 2 + 8
        desired_width = list_width + detail_width + outer_spacing

        usable_width = max(1180, screen_width - 120)
        usable_height = max(720, screen_height - 120)
        window_width = min(max(1600, desired_width), usable_width)
        window_height = min(1000, usable_height)
        x_position = max(0, (screen_width - window_width) // 2)
        y_position = max(0, (screen_height - window_height) // 2)
        self.root.geometry(
            f"{window_width}x{window_height}+{x_position}+{y_position}"
        )
        self._initial_list_width = list_width
        self._initial_detail_width = detail_width
        self.root.after_idle(self._place_initial_sash)

    def _place_initial_sash(self) -> None:
        """Position the divider after Windows has mapped the resized window."""
        self.root.update_idletasks()
        available_content = self.content.winfo_width()
        minimum_list_width = 480
        minimum_detail_width = 360
        sash_position = min(
            self._initial_list_width,
            max(
                minimum_list_width,
                available_content
                - max(self._initial_detail_width, minimum_detail_width)
                - 8,
            ),
        )
        self.content.sash_place(0, sash_position, 1)

    def _schedule_pane_fit(self, _event: tk.Event) -> None:
        """Keep both panes useful when a tiling compositor resizes the window."""
        if self._pane_resize_pending:
            return
        self._pane_resize_pending = True
        self.root.after_idle(self._keep_detail_pane_visible)

    def _keep_detail_pane_visible(self) -> None:
        self._pane_resize_pending = False
        available_content = self.content.winfo_width()
        if available_content <= 1:
            return
        current_sash = self.content.sash_coord(0)[0]
        maximum_sash = max(480, available_content - 360 - 8)
        if current_sash > maximum_sash:
            self.content.sash_place(0, maximum_sash, 1)

    def _update_detail_scrollregion(self, _event: tk.Event) -> None:
        bounds = self.detail_canvas.bbox("all")
        if bounds:
            self.detail_canvas.configure(scrollregion=bounds)

    def _resize_detail_content(self, event: tk.Event) -> None:
        self.detail_canvas.itemconfigure(
            self.detail_canvas_window, width=max(1, event.width)
        )

    def _on_detail_mousewheel(self, event: tk.Event) -> str | None:
        canvas = self.detail_canvas
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        inside = (
            canvas.winfo_rootx()
            <= pointer_x
            < canvas.winfo_rootx() + canvas.winfo_width()
            and canvas.winfo_rooty()
            <= pointer_y
            < canvas.winfo_rooty() + canvas.winfo_height()
        )
        if not inside:
            return None
        if self._history_scroll_active and self._pointer_inside(self.history_panel):
            history_result = self._on_history_mousewheel(event)
            if history_result == "break":
                return history_result
        if getattr(event, "num", None) == 4:
            direction = -3
        elif getattr(event, "num", None) == 5:
            direction = 3
        else:
            delta = getattr(event, "delta", 0)
            direction = -1 if delta > 0 else 1
        canvas.yview_scroll(direction, "units")
        return "break"

    def _on_history_mousewheel(self, event: tk.Event) -> str | None:
        if not self._history_scroll_active:
            return None
        if getattr(event, "num", None) == 4:
            direction = -3
        elif getattr(event, "num", None) == 5:
            direction = 3
        else:
            delta = getattr(event, "delta", 0)
            direction = -1 if delta > 0 else 1

        first, last = self.detail_text.yview()
        at_boundary = (direction < 0 and first <= 0) or (direction > 0 and last >= 1)
        if not at_boundary:
            self.detail_text.yview_scroll(direction, "units")
        return "break"

    def _on_history_area_mousewheel(self, event: tk.Event) -> str:
        """Preempt Tk's Text/Scrollbar class bindings and choose one scroll owner."""
        if self._history_scroll_active:
            self._on_history_mousewheel(event)
        else:
            self._on_detail_mousewheel(event)
        return "break"

    def _pointer_inside(self, widget: tk.Widget) -> bool:
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        return (
            widget.winfo_rootx()
            <= pointer_x
            < widget.winfo_rootx() + widget.winfo_width()
            and widget.winfo_rooty()
            <= pointer_y
            < widget.winfo_rooty() + widget.winfo_height()
        )

    def _update_history_scroll_selection(self, _event: tk.Event) -> None:
        if not self._pointer_inside(self.history_panel):
            self._set_history_scroll_active(False)

    def _activate_history_scroll(self, _event: tk.Event) -> None:
        self._set_history_scroll_active(True)

    def _toggle_history_scroll(self, _event: tk.Event) -> None:
        self._set_history_scroll_active(not self._history_scroll_active)

    def _set_history_scroll_active(self, active: bool) -> None:
        if active == self._history_scroll_active:
            return
        self._history_scroll_active = active
        if hasattr(self, "history_panel"):
            border_color = COLORS["accent"] if active else COLORS["border"]
            self.history_panel.configure(
                highlightbackground=border_color,
                highlightcolor=border_color,
            )

    def _tick(self) -> None:
        current = now_local()
        self.clock_var.set(current.strftime("%A, %B %d · %I:%M:%S %p"))
        self._update_countdown()
        self._update_overview_countdowns(current)
        minute_key = current.strftime("%Y-%m-%d %H:%M")
        if (
            self._last_status_refresh_minute is not None
            and minute_key != self._last_status_refresh_minute
        ):
            self.refresh()
        self._last_status_refresh_minute = minute_key
        self.root.after(1000, self._tick)

    def _update_overview_countdowns(self, current: datetime) -> None:
        """Keep the compact Due In column live without rebuilding the table."""
        for item_id in self.tree.get_children():
            try:
                item = self.store.commitment(item_id)
            except AccountabilityError:
                continue
            self.tree.set(item_id, "due_in", format_due_in(item, current))

    def _update_countdown(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            self.countdown_var.set("—")
            self.countdown_label.configure(fg=COLORS["muted"])
            return
        try:
            item = self.store.commitment(item_id)
        except AccountabilityError:
            return

        current = now_local()
        self.countdown_var.set(format_countdown(item, current))
        state = classify_commitment(item, current)
        due = parse_datetime(item.get("due_at"))
        if state == "completed":
            color = COLORS["completed"]
        elif state == "triaged":
            color = COLORS["triaged"]
        elif state == "overdue":
            color = COLORS["overdue"]
        elif due and (due - current).total_seconds() < 60 * 60:
            color = COLORS["due_soon"]
        elif due and (due - current).total_seconds() < 24 * 60 * 60:
            color = COLORS["due_soon"]
        else:
            color = COLORS["accent"]
        self.countdown_label.configure(fg=color)

    def toggle_fullscreen(self, _event=None) -> None:
        self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))

    def refresh(self, select_id: str | None = None) -> None:
        try:
            self.store.load()
            snapshot = self.store.snapshot()
        except AccountabilityError as exc:
            messagebox.showerror("Accountability data error", str(exc), parent=self.root)
            return

        for key, value in snapshot["counts"].items():
            self.summary_vars[key].set(str(value))

        previous = select_id or self.selected_id()
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        current_view = self.current_filter.get()
        all_items = self.store.commitments(include_closed=True)
        if current_view == "Archived":
            items = [
                item
                for item in self.store.commitments(
                    include_closed=True, include_archived=True
                )
                if item.get("archived_at")
            ]
        else:
            items = all_items if current_view == "All" else self.store.commitments()
        if current_view == "Overdue":
            items = [item for item in items if item["display_status"] == "overdue"]
        elif current_view == "Check-ins":
            items = [item for item in items if item["display_status"] == "check_in_due"]

        for item in items:
            state = item["display_status"]
            self.tree.insert(
                "",
                "end",
                iid=item["id"],
                values=(
                    state.replace("_", " ").upper(),
                    item["title"],
                    format_due_in(item),
                ),
                tags=(state,),
            )

        if previous and self.tree.exists(previous):
            self._set_tree_selection(previous)
        elif items:
            self._set_tree_selection(items[0]["id"])
        else:
            self._selected_item_id = None
            self.show_selected_detail()

    def _on_tree_selection(self, _event=None) -> None:
        native_selection = self.tree.selection()
        if not native_selection:
            return
        item_id = native_selection[0]
        self.tree.selection_remove(*native_selection)
        self._set_tree_selection(item_id)

    def _set_tree_selection(self, item_id: str) -> None:
        self._set_history_scroll_active(False)
        self._selected_item_id = item_id
        for item_id in self.tree.get_children():
            marker = self.selection_marker if item_id == self._selected_item_id else ""
            self.tree.item(item_id, image=marker)
        self.tree.focus(self._selected_item_id)
        self.tree.see(self._selected_item_id)
        self.show_selected_detail()
        self.root.after_idle(lambda: self.detail_canvas.yview_moveto(0))

    def _move_tree_selection(self, offset: int) -> str:
        items = list(self.tree.get_children())
        if not items:
            return "break"
        try:
            current = items.index(self.selected_id())
        except ValueError:
            current = 0
        target = items[max(0, min(len(items) - 1, current + offset))]
        self._set_tree_selection(target)
        return "break"

    def selected_id(self) -> str | None:
        if (
            hasattr(self, "tree")
            and self._selected_item_id
            and self.tree.exists(self._selected_item_id)
        ):
            return self._selected_item_id
        return None

    def show_selected_detail(self, _event=None) -> None:
        item_id = self.selected_id()
        if not item_id:
            self.detail_title.set("No commitments in this view")
            self.detail_meta.set("Create one, or change the view filter.")
            self.linked_goal_var.set("No linked goal")
            self.goal_action_var.set("Link goal")
            self.check_in_button.configure(state="disabled", cursor="arrow")
            self.revise_goal_button.configure(state="disabled", cursor="arrow")
            self.goal_action_button.configure(state="disabled", cursor="arrow")
            self.triage_commitment_button.configure(state="disabled", cursor="arrow")
            self.archive_commitment_button.configure(state="disabled", cursor="arrow")
            self.archive_action_var.set("Archive commitment")
            self.delete_commitment_button.configure(state="disabled", cursor="arrow")
            self.countdown_var.set("—")
            self._render_commitment_progress(None)
            self._render_dependencies(None)
            self._set_detail("")
            return
        try:
            item = self.store.commitment(item_id)
        except AccountabilityError:
            return
        goal = self.store.goal(item.get("goal_id"))
        self._render_commitment_progress(item)
        self._render_dependencies(item)
        self.linked_goal_var.set(goal["title"] if goal else "No linked goal")
        self.goal_action_var.set("Change goal" if goal else "Link goal")
        is_open = item["status"] in {"planned", "in_progress"}
        is_archived = bool(item.get("archived_at"))
        self.check_in_button.configure(
            state="normal" if is_open and not is_archived else "disabled",
            cursor="hand2" if is_open and not is_archived else "arrow",
        )
        self.revise_goal_button.configure(
            state="normal" if goal else "disabled",
            cursor="hand2" if goal else "arrow",
        )
        self.goal_action_button.configure(state="normal", cursor="hand2")
        self.triage_commitment_button.configure(
            state="normal" if is_open and not is_archived else "disabled",
            cursor="hand2" if is_open and not is_archived else "arrow",
        )
        self.archive_action_var.set(
            "Restore from archive" if is_archived else "Archive commitment"
        )
        can_archive = is_archived or item["status"] in {"completed", "triaged"}
        self.archive_commitment_button.configure(
            state="normal" if can_archive else "disabled",
            cursor="hand2" if can_archive else "arrow",
        )
        self.delete_commitment_button.configure(state="normal", cursor="hand2")
        self.detail_title.set(item["title"])
        self.detail_meta.set(
            f"{item['status'].replace('_', ' ').upper()}  ·  "
            f"{item['priority'].upper()} PRIORITY"
        )
        self._update_countdown()
        parts = [
            f"DUE\n{format_when(item['due_at'])}",
            f"NEXT CHECK-IN\n{format_when(item.get('check_in_at'))}",
        ]
        if item.get("notes"):
            parts.append(f"NOTES\n{item['notes']}")
        if goal:
            revisions = self.store.goal_revisions_for(goal["id"])
            if revisions:
                history = []
                labels = {
                    "title": "Title",
                    "why": "Why statement",
                    "target_date": "Target date",
                    "status": "Status",
                }
                for revision in revisions[:5]:
                    changes = []
                    for field, change in revision["changes"].items():
                        if field == "why":
                            changes.append("Why statement revised")
                        else:
                            before = change["from"] or "—"
                            after = change["to"] or "—"
                            changes.append(
                                f"{labels.get(field, field.title())}: {before} → {after}"
                            )
                    history.append(
                        f"{format_when(revision['revised_at'])}\n"
                        f"{revision['reason']}\n"
                        + "\n".join(changes)
                    )
                parts.append("GOAL REVISION HISTORY\n" + "\n\n".join(history))
        check_ins = self.store.check_ins_for(item_id)
        if check_ins:
            history = []
            for entry in check_ins[:5]:
                detail = entry.get("note") or "No note"
                if entry.get("next_action"):
                    detail += f"\nNext: {entry['next_action']}"
                history.append(
                    f"{format_when(entry['recorded_at'])} · "
                    f"{entry['state'].replace('_', ' ')}\n{detail}"
                )
            parts.append("RECENT CHECK-INS\n" + "\n\n".join(history))
        self._set_detail("\n\n".join(parts))

    def _render_commitment_progress(self, commitment: dict | None) -> None:
        for child in self.conditions_frame.winfo_children():
            child.destroy()
        self._condition_vars.clear()
        if commitment is None:
            self.mark_done_button.pack_forget()
            self.commitment_progress_var.set("NO COMMITMENT SELECTED")
            self.commitment_progress_bar.configure(value=0)
            self.add_condition_button.configure(state="disabled", cursor="arrow")
            tk.Label(
                self.conditions_frame,
                text="Select a commitment to track its subtasks.",
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=ui_font(9),
                wraplength=350,
                justify="left",
            ).pack(anchor="w")
            return

        self.add_condition_button.configure(state="normal", cursor="hand2")
        progress = self.store.commitment_progress(commitment["id"])
        if progress["total"]:
            label = f"{progress['completed']} OF {progress['total']} COMPLETE"
            if progress["all_met"]:
                label += " · ALL CONDITIONS MET"
        else:
            label = "NO WIN CONDITIONS YET"
        self.commitment_progress_var.set(label)
        self.commitment_progress_bar.configure(value=progress["ratio"] * 100)
        if progress["all_met"] and commitment["status"] in {"planned", "in_progress"}:
            if not self.mark_done_button.winfo_manager():
                self.mark_done_button.pack(fill="x", pady=(14, 0))
        else:
            self.mark_done_button.pack_forget()

        if not commitment["win_conditions"]:
            tk.Label(
                self.conditions_frame,
                text="Add observable subtasks that would complete this commitment.",
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                font=ui_font(9),
                wraplength=350,
                justify="left",
            ).pack(anchor="w")
            return

        selected_item = self.selected_id()
        for condition in commitment["win_conditions"]:
            variable = tk.BooleanVar(value=condition["completed"])
            self._condition_vars.append(variable)
            condition_row = tk.Frame(
                self.conditions_frame, bg=COLORS["panel_alt"]
            )
            condition_row.pack(fill="x", anchor="w", pady=2)
            toggle = lambda _event=None, commitment_id=commitment["id"], condition_id=condition["id"], value=variable, item_id=selected_item: self._toggle_win_condition_from_click(
                commitment_id, condition_id, value, item_id
            )
            indicator = tk.Canvas(
                condition_row,
                width=16,
                height=16,
                bg=COLORS["panel_alt"],
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            indicator.pack(side="left", padx=(0, 7))
            checked = condition["completed"]
            box = indicator.create_rectangle(
                2,
                2,
                14,
                14,
                fill=COLORS["completed"] if checked else COLORS["trough"],
                outline=COLORS["completed"] if checked else COLORS["border"],
                width=1,
            )
            if checked:
                indicator.create_line(
                    4,
                    8,
                    7,
                    11,
                    12,
                    5,
                    fill=COLORS["accent_text"],
                    width=2,
                    capstyle="round",
                    joinstyle="round",
                )
            indicator.bind("<Button-1>", toggle)
            indicator.bind(
                "<Enter>",
                lambda _event, canvas=indicator, item=box: canvas.itemconfigure(
                    item, outline=COLORS["accent"]
                ),
            )
            indicator.bind(
                "<Leave>",
                lambda _event, canvas=indicator, item=box, completed=checked: canvas.itemconfigure(
                    item,
                    outline=COLORS["completed"] if completed else COLORS["border"],
                ),
            )
            condition_label = tk.Label(
                condition_row,
                text=condition["text"],
                bg=COLORS["panel_alt"],
                fg=COLORS["completed"] if checked else COLORS["text"],
                anchor="w",
                justify="left",
                wraplength=295,
                font=ui_font(9),
                cursor="hand2",
            )
            condition_label.pack(side="left", fill="x", expand=True, anchor="w")
            condition_label.bind("<Button-1>", toggle)
            tk.Button(
                condition_row,
                text="×",
                command=lambda commitment_id=commitment["id"], condition_id=condition["id"], condition_text=condition["text"], item_id=selected_item: self._remove_win_condition(
                    commitment_id, condition_id, condition_text, item_id
                ),
                bg=COLORS["panel_alt"],
                fg=COLORS["muted"],
                activebackground=COLORS["danger_hover"],
                activeforeground=COLORS["overdue"],
                relief="flat",
                bd=0,
                cursor="hand2",
                font=ui_font(11, "bold"),
                width=2,
            ).pack(side="right")

    def _toggle_win_condition_from_click(
        self,
        commitment_id: str,
        condition_id: str,
        variable: tk.BooleanVar,
        item_id: str | None,
    ) -> str:
        variable.set(not variable.get())
        self._toggle_win_condition(commitment_id, condition_id, variable, item_id)
        return "break"

    def _render_dependencies(self, commitment: dict | None) -> None:
        for child in self.dependencies_frame.winfo_children():
            child.destroy()
        if commitment is None:
            self.dependency_action_button.configure(state="disabled", cursor="arrow")
            message = "Select a commitment to inspect its dependencies."
        else:
            self.dependency_action_button.configure(state="normal", cursor="hand2")
            dependencies = self.store.dependencies_for(commitment["id"])
            dependents = self.store.dependents_for(commitment["id"])

            def render_group(
                label: str, related_items: list[dict], removable: bool
            ) -> None:
                tk.Label(
                    self.dependencies_frame,
                    text=label,
                    bg=COLORS["panel"],
                    fg=COLORS["muted"],
                    font=ui_font(8, "bold"),
                    anchor="w",
                ).pack(anchor="w", pady=(3, 1))
                for dependency in related_items:
                    row = tk.Frame(self.dependencies_frame, bg=COLORS["panel"])
                    row.pack(fill="x", pady=1)
                    state = dependency["display_status"]
                    color = COLORS.get(state, COLORS["muted"])
                    tk.Label(
                        row,
                        text=dependency["dependency_kind"].upper(),
                        bg=COLORS["panel"],
                        fg=COLORS["muted"],
                        font=ui_font(8, "bold"),
                        width=9,
                        anchor="w",
                    ).pack(side="left")
                    tk.Label(
                        row,
                        text=f"{dependency['title']} · {state.replace('_', ' ')}",
                        bg=COLORS["panel"],
                        fg=color,
                        font=ui_font(9),
                        anchor="w",
                    ).pack(side="left", fill="x", expand=True)
                    if removable:
                        tk.Button(
                            row,
                            text="×",
                            command=lambda dependency_id=dependency["id"], commitment_id=commitment["id"]: self._remove_dependency(
                                commitment_id, dependency_id
                            ),
                            bg=COLORS["panel"],
                            fg=COLORS["muted"],
                            activebackground=COLORS["danger_hover"],
                            activeforeground=COLORS["overdue"],
                            relief="flat",
                            bd=0,
                            cursor="hand2",
                            font=ui_font(11, "bold"),
                            width=2,
                        ).pack(side="right")

            if dependencies or dependents:
                if dependencies:
                    render_group("DEPENDS ON", dependencies, True)
                if dependents:
                    render_group("NEEDED BY", dependents, False)
                return
            message = "No dependency links."

        tk.Label(
            self.dependencies_frame,
            text=message,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=ui_font(9),
            anchor="w",
        ).pack(anchor="w")

    def _toggle_win_condition(
        self,
        commitment_id: str,
        condition_id: str,
        variable: tk.BooleanVar,
        item_id: str | None,
    ) -> None:
        try:
            self.store.set_win_condition(
                commitment_id, condition_id, variable.get()
            )
            self.refresh(item_id)
        except AccountabilityError as exc:
            messagebox.showerror("Could not update progress", str(exc), parent=self.root)
            self.refresh(item_id)

    def _remove_win_condition(
        self,
        commitment_id: str,
        condition_id: str,
        condition_text: str,
        item_id: str | None,
    ) -> None:
        confirmed = messagebox.askyesno(
            "Remove subtask",
            f"Remove this win condition?\n\n{condition_text}",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.store.remove_win_condition(commitment_id, condition_id)
            self.refresh(item_id)
        except AccountabilityError as exc:
            messagebox.showerror("Could not remove subtask", str(exc), parent=self.root)

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")
        self.detail_text.yview_moveto(0)

    def open_add_goal(self) -> None:
        dialog = GoalDialog(self.root, anchor=self.add_goal_button)
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                self.store.add_goal(**dialog.result)
                self.refresh()
            except AccountabilityError as exc:
                messagebox.showerror("Could not create goal", str(exc), parent=self.root)

    def open_add_commitment(self) -> None:
        dialog = CommitmentDialog(
            self.root, self.store.goals(), anchor=self.add_commitment_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                item = self.store.add_commitment(**dialog.result)
                self.current_filter.set("Open")
                self.refresh(item["id"])
            except AccountabilityError as exc:
                messagebox.showerror("Could not create commitment", str(exc), parent=self.root)

    def open_revise_goal(self) -> None:
        goals = self.store.goals()
        if not goals:
            messagebox.showinfo(
                "Revise goal", "Create a goal before revising one.", parent=self.root
            )
            return
        selected_goal_id = None
        item_id = self.selected_id()
        if item_id:
            selected_goal_id = self.store.commitment(item_id).get("goal_id")
        dialog = GoalRevisionDialog(
            self.root, goals, selected_goal_id, anchor=self.revise_goal_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                self.store.revise_goal(**dialog.result)
                self.refresh(item_id)
            except AccountabilityError as exc:
                messagebox.showerror("Could not revise goal", str(exc), parent=self.root)

    def open_link_goal(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo("Link goal", "Select a commitment first.", parent=self.root)
            return
        commitment = self.store.commitment(item_id)
        goals = self.store.goals()
        if not goals and not commitment.get("goal_id"):
            messagebox.showinfo(
                "Link goal",
                "Create a goal before linking this commitment.",
                parent=self.root,
            )
            return
        dialog = CommitmentGoalDialog(
            self.root, commitment, goals, anchor=self.goal_action_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result is not None:
            try:
                self.store.set_commitment_goal(
                    commitment["id"], dialog.result["goal_id"]
                )
                self.refresh(item_id)
            except AccountabilityError as exc:
                messagebox.showerror("Could not update goal link", str(exc), parent=self.root)

    def open_add_win_condition(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo(
                "Commitment progress", "Select a commitment first.", parent=self.root
            )
            return
        commitment = self.store.commitment(item_id)
        dialog = AddWinConditionDialog(
            self.root, commitment["title"], anchor=self.add_condition_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                self.store.add_win_condition(commitment["id"], dialog.result)
                self.refresh(item_id)
            except AccountabilityError as exc:
                messagebox.showerror(
                    "Could not add win condition", str(exc), parent=self.root
                )

    def open_add_dependency(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo(
                "Dependencies", "Select a commitment first.", parent=self.root
            )
            return
        commitment = self.store.commitment(item_id)
        linked_ids = {
            dependency["commitment_id"]
            for dependency in commitment["dependencies"]
        }
        candidates = [
            item
            for item in self.store.commitments(include_closed=True)
            if item["id"] != item_id and item["id"] not in linked_ids
        ]
        if not candidates:
            messagebox.showinfo(
                "Dependencies",
                "There are no other unlinked commitments available.",
                parent=self.root,
            )
            return
        dialog = DependencyDialog(
            self.root, commitment, candidates, anchor=self.dependency_action_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                self.store.add_dependency(commitment["id"], **dialog.result)
                self.refresh(item_id)
            except AccountabilityError as exc:
                messagebox.showerror(
                    "Could not link dependency", str(exc), parent=self.root
                )

    def _remove_dependency(self, commitment_id: str, dependency_id: str) -> None:
        dependency = self.store.commitment(dependency_id)
        confirmed = messagebox.askyesno(
            "Remove dependency",
            f"Remove dependency on {dependency['title']}?",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.store.remove_dependency(commitment_id, dependency_id)
            self.refresh(commitment_id)
        except AccountabilityError as exc:
            messagebox.showerror(
                "Could not remove dependency", str(exc), parent=self.root
            )

    def triage_selected_commitment(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            return
        commitment = self.store.commitment(item_id)
        confirmed = messagebox.askyesno(
            "Triage commitment",
            f"Close “{commitment['title']}” as triaged without completing it?",
            parent=self.root,
        )
        if not confirmed:
            return
        self._set_selected_status("triaged")

    def archive_selected_commitment(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            return
        commitment = self.store.commitment(item_id)
        try:
            if commitment.get("archived_at"):
                self.store.restore_commitment(item_id)
            else:
                self.store.archive_commitment(item_id)
            self._selected_item_id = None
            self.refresh()
        except AccountabilityError as exc:
            messagebox.showerror(
                "Could not update archive", str(exc), parent=self.root
            )

    def delete_selected_commitment(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            return
        commitment = self.store.commitment(item_id)
        confirmed = messagebox.askyesno(
            "Delete commitment",
            f"Permanently delete “{commitment['title']}”?\n\n"
            "Its check-ins and dependency links will also be removed. "
            "This cannot be undone.",
            icon="warning",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.store.delete_commitment(item_id)
            self._selected_item_id = None
            self.refresh()
        except AccountabilityError as exc:
            messagebox.showerror(
                "Could not delete commitment", str(exc), parent=self.root
            )

    def open_check_in(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo("Check in", "Select a commitment first.", parent=self.root)
            return
        item = self.store.commitment(item_id)
        dialog = CheckInDialog(
            self.root, item["title"], anchor=self.check_in_button
        )
        self.root.wait_window(dialog.window)
        if dialog.result:
            try:
                self.store.record_check_in(item_id, **dialog.result)
                self.refresh(item_id)
            except AccountabilityError as exc:
                messagebox.showerror("Could not record check-in", str(exc), parent=self.root)

    def mark_done(self) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo("Commitment", "Select a commitment first.", parent=self.root)
            return
        if not self.store.commitment_progress(item_id)["all_met"]:
            messagebox.showinfo(
                "Win conditions",
                "Complete every win condition before marking this commitment done.",
                parent=self.root,
            )
            return
        self._set_selected_status("completed")

    def reopen(self) -> None:
        self._set_selected_status("in_progress")

    def _set_selected_status(self, status: str) -> None:
        item_id = self.selected_id()
        if not item_id:
            messagebox.showinfo("Commitment", "Select a commitment first.", parent=self.root)
            return
        try:
            self.store.set_commitment_status(item_id, status)
            self.refresh(item_id)
        except AccountabilityError as exc:
            messagebox.showerror("Could not update commitment", str(exc), parent=self.root)


class DateTimePicker(tk.Frame):
    """Readonly date/time field backed by a dark calendar dialog."""

    def __init__(
        self,
        parent: tk.Widget,
        variable: tk.StringVar,
        optional: bool = False,
        include_time: bool = True,
    ):
        super().__init__(parent, bg=COLORS["panel"])
        self.variable = variable
        self.optional = optional
        self.include_time = include_time
        self.grid_columnconfigure(0, weight=1)
        self.display = tk.Entry(
            self,
            textvariable=variable,
            state="readonly",
            readonlybackground=COLORS["panel_alt"],
            fg=COLORS["text"],
            relief="flat",
            font=ui_font(11),
        )
        self.display.grid(row=0, column=0, sticky="ew", ipady=7)
        self.choose_button = tk.Button(
            self,
            text="Choose…",
            command=self.open_calendar,
            bg=COLORS["panel_hover"],
            fg=COLORS["text"],
            activebackground=COLORS["border"],
            activeforeground=COLORS["text"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=13,
            pady=8,
        )
        self.choose_button.grid(row=0, column=1, padx=(8, 0))

    def open_calendar(self) -> None:
        parent_window = self.winfo_toplevel()
        dialog = CalendarDialog(
            parent_window,
            initial_value=self.variable.get(),
            optional=self.optional,
            include_time=self.include_time,
            anchor=self.choose_button,
        )
        self.wait_window(dialog.window)
        if dialog.result is not None:
            self.variable.set(dialog.result)


class CalendarDialog:
    def __init__(
        self,
        parent: tk.Toplevel,
        initial_value: str = "",
        optional: bool = False,
        include_time: bool = True,
        anchor: tk.Widget | None = None,
    ):
        self.parent = parent
        self.optional = optional
        self.include_time = include_time
        self.result: str | None = None
        try:
            initial = datetime.strptime(
                initial_value,
                "%Y-%m-%d %H:%M" if include_time else "%Y-%m-%d",
            )
        except ValueError:
            initial = now_local().replace(second=0, microsecond=0)
        self.selected_date = initial.date()
        self.visible_year = initial.year
        self.visible_month = initial.month
        self.hour_var = tk.StringVar(value=f"{initial.hour:02}")
        self.minute_var = tk.StringVar(value=f"{initial.minute:02}")

        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("Choose date and time" if include_time else "Choose date")
        self.window.transient(parent)
        self.window.geometry(
            child_window_geometry(
                parent, 450, 510 if include_time else 415, anchor=anchor
            )
        )
        self.window.resizable(False, False)
        self.window.configure(bg=COLORS["panel"])
        apply_windows_window_theme(self.window)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Escape>", lambda _event: self.cancel())

        header = tk.Frame(self.window, bg=COLORS["panel"], padx=20, pady=18)
        header.pack(fill="x")
        self._nav_button(header, "‹", lambda: self.shift_month(-1)).pack(side="left")
        self.month_var = tk.StringVar()
        tk.Label(
            header,
            textvariable=self.month_var,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(15, "bold"),
        ).pack(side="left", expand=True)
        self._nav_button(header, "›", lambda: self.shift_month(1)).pack(side="right")

        self.calendar_frame = tk.Frame(
            self.window, bg=COLORS["panel"], padx=18, pady=4
        )
        self.calendar_frame.pack(fill="x")

        if include_time:
            time_panel = tk.Frame(self.window, bg=COLORS["panel"], padx=20, pady=16)
            time_panel.pack(fill="x")
            tk.Label(
                time_panel,
                text="TIME · 24 HOUR",
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=ui_font(9, "bold"),
            ).pack(anchor="w", pady=(0, 6))
            time_controls = tk.Frame(time_panel, bg=COLORS["panel"])
            time_controls.pack(anchor="w")
            hour_control = self._spinbox(
                time_controls,
                self.hour_var,
                tuple(f"{hour:02}" for hour in range(24)),
            )
            hour_control.pack(side="left")
            tk.Label(
                time_controls,
                text=":",
                bg=COLORS["panel"],
                fg=COLORS["text"],
                font=mono_font(18, "bold"),
            ).pack(side="left", padx=6)
            minute_control = self._spinbox(
                time_controls,
                self.minute_var,
                tuple(f"{minute:02}" for minute in range(60)),
            )
            minute_control.pack(side="left")
            self.hour_var.set(f"{initial.hour:02}")
            self.minute_var.set(f"{initial.minute:02}")

        actions = tk.Frame(self.window, bg=COLORS["panel"], padx=20, pady=14)
        actions.pack(fill="x", side="bottom")
        if optional:
            self._action_button(actions, "Clear", self.clear).pack(side="left")
        self._action_button(actions, "Cancel", self.cancel).pack(
            side="right", padx=(8, 0)
        )
        self._action_button(actions, "Apply", self.apply, accent=True).pack(side="right")
        self.render_month()
        self.window.deiconify()
        self.window.lift()
        self.window.grab_set()

    def _nav_button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            activebackground=COLORS["border"],
            activeforeground=COLORS["text"],
            relief="flat",
            bd=0,
            font=ui_font(16, "bold"),
            width=3,
            cursor="hand2",
        )

    def _spinbox(
        self, parent: tk.Widget, variable: tk.StringVar, values: tuple[str, ...]
    ) -> tk.Spinbox:
        return tk.Spinbox(
            parent,
            values=values,
            textvariable=variable,
            wrap=True,
            width=4,
            justify="center",
            state="readonly",
            readonlybackground=COLORS["panel_alt"],
            fg=COLORS["text"],
            buttonbackground=COLORS["panel_hover"],
            relief="flat",
            font=mono_font(13, "bold"),
        )

    def _action_button(
        self, parent: tk.Widget, text: str, command, accent: bool = False
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent"] if accent else COLORS["panel_alt"],
            fg=COLORS["accent_text"] if accent else COLORS["text"],
            activebackground=(
                COLORS["accent_hover"] if accent else COLORS["border"]
            ),
            activeforeground=COLORS["accent_text"] if accent else COLORS["text"],
            relief="flat",
            bd=0,
            font=ui_font(9, "bold"),
            padx=15,
            pady=8,
            cursor="hand2",
        )

    def render_month(self) -> None:
        for child in self.calendar_frame.winfo_children():
            child.destroy()
        self.month_var.set(f"{calendar.month_name[self.visible_month]} {self.visible_year}")
        for column, weekday in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")):
            self.calendar_frame.grid_columnconfigure(column, weight=1)
            tk.Label(
                self.calendar_frame,
                text=weekday,
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=ui_font(8, "bold"),
            ).grid(row=0, column=column, sticky="ew", pady=(0, 7))

        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            self.visible_year, self.visible_month
        )
        today = now_local().date()
        for row, week in enumerate(weeks, start=1):
            for column, day_number in enumerate(week):
                if day_number == 0:
                    tk.Label(
                        self.calendar_frame, text="", bg=COLORS["panel"]
                    ).grid(row=row, column=column, padx=3, pady=3, sticky="nsew")
                    continue
                day = date(self.visible_year, self.visible_month, day_number)
                selected = day == self.selected_date
                button = tk.Button(
                    self.calendar_frame,
                    text=str(day_number),
                    command=lambda chosen=day: self.select_date(chosen),
                    bg=COLORS["accent"] if selected else COLORS["panel_alt"],
                    fg=(
                        COLORS["accent_text"]
                        if selected
                        else COLORS["accent"]
                        if day == today
                        else COLORS["text"]
                    ),
                    activebackground=(
                        COLORS["accent_hover"] if selected else COLORS["border"]
                    ),
                    activeforeground=(
                        COLORS["accent_text"] if selected else COLORS["text"]
                    ),
                    relief="flat",
                    bd=0,
                    font=ui_font(10, "bold" if selected else "normal"),
                    cursor="hand2",
                    width=4,
                    pady=7,
                )
                button.grid(row=row, column=column, padx=3, pady=3, sticky="nsew")

    def select_date(self, selected: date) -> None:
        self.selected_date = selected
        self.render_month()

    def shift_month(self, offset: int) -> None:
        month_index = self.visible_year * 12 + self.visible_month - 1 + offset
        self.visible_year, zero_based_month = divmod(month_index, 12)
        self.visible_month = zero_based_month + 1
        self.render_month()

    def apply(self) -> None:
        self.result = self.selected_date.isoformat()
        if self.include_time:
            self.result += (
                f" {int(self.hour_var.get()):02}:{int(self.minute_var.get()):02}"
            )
        self.close()

    def clear(self) -> None:
        self.result = ""
        self.close()

    def cancel(self) -> None:
        self.result = None
        self.close()

    def close(self) -> None:
        self.window.destroy()
        if self.parent.winfo_exists():
            self.parent.grab_set()


class BaseDialog:
    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        width: int,
        height: int,
        anchor: tk.Widget | None = None,
    ):
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title(title)
        self.window.transient(parent)
        self.window.geometry(
            child_window_geometry(parent, width, height, anchor=anchor)
        )
        self.window.resizable(False, False)
        self.window.configure(bg=COLORS["panel"])
        apply_windows_window_theme(self.window)
        self.body = tk.Frame(self.window, bg=COLORS["panel"], padx=24, pady=20)
        self.body.pack(fill="both", expand=True)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.deiconify()
        self.window.lift()
        self.window.grab_set()

    def label(self, text: str, row: int) -> None:
        tk.Label(
            self.body,
            text=text,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=ui_font(9, "bold"),
        ).grid(row=row, column=0, sticky="w", pady=(8, 3))

    def entry(self, variable: tk.StringVar, row: int) -> tk.Entry:
        widget = tk.Entry(
            self.body,
            textvariable=variable,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            font=ui_font(11),
        )
        widget.grid(row=row, column=0, sticky="ew", ipady=7)
        return widget

    def text(self, row: int, height: int = 3) -> tk.Text:
        widget = tk.Text(
            self.body,
            height=height,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            wrap="word",
            font=ui_font(10),
        )
        widget.grid(row=row, column=0, sticky="ew")
        return widget

    def actions(self, row: int, save_text: str, command) -> None:
        frame = tk.Frame(self.body, bg=COLORS["panel"])
        frame.grid(row=row, column=0, sticky="e", pady=(18, 0))
        tk.Button(
            frame,
            text="Cancel",
            command=self.window.destroy,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="left", padx=5)
        tk.Button(
            frame,
            text=save_text,
            command=command,
            bg=COLORS["accent"],
            fg=COLORS["accent_text"],
            relief="flat",
            font=ui_font(9, "bold"),
            padx=14,
            pady=7,
        ).pack(side="left")


class GoalDialog(BaseDialog):
    def __init__(self, parent: tk.Tk, anchor: tk.Widget | None = None):
        super().__init__(parent, "Create goal", 520, 440, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        self.title_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.label("GOAL", 0)
        title_entry = self.entry(self.title_var, 1)
        self.label("WHY DOES THIS MATTER?", 2)
        self.why_text = self.text(3, height=6)
        self.label("TARGET DATE · OPTIONAL", 4)
        self.target_picker = DateTimePicker(
            self.body,
            self.target_var,
            optional=True,
            include_time=False,
        )
        self.target_picker.grid(row=5, column=0, sticky="ew")
        self.actions(6, "Create goal", self.save)
        title_entry.focus_set()

    def save(self) -> None:
        if not self.title_var.get().strip():
            messagebox.showwarning("Goal", "Give the goal a title.", parent=self.window)
            return
        self.result = {
            "title": self.title_var.get().strip(),
            "why": self.why_text.get("1.0", "end").strip(),
            "target_date": self.target_var.get().strip() or None,
        }
        self.window.destroy()


class GoalRevisionDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        goals: list[dict],
        selected_goal_id: str | None = None,
        anchor: tk.Widget | None = None,
    ):
        super().__init__(parent, "Revise goal", 620, 700, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        self.goals_by_choice = {
            f"{goal['title']}  [{goal['id'][-6:]}]": goal for goal in goals
        }
        initial_choice = next(
            (
                choice
                for choice, goal in self.goals_by_choice.items()
                if goal["id"] == selected_goal_id
            ),
            next(iter(self.goals_by_choice)),
        )
        self.goal_var = tk.StringVar(value=initial_choice)
        self.title_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self.label("GOAL TO REVISE", 0)
        goal_box = ttk.Combobox(
            self.body,
            textvariable=self.goal_var,
            values=tuple(self.goals_by_choice),
            state="readonly",
        )
        goal_box.grid(row=1, column=0, sticky="ew", ipady=5)
        goal_box.bind("<<ComboboxSelected>>", lambda _event: self.populate())
        self.label("REVISED TITLE", 2)
        self.entry(self.title_var, 3)
        self.label("WHY DOES THIS GOAL MATTER?", 4)
        self.why_text = self.text(5, height=5)
        self.label("TARGET DATE · OPTIONAL", 6)
        self.target_picker = DateTimePicker(
            self.body,
            self.target_var,
            optional=True,
            include_time=False,
        )
        self.target_picker.grid(row=7, column=0, sticky="ew")
        self.label("GOAL STATUS", 8)
        status_box = ttk.Combobox(
            self.body,
            textvariable=self.status_var,
            values=("active", "paused", "achieved"),
            state="readonly",
        )
        status_box.grid(row=9, column=0, sticky="ew", ipady=5)
        self.label("WHY ARE YOU REVISING IT? · REQUIRED", 10)
        self.reason_text = self.text(11, height=4)
        self.actions(12, "Record revision", self.save)
        self.populate()

    def populate(self) -> None:
        goal = self.goals_by_choice[self.goal_var.get()]
        self.title_var.set(goal["title"])
        self.target_var.set(goal.get("target_date") or "")
        self.status_var.set(goal.get("status", "active"))
        self.why_text.delete("1.0", "end")
        self.why_text.insert("1.0", goal.get("why", ""))
        self.reason_text.delete("1.0", "end")

    def save(self) -> None:
        reason = self.reason_text.get("1.0", "end").strip()
        if not self.title_var.get().strip():
            messagebox.showwarning("Revise goal", "A goal needs a title.", parent=self.window)
            return
        if not reason:
            messagebox.showwarning(
                "Revise goal",
                "Record why you are revising this goal.",
                parent=self.window,
            )
            return
        goal = self.goals_by_choice[self.goal_var.get()]
        self.result = {
            "goal_id": goal["id"],
            "title": self.title_var.get().strip(),
            "why": self.why_text.get("1.0", "end").strip(),
            "target_date": self.target_var.get().strip() or None,
            "status": self.status_var.get(),
            "reason": reason,
        }
        self.window.destroy()


class CommitmentGoalDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        commitment: dict,
        goals: list[dict],
        anchor: tk.Widget | None = None,
    ):
        super().__init__(
            parent, "Link commitment to goal", 560, 300, anchor=anchor
        )
        self.body.grid_columnconfigure(0, weight=1)
        self.choice_to_id: dict[str, str | None] = {"No linked goal": None}
        for goal in goals:
            choice = f"{goal['title']}  [{goal['id'][-6:]}]"
            self.choice_to_id[choice] = goal["id"]
        current_choice = next(
            (
                choice
                for choice, goal_id in self.choice_to_id.items()
                if goal_id == commitment.get("goal_id")
            ),
            "No linked goal",
        )
        self.goal_var = tk.StringVar(value=current_choice)
        tk.Label(
            self.body,
            text=commitment["title"],
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(15, "bold"),
            wraplength=500,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.label("GOAL · LONG-RANGE OBJECTIVE OR METACATEGORY", 1)
        goal_box = ttk.Combobox(
            self.body,
            textvariable=self.goal_var,
            values=tuple(self.choice_to_id),
            state="readonly",
        )
        goal_box.grid(row=2, column=0, sticky="ew", ipady=6)
        tk.Label(
            self.body,
            text="You can link, change, or remove the goal without changing the commitment or its subtasks.",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=ui_font(9),
            wraplength=500,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.actions(4, "Update link", self.save)

    def save(self) -> None:
        self.result = {"goal_id": self.choice_to_id[self.goal_var.get()]}
        self.window.destroy()


class DependencyDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        commitment: dict,
        candidates: list[dict],
        anchor: tk.Widget | None = None,
    ):
        super().__init__(parent, "Link dependency", 570, 350, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        self.choice_to_id = {
            f"{item['title']}  [{item['id'][-6:]}]": item["id"]
            for item in candidates
        }
        self.dependency_var = tk.StringVar(value=next(iter(self.choice_to_id)))
        self.kind_var = tk.StringVar(value="required")
        tk.Label(
            self.body,
            text=commitment["title"],
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(15, "bold"),
            wraplength=510,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.label("DEPENDS ON", 1)
        dependency_box = ttk.Combobox(
            self.body,
            textvariable=self.dependency_var,
            values=tuple(self.choice_to_id),
            state="readonly",
        )
        dependency_box.grid(row=2, column=0, sticky="ew", ipady=5)
        self.label("RELATIONSHIP", 3)
        kind_box = ttk.Combobox(
            self.body,
            textvariable=self.kind_var,
            values=("required", "helpful"),
            state="readonly",
        )
        kind_box.grid(row=4, column=0, sticky="ew", ipady=5)
        tk.Label(
            self.body,
            text=(
                "Required means it should happen first; helpful means it makes "
                "this commitment easier. Neither relationship blocks completion."
            ),
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=ui_font(9),
            wraplength=510,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(12, 0))
        self.actions(6, "Link dependency", self.save)

    def save(self) -> None:
        self.result = {
            "dependency_id": self.choice_to_id[self.dependency_var.get()],
            "kind": self.kind_var.get(),
        }
        self.window.destroy()


class AddWinConditionDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        commitment_title: str,
        anchor: tk.Widget | None = None,
    ):
        super().__init__(parent, "Add win condition", 540, 250, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        tk.Label(
            self.body,
            text=commitment_title,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=ui_font(14, "bold"),
            wraplength=480,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.label("WHAT OBSERVABLE SUBTASK OR RESULT COMPLETES THIS?", 1)
        self.condition_var = tk.StringVar()
        condition_entry = self.entry(self.condition_var, 2)
        self.actions(3, "Add condition", self.save)
        condition_entry.focus_set()
        condition_entry.bind("<Return>", lambda _event: self.save())

    def save(self) -> None:
        condition = self.condition_var.get().strip()
        if not condition:
            messagebox.showwarning(
                "Win condition",
                "Describe an observable result.",
                parent=self.window,
            )
            return
        self.result = condition
        self.window.destroy()


class WinConditionEditor(tk.Frame):
    """Compact multi-item editor used while creating a commitment."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent, bg=COLORS["panel"])
        self.items: list[str] = []
        self.pending_var = tk.StringVar()
        self.grid_columnconfigure(0, weight=1)
        entry = tk.Entry(
            self,
            textvariable=self.pending_var,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            font=ui_font(10),
        )
        entry.grid(row=0, column=0, sticky="ew", ipady=7)
        entry.bind("<Return>", self._add_from_event)
        tk.Button(
            self,
            text="+ Add subtask",
            command=self.add_pending,
            bg=COLORS["panel_hover"],
            fg=COLORS["accent"],
            activebackground=COLORS["border"],
            activeforeground=COLORS["accent"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(9, "bold"),
            padx=12,
            pady=8,
        ).grid(row=0, column=1, padx=(8, 0))
        self.listbox = tk.Listbox(
            self,
            height=4,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            selectbackground=COLORS["selection"],
            selectforeground=COLORS["text"],
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            font=ui_font(10),
        )
        self.listbox.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Button(
            self,
            text="Remove selected",
            command=self.remove_selected,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            activebackground=COLORS["panel"],
            activeforeground=COLORS["text"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=ui_font(8),
        ).grid(row=2, column=0, columnspan=2, sticky="e", pady=(3, 0))

    def _add_from_event(self, _event=None) -> str:
        self.add_pending()
        return "break"

    def add_pending(self) -> None:
        text = self.pending_var.get().strip()
        if not text:
            return
        if any(existing.casefold() == text.casefold() for existing in self.items):
            messagebox.showwarning(
                "Win condition",
                "That subtask is already listed.",
                parent=self.winfo_toplevel(),
            )
            return
        self.items.append(text)
        self.listbox.insert("end", f"☐  {text}")
        self.pending_var.set("")

    def remove_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.listbox.delete(index)
        del self.items[index]

    def values(self) -> list[str]:
        self.add_pending()
        return list(self.items)


class CommitmentDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        goals: list[dict],
        anchor: tk.Widget | None = None,
    ):
        super().__init__(parent, "Create commitment", 610, 700, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        self.goals = goals
        self.goal_lookup = {goal["title"]: goal["id"] for goal in goals}
        self.title_var = tk.StringVar()
        self.goal_var = tk.StringVar(value="No linked goal")
        tomorrow = now_local() + timedelta(days=1)
        self.due_var = tk.StringVar(value=tomorrow.strftime("%Y-%m-%d 17:00"))
        self.check_var = tk.StringVar(value=now_local().strftime("%Y-%m-%d 20:00"))
        self.priority_var = tk.StringVar(value="medium")

        self.label("COMMITMENT", 0)
        title_entry = self.entry(self.title_var, 1)
        self.label("LINKED GOAL", 2)
        goal_box = ttk.Combobox(
            self.body,
            textvariable=self.goal_var,
            values=("No linked goal", *self.goal_lookup.keys()),
            state="readonly",
        )
        goal_box.grid(row=3, column=0, sticky="ew", ipady=5)
        self.label("DUE", 4)
        self.due_picker = DateTimePicker(self.body, self.due_var)
        self.due_picker.grid(row=5, column=0, sticky="ew")
        self.label("NEXT CHECK-IN · OPTIONAL", 6)
        self.check_picker = DateTimePicker(
            self.body, self.check_var, optional=True
        )
        self.check_picker.grid(row=7, column=0, sticky="ew")
        self.label("PRIORITY", 8)
        priority_box = ttk.Combobox(
            self.body,
            textvariable=self.priority_var,
            values=("low", "medium", "high"),
            state="readonly",
        )
        priority_box.grid(row=9, column=0, sticky="ew", ipady=5)
        self.label("WIN CONDITIONS · BREAK THIS INTO OBSERVABLE SUBTASKS", 10)
        self.win_condition_editor = WinConditionEditor(self.body)
        self.win_condition_editor.grid(row=11, column=0, sticky="ew")
        self.label("NOTES · OPTIONAL", 12)
        self.notes_text = self.text(13)
        self.actions(14, "Make commitment", self.save)
        title_entry.focus_set()

    def save(self) -> None:
        if not self.title_var.get().strip():
            messagebox.showwarning(
                "Commitment", "Describe the commitment.", parent=self.window
            )
            return
        win_conditions = self.win_condition_editor.values()
        if not win_conditions:
            messagebox.showwarning(
                "Commitment",
                "Add at least one observable subtask or win condition.",
                parent=self.window,
            )
            return
        self.result = {
            "title": self.title_var.get().strip(),
            "goal_id": self.goal_lookup.get(self.goal_var.get()),
            "due_at": self.due_var.get().strip(),
            "check_in_at": self.check_var.get().strip() or None,
            "priority": self.priority_var.get(),
            "win_conditions": win_conditions,
            "notes": self.notes_text.get("1.0", "end").strip(),
        }
        self.window.destroy()


class CheckInDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Tk,
        commitment_title: str,
        anchor: tk.Widget | None = None,
    ):
        super().__init__(parent, "Progress check-in", 590, 600, anchor=anchor)
        self.body.grid_columnconfigure(0, weight=1)
        self.state_var = tk.StringVar(value="on_track")
        self.next_check_var = tk.StringVar(
            value=(now_local() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        )
        tk.Label(
            self.body,
            text=commitment_title,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            wraplength=520,
            justify="left",
            font=ui_font(16, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.label("HONEST STATE", 1)
        state_box = ttk.Combobox(
            self.body,
            textvariable=self.state_var,
            values=("on_track", "at_risk", "blocked", "done"),
            state="readonly",
        )
        state_box.grid(row=2, column=0, sticky="ew", ipady=5)
        self.label("WHAT HAPPENED?", 3)
        self.note_text = self.text(4, height=5)
        self.label("NEXT VISIBLE ACTION", 5)
        self.action_text = self.text(6, height=3)
        self.label("NEXT CHECK-IN · OPTIONAL", 7)
        self.next_check_picker = DateTimePicker(
            self.body, self.next_check_var, optional=True
        )
        self.next_check_picker.grid(row=8, column=0, sticky="ew")
        self.actions(9, "Record check-in", self.save)
        self.note_text.focus_set()

    def save(self) -> None:
        self.result = {
            "state": self.state_var.get(),
            "note": self.note_text.get("1.0", "end").strip(),
            "next_action": self.action_text.get("1.0", "end").strip(),
            "next_check_in_at": self.next_check_var.get().strip() or None,
        }
        self.window.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Open the accountability dashboard.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Accountability JSON file to display",
    )
    parser.add_argument(
        "--title", default=WINDOW_TITLE, help="Window title to use for this dashboard"
    )
    args = parser.parse_args(argv)
    root = tk.Tk()
    try:
        AccountabilityApp(root, args.data, window_title=args.title)
    except AccountabilityError as exc:
        root.withdraw()
        messagebox.showerror("Momentum Pact", str(exc))
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
