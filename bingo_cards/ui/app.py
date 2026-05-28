from pathlib import Path
import os
import json
import re
import threading
from urllib.parse import urlparse
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

from bingo_cards.config import (
    APP_STATE_PATH,
    CUSTOMIZE_UNDO_LIMIT,
    FREE_ICON_SIZE_DEFAULT,
    FREE_IMAGE_PATH,
    PREVIEW_REFRESH_DEBOUNCE_MS,
    SAVE_STATE_DEBOUNCE_MS,
    SPOTIFY_TEMP_PDF_DIR,
    SUPPORTED_GRID_SIZES,
)
from bingo_cards.grid.placement import build_default_grid_cells
from bingo_cards.music.names import canonical_music_name, song_identity_key
from bingo_cards.pdf import (
    detect_pdf_layout,
    extract_bingo_cards,
    extract_first_card_matrix,
    normalize_cell_text,
)
from bingo_cards.playlist import (
    PlaylistGenerationError,
    PlaylistGenerationOptions,
    PlaylistPdfResult,
    generate_playlist_pdf,
    match_cell_to_playlist_label,
    playlist_track_labels,
)
from bingo_cards.render import build_preview, get_placeholder_matrix, is_free_cell_text
from bingo_cards.ui.toolbar_icons import load_toolbar_icon
from bingo_cards.ui.widgets import HoverToolTip, IconToolbarButton, get_windows_work_area


class BingoDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Bingo Card Designer")
        self.geometry("1380x900")
        self.minsize(1200, 780)
        self.after(0, lambda: self.state("zoomed"))

        self.template_path: Path | None = None
        self.pdf_path: Path | None = None
        self.template_image: Image.Image | None = None
        self.pdf_layout: int | None = None
        self.output_dir: Path | None = None
        self.free_icon_path: Path | None = None
        self.preview_photo = None
        self.preview_base_image: Image.Image | None = None
        self.preview_image_id: int | None = None
        self.preview_zoom = 1.0
        self.preview_zoom_label_var = tk.StringVar(value="100%")
        self._pending_fit_zoom = False
        self._preview_h_scroll_visible = True
        self._preview_v_scroll_visible = True
        self.cached_pdf_cards: list[dict] | None = None
        self.playlist_tracks: list[dict] = []
        self.playlist_include_artist: bool = False
        self.music_name_overrides: dict[str, str] = {}
        self.tutorial_seen = False
        self._tutorial_tooltip: ctk.CTkToplevel | None = None
        self._tutorial_target_widget = None
        self._tutorial_target_restore: dict[str, object] | None = None
        self._tutorial_steps: list[dict] = []
        self._tutorial_step_index = 0
        self._tutorial_import_dialog: ctk.CTkToplevel | None = None
        self._tutorial_music_editor_dialog: ctk.CTkToplevel | None = None

        self.text_color_var = tk.StringVar(value="#000000")
        self.font_size_var = tk.IntVar(value=26)
        self.text_offset_x_var = tk.IntVar(value=0)
        self.text_offset_y_var = tk.IntVar(value=0)
        self.free_icon_size_var = tk.DoubleVar(value=FREE_ICON_SIZE_DEFAULT)
        self.grid_x_var = tk.IntVar(value=0)
        self.grid_y_var = tk.IntVar(value=0)
        self.grid_cell_width_var = tk.IntVar(value=120)
        self.grid_cell_height_var = tk.IntVar(value=120)
        self.show_grid_overlay_var = tk.BooleanVar(value=True)
        self.grid_settings_expanded = False
        self.text_settings_expanded = False
        self._loading_state = False
        self._customize_history_suppressed = False
        self._customize_undo_stack: list[dict] = []
        self._customize_redo_stack: list[dict] = []
        self._customize_active_action_key: str | None = None
        self._preview_refresh_after_id: str | None = None
        self._save_state_after_id: str | None = None
        self._cached_preview_matrix: list[list[str]] | None = None
        self._cached_preview_matrix_key: tuple | None = None
        self._pending_legacy_grid_offsets: tuple[int, int] | None = None
        self._pending_legacy_cell_adjustments: tuple[int, int] | None = None
        self._cached_free_image: Image.Image | None = None
        self._cached_free_image_path: Path | None = None
        self.spotify_playlist_url_var = tk.StringVar(value="")
        self.spotify_grid_size_var = tk.StringVar(value="5x5")
        self.spotify_card_count_var = tk.IntVar(value=20)
        self.spotify_include_artist_var = tk.BooleanVar(value=False)
        self.spotify_free_center_var = tk.BooleanVar(value=True)
        self.spotify_downloaded_pdf_path: Path | None = None

        self._build_layout()
        self._load_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(450, self._show_tutorial_if_needed)

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(self, fg_color="transparent", width=380)
        left_panel.grid(row=0, column=0, sticky="nsw", padx=(16, 8), pady=16)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(0, weight=1)

        controls = ctk.CTkScrollableFrame(left_panel, corner_radius=12, width=380)
        controls.grid(row=0, column=0, sticky="nsew")
        controls.grid_columnconfigure(0, weight=1)
        self.controls_scrollable = controls

        ctk.CTkLabel(
            controls,
            text="Bingo Card Designer",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        ctk.CTkLabel(
            controls,
            text="Source",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=0, padx=16, pady=(8, 6), sticky="w")

        self.select_template_button = ctk.CTkButton(
            controls,
            text="Select Template Image",
            command=self._select_template,
            height=36,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.select_template_button.grid(
            row=2, column=0, padx=16, pady=(0, 10), sticky="ew"
        )

        self.spotify_import_button = ctk.CTkButton(
            controls,
            text="Import from Spotify Playlist",
            command=self._open_spotify_import_dialog,
            height=36,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
        )
        self.spotify_import_button.grid(
            row=3, column=0, padx=16, pady=(0, 10), sticky="ew"
        )

        self.pdf_layout_label = ctk.CTkLabel(
            controls, text="Grid layout: -", anchor="w"
        )
        self.pdf_layout_label.grid(row=4, column=0, padx=16, pady=(0, 14), sticky="ew")
        self.edit_music_button = ctk.CTkButton(
            controls,
            text="Edit Music Names",
            command=self._open_music_name_editor,
            height=34,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            state="disabled",
        )
        self.edit_music_button.grid(row=5, column=0, padx=16, pady=(0, 12), sticky="ew")

        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=6, column=0, padx=16, pady=(4, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Customize",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=7, column=0, padx=16, pady=(0, 6), sticky="w")

        self.text_settings_toggle_button = ctk.CTkButton(
            controls,
            text="▶ Text Settings",
            command=self._toggle_text_settings,
            height=32,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        self.text_settings_toggle_button.grid(
            row=8, column=0, padx=16, pady=(0, 10), sticky="ew"
        )

        self.text_settings_frame = ctk.CTkFrame(controls, corner_radius=8)
        self.text_settings_frame.grid_columnconfigure(0, weight=1)

        color_row = ctk.CTkFrame(self.text_settings_frame, fg_color="transparent")
        color_row.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="ew")
        color_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(color_row, text="Text Color (#RRGGBB)").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.text_color_entry = ctk.CTkEntry(
            color_row, textvariable=self.text_color_var, width=110
        )
        self.text_color_entry.grid(row=0, column=1, padx=(0, 6), sticky="e")
        self.text_color_entry.bind(
            "<FocusIn>",
            lambda _event: self._stash_customize_undo("entry:text_color"),
        )
        ctk.CTkButton(
            color_row,
            text="Pick",
            width=60,
            command=self._pick_text_color,
        ).grid(row=0, column=2, sticky="e")

        self.color_swatch = ctk.CTkLabel(
            self.text_settings_frame,
            text="",
            height=18,
            corner_radius=6,
            fg_color=self.text_color_var.get(),
        )
        self.color_swatch.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

        self.font_size_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=2,
            label="Font Size",
            variable=self.font_size_var,
            minimum=10,
            maximum=64,
        )
        self.text_offset_x_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=3,
            label="Text Offset X",
            variable=self.text_offset_x_var,
            minimum=-120,
            maximum=120,
        )
        self.text_offset_y_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=4,
            label="Text Offset Y",
            variable=self.text_offset_y_var,
            minimum=-120,
            maximum=120,
        )
        self.free_icon_size_value_label = self._create_float_stepper_row(
            self.text_settings_frame,
            row=5,
            label="Free Icon Size",
            variable=self.free_icon_size_var,
            minimum=0.30,
            maximum=1.00,
            step=0.05,
            decimals=2,
        )
        free_icon_row = ctk.CTkFrame(self.text_settings_frame, fg_color="transparent")
        free_icon_row.grid(row=6, column=0, padx=10, pady=(0, 10), sticky="ew")
        free_icon_row.grid_columnconfigure(0, weight=1)
        self.free_icon_path_label = ctk.CTkLabel(
            free_icon_row,
            text=self._format_free_icon_label(),
            anchor="w",
            text_color="#9ca3af",
        )
        self.free_icon_path_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkButton(
            free_icon_row,
            text="Select FREE Icon",
            width=140,
            command=self._select_free_icon,
            fg_color="#6b7280",
            hover_color="#4b5563",
        ).grid(row=0, column=1, sticky="e")

        self.grid_settings_toggle_button = ctk.CTkButton(
            controls,
            text="▶ Grid Settings",
            command=self._toggle_grid_settings,
            height=32,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        self.grid_settings_toggle_button.grid(
            row=10, column=0, padx=16, pady=(0, 12), sticky="ew"
        )

        self.grid_settings_frame = ctk.CTkFrame(controls, corner_radius=8)
        self.grid_settings_frame.grid_columnconfigure(0, weight=1)

        grid_overlay_row = ctk.CTkFrame(
            self.grid_settings_frame, fg_color="transparent"
        )
        grid_overlay_row.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="ew")
        grid_overlay_row.grid_columnconfigure(0, weight=1)
        grid_overlay_row.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(grid_overlay_row, text="Show Preview Grid").grid(
            row=0, column=0, sticky="w"
        )

        overlay_controls = ctk.CTkFrame(
            grid_overlay_row, fg_color="transparent", width=136, height=30
        )
        overlay_controls.grid(row=0, column=1, sticky="e")
        overlay_controls.grid_propagate(False)
        overlay_controls.grid_columnconfigure(0, weight=1)

        self.grid_overlay_switch = ctk.CTkSwitch(
            overlay_controls,
            text="",
            width=46,
            switch_width=36,
            variable=self.show_grid_overlay_var,
            command=self._on_grid_overlay_toggled,
        )
        self.grid_overlay_switch.grid(row=0, column=0, sticky="e")

        self.grid_x_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=1,
            label="Grid X",
            variable=self.grid_x_var,
            minimum=0,
            maximum=4096,
        )
        self.grid_y_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=2,
            label="Grid Y",
            variable=self.grid_y_var,
            minimum=0,
            maximum=4096,
        )
        self.grid_cell_width_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=3,
            label="Cell Width",
            variable=self.grid_cell_width_var,
            minimum=20,
            maximum=1024,
        )
        self.grid_cell_height_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=4,
            label="Cell Height",
            variable=self.grid_cell_height_var,
            minimum=20,
            maximum=1024,
        )
        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=12, column=0, padx=16, pady=(10, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Output",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=14, column=0, padx=16, pady=(0, 6), sticky="w")
        self.output_folder_button = ctk.CTkButton(
            controls,
            text=self._format_output_button_text(),
            command=self._select_output_folder,
            height=36,
            fg_color="#0891b2",
            hover_color="#0e7490",
        )
        self.output_folder_button.grid(
            row=15, column=0, padx=16, pady=(0, 10), sticky="ew"
        )
        ctk.CTkButton(
            controls,
            text="Open Generated Folder",
            command=self._open_output_folder,
            height=34,
            fg_color="#475569",
            hover_color="#334155",
        ).grid(row=16, column=0, padx=16, pady=(0, 12), sticky="ew")

        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=17, column=0, padx=16, pady=(2, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Run",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=18, column=0, padx=16, pady=(0, 6), sticky="w")
        self.generate_button = ctk.CTkButton(
            controls,
            text="Generate Cards",
            command=self._generate_cards,
            fg_color="#16a34a",
            hover_color="#15803d",
            height=38,
        )
        self.generate_button.grid(row=20, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.generate_progress = ctk.CTkProgressBar(controls)
        self.generate_progress.set(0)
        self.generate_progress.grid(row=21, column=0, padx=16, pady=(0, 4), sticky="ew")
        self.generate_status_label = ctk.CTkLabel(
            controls, text="Generation status: idle", anchor="w", text_color="#9ca3af"
        )
        self.generate_status_label.grid(
            row=22, column=0, padx=16, pady=(0, 16), sticky="ew"
        )
        self.tutorial_button = ctk.CTkButton(
            left_panel,
            text="Start Tutorial Tour",
            command=self._start_tutorial,
            height=34,
            fg_color="#4f46e5",
            hover_color="#4338ca",
        )
        self.tutorial_button.grid(row=1, column=0, padx=16, pady=(8, 0), sticky="ew")

        preview_frame = ctk.CTkFrame(self, corner_radius=12)
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)

        preview_header = ctk.CTkFrame(preview_frame, fg_color="transparent")
        preview_header.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="ew")
        preview_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview_header,
            text="Live Preview",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        preview_toolbar = ctk.CTkFrame(preview_header, fg_color="transparent")
        preview_toolbar.grid(row=0, column=1, sticky="e")

        icon_pixel_size = 24
        toolbar_button_size = 36

        undo_icon_on = load_toolbar_icon("undo", icon_pixel_size, enabled=True)
        undo_icon_off = load_toolbar_icon("undo", icon_pixel_size, enabled=False)
        redo_icon_on = load_toolbar_icon("redo", icon_pixel_size, enabled=True)
        redo_icon_off = load_toolbar_icon("redo", icon_pixel_size, enabled=False)

        self.undo_customize_button = IconToolbarButton(
            preview_toolbar,
            pil_image=undo_icon_on,
            pil_image_disabled=undo_icon_off,
            command=self._undo_customize,
            size=toolbar_button_size,
            state="disabled",
        )
        self.undo_customize_button.grid(row=0, column=0, padx=(0, 4))

        self.redo_customize_button = IconToolbarButton(
            preview_toolbar,
            pil_image=redo_icon_on,
            pil_image_disabled=redo_icon_off,
            command=self._redo_customize,
            size=toolbar_button_size,
            state="disabled",
        )
        self.redo_customize_button.grid(row=0, column=1, padx=(0, 4))

        self.reset_customize_button = IconToolbarButton(
            preview_toolbar,
            pil_image=load_toolbar_icon("reset", icon_pixel_size),
            command=self._reset_configs,
            size=toolbar_button_size,
            fg_color="#6b7280",
        )
        self.reset_customize_button.grid(row=0, column=2, padx=(0, 10))

        ctk.CTkFrame(
            preview_toolbar, width=1, height=toolbar_button_size - 6, fg_color="#6b7280"
        ).grid(row=0, column=3, padx=(0, 10))

        zoom_button_fg = "#2563eb"
        zoom_button_hover = "#1d4ed8"

        self.zoom_out_button = IconToolbarButton(
            preview_toolbar,
            pil_image=load_toolbar_icon("minus", icon_pixel_size),
            command=self._zoom_out,
            size=toolbar_button_size,
            fg_color=zoom_button_fg,
            hover_color=zoom_button_hover,
        )
        self.zoom_out_button.grid(row=0, column=4, padx=(0, 6))
        self.preview_zoom_label = ctk.CTkLabel(
            preview_toolbar,
            textvariable=self.preview_zoom_label_var,
            width=56,
            anchor="center",
        )
        self.preview_zoom_label.grid(row=0, column=5, padx=(0, 6))
        self.zoom_in_button = IconToolbarButton(
            preview_toolbar,
            pil_image=load_toolbar_icon("plus", icon_pixel_size),
            command=self._zoom_in,
            size=toolbar_button_size,
            fg_color=zoom_button_fg,
            hover_color=zoom_button_hover,
        )
        self.zoom_in_button.grid(row=0, column=6, padx=(0, 6))
        self.zoom_fit_button = IconToolbarButton(
            preview_toolbar,
            pil_image=load_toolbar_icon("fit", icon_pixel_size),
            command=self._zoom_reset,
            size=toolbar_button_size,
        )
        self.zoom_fit_button.grid(row=0, column=7)

        self._preview_tooltips = [
            HoverToolTip(self.undo_customize_button, "Undo customize change (Ctrl+Z)"),
            HoverToolTip(self.redo_customize_button, "Redo customize change (Ctrl+Y)"),
            HoverToolTip(
                self.reset_customize_button,
                "Reset text and grid settings to defaults",
            ),
            HoverToolTip(self.zoom_out_button, "Zoom out"),
            HoverToolTip(self.preview_zoom_label, "Preview zoom level"),
            HoverToolTip(self.zoom_in_button, "Zoom in"),
            HoverToolTip(self.zoom_fit_button, "Fit preview to window"),
        ]

        preview_viewport = ctk.CTkFrame(preview_frame, corner_radius=8)
        preview_viewport.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        preview_viewport.grid_rowconfigure(0, weight=1)
        preview_viewport.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_viewport,
            bg="#2b2b2b",
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_v_scroll = ctk.CTkScrollbar(
            preview_viewport, orientation="vertical", command=self.preview_canvas.yview
        )
        self.preview_v_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_h_scroll = ctk.CTkScrollbar(
            preview_viewport,
            orientation="horizontal",
            command=self.preview_canvas.xview,
        )
        self.preview_h_scroll.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.configure(
            xscrollcommand=self.preview_h_scroll.set,
            yscrollcommand=self.preview_v_scroll.set,
        )
        self.preview_canvas.bind("<Control-MouseWheel>", self._on_preview_ctrl_wheel)
        self.preview_canvas.bind("<MouseWheel>", self._on_preview_scroll)
        self.preview_canvas.bind("<Shift-MouseWheel>", self._on_preview_shift_scroll)
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_configure)
        self._show_preview_warning("Select a template image to start.")

        preview_refresh = lambda *_args: self._schedule_preview_refresh()
        self.text_color_var.trace_add("write", preview_refresh)
        self.font_size_var.trace_add("write", preview_refresh)
        self.text_offset_x_var.trace_add("write", preview_refresh)
        self.text_offset_y_var.trace_add("write", preview_refresh)
        self.free_icon_size_var.trace_add("write", preview_refresh)
        self.grid_x_var.trace_add("write", preview_refresh)
        self.grid_y_var.trace_add("write", preview_refresh)
        self.grid_cell_width_var.trace_add("write", preview_refresh)
        self.grid_cell_height_var.trace_add("write", preview_refresh)
        self.show_grid_overlay_var.trace_add("write", preview_refresh)

        self.bind_all("<Control-z>", self._on_customize_undo_shortcut)
        self.bind_all("<Control-Z>", self._on_customize_undo_shortcut)
        self.bind_all("<Control-y>", self._on_customize_redo_shortcut)
        self.bind_all("<Control-Y>", self._on_customize_redo_shortcut)
        self.bind_all("<Control-Shift-z>", self._on_customize_redo_shortcut)
        self.bind_all("<Control-Shift-Z>", self._on_customize_redo_shortcut)

    def _toggle_text_settings(self):
        self.text_settings_expanded = not self.text_settings_expanded
        if self.text_settings_expanded:
            self.text_settings_toggle_button.configure(text="▼ Text Settings")
            self.text_settings_frame.grid(
                row=9, column=0, padx=16, pady=(0, 12), sticky="ew"
            )
        else:
            self.text_settings_toggle_button.configure(text="▶ Text Settings")
            self.text_settings_frame.grid_forget()
        self._save_state()

    def _toggle_grid_settings(self):
        self.grid_settings_expanded = not self.grid_settings_expanded
        if self.grid_settings_expanded:
            self.grid_settings_toggle_button.configure(text="▼ Grid Settings")
            self.grid_settings_frame.grid(
                row=11, column=0, padx=16, pady=(0, 12), sticky="ew"
            )
        else:
            self.grid_settings_toggle_button.configure(text="▶ Grid Settings")
            self.grid_settings_frame.grid_forget()
        self._save_state()

    def _show_tutorial_if_needed(self):
        if not self.tutorial_seen:
            self._start_tutorial()

    def _start_tutorial(self):
        if self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists():
            self._tutorial_position_tooltip()
            self._tutorial_tooltip.lift()
            return

        self._tutorial_steps = [
            {
                "title": "Welcome to Bingo Card Designer",
                "body": (
                    "This tour highlights the main controls directly in the app. "
                    "Use Next/Back below and follow the highlighted element each step."
                ),
                "target": lambda: self.tutorial_button,
                "action": None,
            },
            {
                "title": "Step 1: Select a template image",
                "body": (
                    "Use 'Select Template Image' in Source. This imports the bingo card design where "
                    "text should be drawn. The app detects the template grid layout automatically."
                ),
                "target": lambda: self.select_template_button,
                "action": None,
            },
            {
                "title": "Step 2: Import from Spotify playlist",
                "body": (
                    "Click 'Import from Spotify Playlist'. This generates your bingo cards PDF automatically "
                    "and imports song values from it. "
                    "After import, the music-name editor becomes available."
                ),
                "target": lambda: self.spotify_import_button,
                "action": None,
            },
            {
                "title": "Step 3: Import dialog walkthrough",
                "body": (
                    "The import dialog is now open. Paste your Spotify playlist URL, choose card setup, "
                    "then click 'Generate and Import PDF'."
                ),
                "target": lambda: self._tutorial_import_dialog
                or self.spotify_import_button,
                "action": self._open_tutorial_import_dialog,
                "keep_import_dialog_open": True,
                "tooltip_placement": "below",
                "highlight_target": False,
            },
            {
                "title": "Step 4: Edit music names",
                "body": (
                    "Use 'Edit Music Names' to fix OCR inconsistencies or rename entries. "
                    "These overrides are saved and used in preview and final generated cards."
                ),
                "target": lambda: self.edit_music_button,
                "action": None,
            },
            {
                "title": "Step 5: Music editor dialog walkthrough",
                "body": (
                    "The music editor is now open. Each row shows the original song on the left "
                    "and your editable name on the right. Use Apply to save changes or Reset to undo."
                ),
                "target": lambda: self._tutorial_music_editor_dialog
                or self.edit_music_button,
                "action": self._open_tutorial_music_editor_dialog,
                "keep_music_editor_dialog_open": True,
                "tooltip_placement": "below",
                "highlight_target": False,
            },
            {
                "title": "Step 6: Adjust text settings",
                "body": (
                    "Open 'Text Settings' to control text color, font size, offsets, and FREE icon size. "
                    "All changes are visible immediately in Live Preview."
                ),
                "target": lambda: self.text_settings_toggle_button,
                "action": self._expand_text_settings,
            },
            {
                "title": "Step 7: Align the grid if needed",
                "body": (
                    "Open 'Grid Settings' only if text placement needs correction. "
                    "Use grid offsets and cell width/height adjust to align content to your template."
                ),
                "target": lambda: self.grid_settings_toggle_button,
                "action": self._expand_grid_settings,
            },
            {
                "title": "Step 8: Choose output and generate",
                "body": (
                    "Choose an output folder using the Output button. "
                    "This is where generated bingo cards will be saved."
                ),
                "target": lambda: self.output_folder_button,
                "action": None,
            },
            {
                "title": "Step 9: Generate cards",
                "body": (
                    "Press 'Generate Cards' to create your final PNG bingo cards. "
                    "When complete, use 'Open Generated Folder' to review exports."
                ),
                "target": lambda: self.generate_button,
                "action": None,
            },
        ]
        tooltip = ctk.CTkToplevel(self)
        tooltip.title("Tutorial")
        tooltip.geometry("420x240")
        tooltip.attributes("-topmost", True)
        tooltip.transient(self)
        tooltip.protocol("WM_DELETE_WINDOW", self._close_tutorial)
        tooltip.grid_columnconfigure(0, weight=1)
        tooltip.grid_rowconfigure(1, weight=1)
        self._tutorial_tooltip = tooltip

        self._tutorial_title_label = ctk.CTkLabel(
            tooltip,
            text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
            justify="left",
        )
        self._tutorial_title_label.grid(
            row=0, column=0, padx=14, pady=(12, 6), sticky="ew"
        )
        self._tutorial_body_label = ctk.CTkLabel(
            tooltip,
            text="",
            anchor="nw",
            justify="left",
            wraplength=390,
        )
        self._tutorial_body_label.grid(
            row=1, column=0, padx=14, pady=(0, 8), sticky="nsew"
        )

        footer = ctk.CTkFrame(tooltip, fg_color="transparent")
        footer.grid(row=2, column=0, padx=14, pady=(2, 12), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        self._tutorial_back_button = ctk.CTkButton(
            footer, text="Back", width=86, command=self._tutorial_prev
        )
        self._tutorial_back_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self._tutorial_progress_label = ctk.CTkLabel(
            footer, text="", text_color="#9ca3af", anchor="w"
        )
        self._tutorial_progress_label.grid(row=0, column=1, sticky="w")
        self._tutorial_next_button = ctk.CTkButton(
            footer,
            text="Next",
            width=96,
            command=self._tutorial_next,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self._tutorial_next_button.grid(row=0, column=2, padx=(8, 0), sticky="e")

        self._tutorial_step_index = 0
        self._render_tutorial_step()

    def _expand_text_settings(self):
        if not self.text_settings_expanded:
            self._toggle_text_settings()

    def _expand_grid_settings(self):
        if not self.grid_settings_expanded:
            self._toggle_grid_settings()

    def _open_tutorial_import_dialog(self):
        self._open_spotify_import_dialog(tutorial_mode=True)

    def _close_tutorial_import_dialog(self):
        if self._tutorial_import_dialog and self._tutorial_import_dialog.winfo_exists():
            self._tutorial_import_dialog.destroy()
        self._tutorial_import_dialog = None

    def _open_tutorial_music_editor_dialog(self):
        self._open_music_name_editor(tutorial_mode=True)

    def _close_tutorial_music_editor_dialog(self):
        if (
            self._tutorial_music_editor_dialog
            and self._tutorial_music_editor_dialog.winfo_exists()
        ):
            self._tutorial_music_editor_dialog.destroy()
        self._tutorial_music_editor_dialog = None

    def _tutorial_music_editor_sample_names(self) -> list[str]:
        return [
            "Example Song One",
            "Example Song Two",
            "Example Song Three",
        ]

    def _render_tutorial_step(self):
        if not self._tutorial_steps:
            return
        self._tutorial_step_index = max(
            0, min(self._tutorial_step_index, len(self._tutorial_steps) - 1)
        )
        current = self._tutorial_steps[self._tutorial_step_index]
        if not current.get("keep_import_dialog_open"):
            self._close_tutorial_import_dialog()
        if not current.get("keep_music_editor_dialog_open"):
            self._close_tutorial_music_editor_dialog()
        action = current.get("action")
        if callable(action):
            action()
        target_getter = current.get("target")
        target_widget = target_getter() if callable(target_getter) else None
        self._tutorial_ensure_widget_visible(target_widget)
        if current.get("highlight_target", True):
            self._tutorial_highlight_widget(target_widget)
        else:
            self._clear_tutorial_highlight()
        self._tutorial_title_label.configure(text=current["title"])
        self._tutorial_body_label.configure(text=current["body"])
        self._tutorial_progress_label.configure(
            text=f"Step {self._tutorial_step_index + 1} of {len(self._tutorial_steps)}"
        )
        self._tutorial_position_tooltip()
        if current.get("tooltip_placement") == "below":
            self.after(80, self._tutorial_position_tooltip)

        if self._tutorial_step_index >= len(self._tutorial_steps) - 1:
            self._tutorial_next_button.configure(text="Finish")
        else:
            self._tutorial_next_button.configure(text="Next")
        self._tutorial_back_button.configure(
            state="normal" if self._tutorial_step_index > 0 else "disabled"
        )

    def _tutorial_position_tooltip(self):
        if not (self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists()):
            return
        if not self._tutorial_steps:
            return
        current = self._tutorial_steps[
            max(0, min(self._tutorial_step_index, len(self._tutorial_steps) - 1))
        ]
        placement = current.get("tooltip_placement", "beside")
        target_getter = current.get("target")
        target = (
            target_getter() if callable(target_getter) else self._tutorial_target_widget
        )
        if not target or not target.winfo_exists():
            return
        self.update_idletasks()
        target.update_idletasks()
        self._tutorial_tooltip.update_idletasks()
        work_area = get_windows_work_area()
        if work_area:
            screen_x, screen_y, screen_right, screen_bottom = work_area
            screen_w = screen_right - screen_x
            screen_h = screen_bottom - screen_y
        else:
            screen_x = self.winfo_vrootx()
            screen_y = self.winfo_vrooty()
            screen_w = self.winfo_vrootwidth()
            screen_h = self.winfo_vrootheight()
        target_x = target.winfo_rootx()
        target_y = target.winfo_rooty()
        target_w = max(target.winfo_width(), target.winfo_reqwidth())
        target_h = max(target.winfo_height(), target.winfo_reqheight())
        tip_w = self._tutorial_tooltip.winfo_width()
        tip_h = self._tutorial_tooltip.winfo_height()
        gap = 14
        margin = 12

        if placement == "below":
            x = target_x + max(0, (target_w - tip_w) // 2)
            y = target_y + target_h + gap
            if y + tip_h > (screen_y + screen_h - margin):
                y = target_y - tip_h - gap
        else:
            x = target_x + target_w + gap
            y = target_y
            if x + tip_w > (screen_x + screen_w - margin):
                x = target_x - tip_w - gap
            if y + tip_h > (screen_y + screen_h - margin):
                y = target_y + target_h - tip_h

        max_x = (screen_x + screen_w) - tip_w - margin
        max_y = (screen_y + screen_h) - tip_h - margin
        x = max(screen_x + margin, min(x, max_x))
        y = max(screen_y + margin, min(y, max_y))

        if self._tutorial_overlaps_target(
            x, y, tip_w, tip_h, target_x, target_y, target_w, target_h
        ):
            x = target_x + max(0, (target_w - tip_w) // 2)
            y = target_y + target_h + gap
            x = max(screen_x + margin, min(x, max_x))
            y = max(screen_y + margin, min(y, max_y))

        self._tutorial_tooltip.geometry(f"+{x}+{y}")

    @staticmethod
    def _tutorial_overlaps_target(
        tip_x: int,
        tip_y: int,
        tip_w: int,
        tip_h: int,
        target_x: int,
        target_y: int,
        target_w: int,
        target_h: int,
    ) -> bool:
        tip_right = tip_x + tip_w
        tip_bottom = tip_y + tip_h
        target_right = target_x + target_w
        target_bottom = target_y + target_h
        return not (
            tip_right <= target_x
            or tip_x >= target_right
            or tip_bottom <= target_y
            or tip_y >= target_bottom
        )

    def _tutorial_ensure_widget_visible(self, widget):
        if widget is None or not widget.winfo_exists():
            return
        self.update_idletasks()
        scrollable = getattr(self, "controls_scrollable", None)
        if scrollable is None:
            return
        canvas = getattr(scrollable, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return

        canvas_top = canvas.winfo_rooty()
        canvas_bottom = canvas_top + canvas.winfo_height()
        widget_top = widget.winfo_rooty()
        widget_bottom = widget_top + widget.winfo_height()
        margin = 18
        if (
            widget_top >= canvas_top + margin
            and widget_bottom <= canvas_bottom - margin
        ):
            return

        try:
            _, content_bottom = canvas.bbox("all")[1], canvas.bbox("all")[3]
            content_height = max(1, content_bottom)
            current_fraction = canvas.yview()[0]
            current_offset = current_fraction * content_height
            delta = 0
            if widget_bottom > canvas_bottom - margin:
                delta = widget_bottom - (canvas_bottom - margin)
            elif widget_top < canvas_top + margin:
                delta = widget_top - (canvas_top + margin)
            target_offset = max(0, min(content_height, current_offset + delta))
            canvas.yview_moveto(target_offset / content_height)
            self.update_idletasks()
        except Exception:
            pass

    def _tutorial_highlight_widget(self, widget):
        self._clear_tutorial_highlight()
        if widget is None or not widget.winfo_exists():
            self._tutorial_target_widget = None
            return
        self._tutorial_target_widget = widget
        restore: dict[str, object] = {}
        try:
            restore["border_width"] = widget.cget("border_width")
            restore["border_color"] = widget.cget("border_color")
            widget.configure(border_width=3, border_color="#f59e0b")
        except Exception:
            try:
                restore["highlightthickness"] = widget.cget("highlightthickness")
                restore["highlightbackground"] = widget.cget("highlightbackground")
                widget.configure(highlightthickness=3, highlightbackground="#f59e0b")
            except Exception:
                pass
        self._tutorial_target_restore = restore

    def _clear_tutorial_highlight(self):
        if (
            self._tutorial_target_widget
            and self._tutorial_target_widget.winfo_exists()
            and self._tutorial_target_restore
        ):
            try:
                if "border_width" in self._tutorial_target_restore:
                    self._tutorial_target_widget.configure(
                        border_width=self._tutorial_target_restore["border_width"],
                        border_color=self._tutorial_target_restore["border_color"],
                    )
                elif "highlightthickness" in self._tutorial_target_restore:
                    self._tutorial_target_widget.configure(
                        highlightthickness=self._tutorial_target_restore[
                            "highlightthickness"
                        ],
                        highlightbackground=self._tutorial_target_restore[
                            "highlightbackground"
                        ],
                    )
            except Exception:
                pass
        self._tutorial_target_widget = None
        self._tutorial_target_restore = None

    def _tutorial_next(self):
        if self._tutorial_step_index >= len(self._tutorial_steps) - 1:
            self._close_tutorial(mark_seen=True)
            return
        self._tutorial_step_index += 1
        self._render_tutorial_step()

    def _tutorial_prev(self):
        if self._tutorial_step_index <= 0:
            return
        self._tutorial_step_index -= 1
        self._render_tutorial_step()

    def _close_tutorial(self, mark_seen: bool = True):
        if mark_seen:
            self.tutorial_seen = True
            self._save_state()
        self._close_tutorial_import_dialog()
        self._close_tutorial_music_editor_dialog()
        self._clear_tutorial_highlight()
        if self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists():
            self._tutorial_tooltip.destroy()
        self._tutorial_tooltip = None

    def _step_int_var(
        self, variable: tk.IntVar, delta: int, minimum: int, maximum: int
    ):
        self._stash_customize_undo(f"step:{id(variable)}")
        current = int(variable.get())
        variable.set(max(minimum, min(maximum, current + delta)))

    def _create_stepper_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.IntVar,
        minimum: int,
        maximum: int,
    ):
        stepper = ctk.CTkFrame(parent, fg_color="transparent")
        stepper.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="ew")
        stepper.grid_columnconfigure(0, weight=1)
        button_width = 32
        value_width = 60

        ctk.CTkLabel(stepper, text=label).grid(row=0, column=0, sticky="w")
        controls = ctk.CTkFrame(stepper, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        controls.grid_columnconfigure(0, minsize=button_width)
        controls.grid_columnconfigure(1, minsize=value_width)
        controls.grid_columnconfigure(2, minsize=button_width)

        ctk.CTkButton(
            controls,
            text="-",
            width=button_width,
            command=lambda: self._step_int_var(variable, -1, minimum, maximum),
        ).grid(row=0, column=0, padx=(0, 6))
        entry_var = tk.StringVar(value=str(int(variable.get())))

        def sync_entry_from_var(*_args):
            entry_var.set(str(int(variable.get())))

        def commit_int_entry(_event=None):
            raw_value = entry_var.get().strip()
            try:
                parsed = int(raw_value)
            except ValueError:
                parsed = int(variable.get())
            parsed = max(minimum, min(maximum, parsed))
            if parsed != int(variable.get()):
                self._stash_customize_undo(f"entry:{id(variable)}")
            variable.set(parsed)
            entry_var.set(str(parsed))
            self._save_state()

        variable.trace_add("write", sync_entry_from_var)
        entry_action_key = f"entry:{id(variable)}"
        value_entry = ctk.CTkEntry(
            controls,
            textvariable=entry_var,
            width=value_width,
            justify="center",
        )
        value_entry.grid(row=0, column=1, padx=(0, 6))
        value_entry.bind(
            "<FocusIn>",
            lambda _event, key=entry_action_key: self._stash_customize_undo(key),
        )
        value_entry.bind("<Return>", commit_int_entry)
        value_entry.bind("<FocusOut>", commit_int_entry)
        ctk.CTkButton(
            controls,
            text="+",
            width=button_width,
            command=lambda: self._step_int_var(variable, 1, minimum, maximum),
        ).grid(row=0, column=2)

        return value_entry

    def _step_float_var(
        self, variable: tk.DoubleVar, delta: float, minimum: float, maximum: float
    ):
        self._stash_customize_undo(f"step:{id(variable)}")
        current = float(variable.get())
        new_value = max(minimum, min(maximum, current + delta))
        variable.set(round(new_value, 2))

    def _create_float_stepper_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
    ):
        stepper = ctk.CTkFrame(parent, fg_color="transparent")
        stepper.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="ew")
        stepper.grid_columnconfigure(0, weight=1)
        button_width = 32
        value_width = 60

        ctk.CTkLabel(stepper, text=label).grid(row=0, column=0, sticky="w")
        controls = ctk.CTkFrame(stepper, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        controls.grid_columnconfigure(0, minsize=button_width)
        controls.grid_columnconfigure(1, minsize=value_width)
        controls.grid_columnconfigure(2, minsize=button_width)

        ctk.CTkButton(
            controls,
            text="-",
            width=button_width,
            command=lambda: self._step_float_var(variable, -step, minimum, maximum),
        ).grid(row=0, column=0, padx=(0, 6))
        entry_var = tk.StringVar(value=f"{float(variable.get()):.{decimals}f}")

        def sync_entry_from_var(*_args):
            entry_var.set(f"{float(variable.get()):.{decimals}f}")

        def commit_float_entry(_event=None):
            raw_value = entry_var.get().strip()
            try:
                parsed = float(raw_value)
            except ValueError:
                parsed = float(variable.get())
            parsed = max(minimum, min(maximum, parsed))
            rounded = round(parsed, decimals)
            if rounded != round(float(variable.get()), decimals):
                self._stash_customize_undo(f"entry:{id(variable)}")
            variable.set(rounded)
            entry_var.set(f"{float(variable.get()):.{decimals}f}")
            self._save_state()

        variable.trace_add("write", sync_entry_from_var)
        entry_action_key = f"entry:{id(variable)}"
        value_entry = ctk.CTkEntry(
            controls,
            textvariable=entry_var,
            width=value_width,
            justify="center",
        )
        value_entry.grid(row=0, column=1, padx=(0, 6))
        value_entry.bind(
            "<FocusIn>",
            lambda _event, key=entry_action_key: self._stash_customize_undo(key),
        )
        value_entry.bind("<Return>", commit_float_entry)
        value_entry.bind("<FocusOut>", commit_float_entry)
        ctk.CTkButton(
            controls,
            text="+",
            width=button_width,
            command=lambda: self._step_float_var(variable, step, minimum, maximum),
        ).grid(row=0, column=2)

        return value_entry

    def _select_template(self):
        file_path = filedialog.askopenfilename(
            title="Select template image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        self._load_template_file(Path(file_path), show_error=True)

    def _select_pdf(self):
        file_path = filedialog.askopenfilename(
            title="Select cards PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not file_path:
            return
        self.playlist_tracks = []
        self.playlist_include_artist = False
        self._load_pdf_file(Path(file_path), show_error=True)

    def _is_valid_spotify_playlist_url(self, value: str) -> bool:
        try:
            parsed = urlparse(value.strip())
        except Exception:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        if "spotify.com" not in parsed.netloc.lower():
            return False
        return "/playlist/" in parsed.path.lower()

    def _open_spotify_import_dialog(self, tutorial_mode: bool = False):
        if (
            tutorial_mode
            and self._tutorial_import_dialog
            and self._tutorial_import_dialog.winfo_exists()
        ):
            self._tutorial_import_dialog.lift()
            self._tutorial_import_dialog.focus_force()
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("Import from Spotify Playlist")
        dialog.geometry("760x500")
        dialog.minsize(700, 470)
        dialog.transient(self)
        if not tutorial_mode:
            dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        if tutorial_mode:
            self._tutorial_import_dialog = dialog

            def _clear_tutorial_dialog_ref(_event=None):
                if self._tutorial_import_dialog is dialog:
                    self._tutorial_import_dialog = None

            dialog.bind("<Destroy>", _clear_tutorial_dialog_ref, add="+")

        ctk.CTkLabel(
            dialog,
            text="Generate a bingo PDF from musicbingogenerator.com",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="ew")

        content = ctk.CTkFrame(dialog)
        content.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        # Top: playlist input section
        source_frame = ctk.CTkFrame(content)
        source_frame.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="ew")
        source_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            source_frame,
            text="Spotify Playlist URL",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")
        spotify_url_entry = ctk.CTkEntry(
            source_frame,
            textvariable=self.spotify_playlist_url_var,
            placeholder_text="https://open.spotify.com/playlist/...",
        )
        spotify_url_entry.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        spotify_url_entry.bind("<FocusOut>", lambda _event: self._save_state())
        ctk.CTkLabel(
            source_frame,
            text="Public Spotify playlists are supported.",
            text_color="#9ca3af",
            anchor="w",
        ).grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")

        # Middle: options and status in two columns
        options_frame = ctk.CTkFrame(content)
        options_frame.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="nsew")
        options_frame.grid_columnconfigure(0, weight=1, uniform="spotifycols")
        options_frame.grid_columnconfigure(1, weight=1, uniform="spotifycols")
        options_frame.grid_rowconfigure(0, weight=1)

        left_col = ctk.CTkFrame(options_frame)
        left_col.grid(row=0, column=0, padx=(12, 6), pady=12, sticky="nsew")
        left_col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left_col,
            text="Card Setup",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(left_col, text="Grid Size", anchor="w").grid(
            row=1, column=0, padx=12, pady=(0, 4), sticky="w"
        )
        ctk.CTkOptionMenu(
            left_col,
            values=["3x3", "4x4", "5x5", "6x6"],
            variable=self.spotify_grid_size_var,
            width=140,
            command=lambda _value: self._save_state(),
        ).grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")

        ctk.CTkLabel(left_col, text="Number of Cards", anchor="w").grid(
            row=3, column=0, padx=12, pady=(0, 4), sticky="w"
        )
        cards_controls = ctk.CTkFrame(left_col, fg_color="transparent")
        cards_controls.grid(row=4, column=0, padx=12, pady=(0, 4), sticky="w")
        card_count_entry_var = tk.StringVar(
            value=str(int(self.spotify_card_count_var.get()))
        )

        def sync_card_count_entry(*_args):
            card_count_entry_var.set(str(int(self.spotify_card_count_var.get())))

        def commit_card_count(_event=None):
            raw_value = card_count_entry_var.get().strip()
            try:
                parsed = int(raw_value)
            except ValueError:
                parsed = int(self.spotify_card_count_var.get())
            parsed = max(1, min(200, parsed))
            self.spotify_card_count_var.set(parsed)
            card_count_entry_var.set(str(parsed))
            self._save_state()

        def step_spotify_cards(delta: int):
            self._step_int_var(self.spotify_card_count_var, delta, 1, 200)

        ctk.CTkButton(
            cards_controls,
            text="-",
            width=32,
            command=lambda: step_spotify_cards(-1),
        ).grid(row=0, column=0, padx=(0, 6))
        self.spotify_card_count_var.trace_add("write", sync_card_count_entry)
        spotify_card_count_entry = ctk.CTkEntry(
            cards_controls,
            textvariable=card_count_entry_var,
            width=60,
            justify="center",
        )
        spotify_card_count_entry.grid(row=0, column=1, padx=(0, 6))
        spotify_card_count_entry.bind("<Return>", commit_card_count)
        spotify_card_count_entry.bind("<FocusOut>", commit_card_count)
        ctk.CTkButton(
            cards_controls,
            text="+",
            width=32,
            command=lambda: step_spotify_cards(1),
        ).grid(row=0, column=2)

        right_col = ctk.CTkFrame(options_frame)
        right_col.grid(row=0, column=1, padx=(6, 12), pady=12, sticky="nsew")
        right_col.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right_col,
            text="Options",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 8), sticky="w")

        include_artist_switch = ctk.CTkSwitch(
            right_col,
            text="Include artist name",
            variable=self.spotify_include_artist_var,
            command=self._save_state,
        )
        include_artist_switch.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")
        free_center_switch = ctk.CTkSwitch(
            right_col,
            text="Free center space (odd grids only)",
            variable=self.spotify_free_center_var,
            command=self._save_state,
        )
        free_center_switch.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")

        spotify_status_label = ctk.CTkLabel(
            right_col, text="Status: idle", text_color="#9ca3af", anchor="w"
        )
        spotify_status_label.grid(row=3, column=0, padx=12, pady=(6, 10), sticky="ew")

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="ew")
        actions.grid_columnconfigure(0, weight=1, uniform="action")
        actions.grid_columnconfigure(1, weight=1, uniform="action")

        ctk.CTkButton(
            actions,
            text="Close",
            command=dialog.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        generate_button = ctk.CTkButton(
            actions,
            text="Generate and Import PDF",
            fg_color="#16a34a",
            hover_color="#15803d",
            command=lambda: (
                commit_card_count(),
                self._start_spotify_pdf_generation(
                    dialog=dialog,
                    status_label=spotify_status_label,
                    generate_button=generate_button,
                ),
            ),
        )
        generate_button.grid(row=0, column=1, sticky="ew")

    def _start_spotify_pdf_generation(self, dialog, status_label, generate_button):
        playlist_url = self.spotify_playlist_url_var.get().strip()
        if not self._is_valid_spotify_playlist_url(playlist_url):
            messagebox.showwarning(
                "Invalid Playlist URL",
                "Please provide a valid Spotify playlist URL.",
            )
            return
        grid_size_text = self.spotify_grid_size_var.get().strip().lower()
        try:
            grid_size = int(grid_size_text.split("x")[0])
        except Exception:
            messagebox.showwarning(
                "Invalid Grid Size", "Please choose a valid grid size."
            )
            return
        number_of_cards = int(self.spotify_card_count_var.get())
        if number_of_cards < 1:
            messagebox.showwarning(
                "Invalid Card Count", "Number of cards must be at least 1."
            )
            return

        options = PlaylistGenerationOptions(
            playlist_url=playlist_url,
            grid_size=grid_size,
            number_of_cards=number_of_cards,
            include_artist_name=bool(self.spotify_include_artist_var.get()),
            free_center_space=bool(self.spotify_free_center_var.get()),
        )
        temp_pdf_dir = SPOTIFY_TEMP_PDF_DIR

        generate_button.configure(state="disabled")
        status_label.configure(text="Status: generating PDF from playlist...")

        def worker():
            try:
                result = generate_playlist_pdf(
                    options=options, output_dir=temp_pdf_dir
                )
                self.after(
                    0,
                    lambda result=result: self._on_spotify_pdf_success(
                        dialog=dialog,
                        status_label=status_label,
                        generate_button=generate_button,
                        result=result,
                    ),
                )
            except Exception as error:
                self.after(
                    0,
                    lambda error=error: self._on_spotify_pdf_failure(
                        status_label=status_label,
                        generate_button=generate_button,
                        error=error,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_spotify_pdf_success(
        self, dialog, status_label, generate_button, result: PlaylistPdfResult
    ):
        pdf_path = result.pdf_path
        self.spotify_downloaded_pdf_path = pdf_path
        self.playlist_tracks = list(result.tracks)
        self.playlist_include_artist = bool(result.include_artist_name)
        status_label.configure(text=f"Status: downloaded {pdf_path.name}")
        generate_button.configure(state="normal")
        dialog.destroy()
        loaded = self._load_pdf_file(pdf_path, show_error=True, reset_grid=False)
        if loaded:
            self._save_state()
            messagebox.showinfo("Spotify Import Complete", f"Imported PDF:\n{pdf_path}")

    def _on_spotify_pdf_failure(self, status_label, generate_button, error: Exception):
        status_label.configure(text="Status: failed")
        generate_button.configure(state="normal")
        if isinstance(error, PlaylistGenerationError):
            messagebox.showerror("Spotify Import Error", str(error))
            return
        messagebox.showerror(
            "Spotify Import Error", f"Could not generate PDF:\n{error}"
        )

    def _effective_grid_size(self) -> int:
        if self.pdf_layout in SUPPORTED_GRID_SIZES:
            return self.pdf_layout
        return 5

    def _default_grid_cells(self, grid_size: int) -> list[dict]:
        if self.template_image is None:
            return []
        width, height = self.template_image.size
        return build_default_grid_cells(width, height, grid_size)

    def _default_grid_origin(self, grid_size: int) -> tuple[int, int]:
        cells = self._default_grid_cells(grid_size)
        if not cells:
            return (0, 0)
        return min(cell["x1"] for cell in cells), min(cell["y1"] for cell in cells)

    def _default_grid_cell_size(self, grid_size: int) -> tuple[int, int]:
        cells = self._default_grid_cells(grid_size)
        if not cells:
            return (120, 120)
        widths = [cell["width"] for cell in cells]
        heights = [cell["height"] for cell in cells]
        return (
            int(round(float(np.median(widths)))),
            int(round(float(np.median(heights)))),
        )

    def _reset_grid_placement(self) -> None:
        grid_size = self._effective_grid_size()
        default_x, default_y = self._default_grid_origin(grid_size)
        default_w, default_h = self._default_grid_cell_size(grid_size)
        self.grid_x_var.set(default_x)
        self.grid_y_var.set(default_y)
        self.grid_cell_width_var.set(default_w)
        self.grid_cell_height_var.set(default_h)

    def _apply_legacy_grid_offsets(self, offset_x: int, offset_y: int) -> None:
        grid_size = self._effective_grid_size()
        default_x, default_y = self._default_grid_origin(grid_size)
        self.grid_x_var.set(default_x + offset_x)
        self.grid_y_var.set(default_y + offset_y)

    def _apply_legacy_cell_adjustments(self, width_adjust: int, height_adjust: int) -> None:
        grid_size = self._effective_grid_size()
        default_w, default_h = self._default_grid_cell_size(grid_size)
        self.grid_cell_width_var.set(max(20, default_w + width_adjust))
        self.grid_cell_height_var.set(max(20, default_h + height_adjust))

    def _update_pdf_layout_label(self) -> None:
        if self.pdf_layout in SUPPORTED_GRID_SIZES:
            self.pdf_layout_label.configure(
                text=f"Grid layout: {self.pdf_layout}x{self.pdf_layout} (from PDF)"
            )
        else:
            self.pdf_layout_label.configure(text="Grid layout: -")

    def _format_output_button_text(self) -> str:
        if self.output_dir is None:
            return "Browse Output Folder"
        path_text = str(self.output_dir)
        max_len = 38
        if len(path_text) > max_len:
            path_text = f"...{path_text[-(max_len - 3):]}"
        return f"Output: {path_text}"

    def _select_output_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if not folder:
            return
        self.output_dir = Path(folder)
        self.output_folder_button.configure(text=self._format_output_button_text())
        self._save_state()

    def _format_free_icon_label(self) -> str:
        icon_path = self.free_icon_path or FREE_IMAGE_PATH
        if self.free_icon_path:
            label_prefix = "FREE Icon:"
        else:
            label_prefix = "FREE Icon (default):"
        name = icon_path.name
        if len(name) > 24:
            name = f"{name[:10]}...{name[-10:]}"
        return f"{label_prefix} {name}"

    def _capture_customize_snapshot(self) -> dict:
        return {
            "text_color": self._normalize_color(self.text_color_var.get()),
            "font_size": int(self.font_size_var.get()),
            "text_offset_x": int(self.text_offset_x_var.get()),
            "text_offset_y": int(self.text_offset_y_var.get()),
            "free_icon_size": round(float(self.free_icon_size_var.get()), 2),
            "free_icon_path": str(self.free_icon_path) if self.free_icon_path else None,
            "grid_x": int(self.grid_x_var.get()),
            "grid_y": int(self.grid_y_var.get()),
            "grid_cell_width": int(self.grid_cell_width_var.get()),
            "grid_cell_height": int(self.grid_cell_height_var.get()),
            "show_grid_overlay": bool(self.show_grid_overlay_var.get()),
        }

    def _apply_customize_snapshot(self, snapshot: dict) -> None:
        self._customize_history_suppressed = True
        try:
            self.text_color_var.set(snapshot.get("text_color", "#000000"))
            self.font_size_var.set(int(snapshot.get("font_size", 26)))
            self.text_offset_x_var.set(int(snapshot.get("text_offset_x", 0)))
            self.text_offset_y_var.set(int(snapshot.get("text_offset_y", 0)))
            self.free_icon_size_var.set(
                float(snapshot.get("free_icon_size", FREE_ICON_SIZE_DEFAULT))
            )
            free_icon_path = snapshot.get("free_icon_path")
            if free_icon_path and Path(free_icon_path).exists():
                self.free_icon_path = Path(free_icon_path)
            else:
                self.free_icon_path = None
            self.free_icon_path_label.configure(text=self._format_free_icon_label())
            if "grid_x" in snapshot or "grid_y" in snapshot:
                self.grid_x_var.set(int(snapshot.get("grid_x", 0)))
                self.grid_y_var.set(int(snapshot.get("grid_y", 0)))
            else:
                self._apply_legacy_grid_offsets(
                    int(snapshot.get("grid_offset_x", 0)),
                    int(snapshot.get("grid_offset_y", 0)),
                )
            if "grid_cell_width" in snapshot or "grid_cell_height" in snapshot:
                self.grid_cell_width_var.set(
                    int(snapshot.get("grid_cell_width", 120))
                )
                self.grid_cell_height_var.set(
                    int(snapshot.get("grid_cell_height", 120))
                )
            else:
                self._apply_legacy_cell_adjustments(
                    int(snapshot.get("manual_cell_width", 0)),
                    int(snapshot.get("manual_cell_height", 0)),
                )
            self.show_grid_overlay_var.set(
                bool(snapshot.get("show_grid_overlay", True))
            )
        finally:
            self._customize_history_suppressed = False
        self._invalidate_free_image_cache()
        self._schedule_preview_refresh()

    def _clear_customize_action_group(self) -> None:
        self._customize_active_action_key = None

    def _stash_customize_undo(self, action_key: str | None = None) -> None:
        if self._customize_history_suppressed or self._loading_state:
            return

        if action_key is not None and action_key == self._customize_active_action_key:
            return

        snapshot = self._capture_customize_snapshot()
        if self._customize_undo_stack and self._customize_undo_stack[-1] == snapshot:
            self._customize_active_action_key = action_key
            return

        self._customize_undo_stack.append(snapshot)
        if len(self._customize_undo_stack) > CUSTOMIZE_UNDO_LIMIT:
            self._customize_undo_stack.pop(0)
        self._customize_redo_stack.clear()
        self._customize_active_action_key = action_key
        self._update_customize_undo_redo_buttons()

    def _update_customize_undo_redo_buttons(self) -> None:
        undo_state = "normal" if self._customize_undo_stack else "disabled"
        redo_state = "normal" if self._customize_redo_stack else "disabled"
        self.undo_customize_button.configure(state=undo_state)
        self.redo_customize_button.configure(state=redo_state)

    def _undo_customize(self) -> None:
        if not self._customize_undo_stack:
            return
        self._clear_customize_action_group()
        current = self._capture_customize_snapshot()
        previous = self._customize_undo_stack.pop()
        if previous != current:
            self._customize_redo_stack.append(current)
            if len(self._customize_redo_stack) > CUSTOMIZE_UNDO_LIMIT:
                self._customize_redo_stack.pop(0)
        self._apply_customize_snapshot(previous)
        self._update_customize_undo_redo_buttons()
        self._schedule_save_state()

    def _redo_customize(self) -> None:
        if not self._customize_redo_stack:
            return
        self._clear_customize_action_group()
        current = self._capture_customize_snapshot()
        next_snapshot = self._customize_redo_stack.pop()
        if next_snapshot != current:
            self._customize_undo_stack.append(current)
            if len(self._customize_undo_stack) > CUSTOMIZE_UNDO_LIMIT:
                self._customize_undo_stack.pop(0)
        self._apply_customize_snapshot(next_snapshot)
        self._update_customize_undo_redo_buttons()
        self._schedule_save_state()

    def _on_grid_overlay_toggled(self) -> None:
        self._stash_customize_undo("toggle:grid_overlay")
        self._schedule_preview_refresh()

    def _on_customize_undo_shortcut(self, _event=None):
        self._undo_customize()
        return "break"

    def _on_customize_redo_shortcut(self, _event=None):
        self._redo_customize()
        return "break"

    def _select_free_icon(self):
        file_path = filedialog.askopenfilename(
            title="Select FREE icon image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        selected = Path(file_path)
        try:
            Image.open(selected).verify()
        except Exception:
            messagebox.showerror(
                "Invalid Image", "Could not read the selected icon image."
            )
            return
        self._stash_customize_undo("pick:free_icon")
        self.free_icon_path = selected
        self.free_icon_path_label.configure(text=self._format_free_icon_label())
        self._invalidate_free_image_cache()
        self._schedule_preview_refresh()

    def _open_output_folder(self):
        if self.output_dir is None:
            messagebox.showwarning(
                "Missing Output Folder", "Please choose an output folder first."
            )
            return
        if not self.output_dir.exists():
            messagebox.showwarning(
                "Missing Folder", f"Output folder does not exist:\n{self.output_dir}"
            )
            return
        os.startfile(self.output_dir)

    def _reset_configs(self):
        self._stash_customize_undo("reset:all")
        self.text_color_var.set("#000000")
        self.font_size_var.set(26)
        self.text_offset_x_var.set(0)
        self.text_offset_y_var.set(0)
        self.free_icon_size_var.set(FREE_ICON_SIZE_DEFAULT)
        self.free_icon_path = None
        self.free_icon_path_label.configure(text=self._format_free_icon_label())
        self._invalidate_free_image_cache()
        self._reset_grid_placement()
        self.show_grid_overlay_var.set(True)
        self.generate_progress.set(0)
        self.generate_status_label.configure(text="Generation status: idle")
        self._schedule_preview_refresh()

    def _generate_cards(self):
        if self.template_image is None or self.template_path is None:
            messagebox.showwarning(
                "Missing Template", "Please select a template image first."
            )
            return
        if self.pdf_path is None:
            messagebox.showwarning(
                "Missing PDF",
                "Please import from Spotify playlist first.",
            )
            return
        if self.output_dir is None:
            messagebox.showwarning(
                "Missing Output Folder", "Please choose an output folder first."
            )
            return
        self.generate_button.configure(state="disabled")
        self.generate_progress.set(0)
        self.generate_status_label.configure(text="Generation status: preparing...")
        self.update_idletasks()

        try:
            cards = self._get_cached_valid_cards(force_reload=True)
            if not cards:
                self.generate_status_label.configure(
                    text="Generation status: no cards found"
                )
                messagebox.showwarning(
                    "No Cards Found", "No cards were extracted from the PDF."
                )
                return

            total_cards = len(cards)
            if total_cards == 0:
                self.generate_status_label.configure(
                    text="Generation status: no valid cards"
                )
                messagebox.showwarning(
                    "No Cards Found", "No cards with song matrices were extracted."
                )
                return

            generated_count = 0
            for index, card in enumerate(cards, start=1):
                matrix = self._apply_music_name_overrides(card.get("songs_matrix", []))
                grid_size = len(matrix)
                image = build_preview(
                    template_image=self.template_image,
                    matrix=matrix,
                    grid_size=grid_size,
                    text_color_hex=self._normalize_color(self.text_color_var.get()),
                    font_size=int(self.font_size_var.get()),
                    text_offset_x=int(self.text_offset_x_var.get()),
                    text_offset_y=int(self.text_offset_y_var.get()),
                    free_icon_size=float(self.free_icon_size_var.get()),
                    grid_x=int(self.grid_x_var.get()),
                    grid_y=int(self.grid_y_var.get()),
                    cell_width=int(self.grid_cell_width_var.get()),
                    cell_height=int(self.grid_cell_height_var.get()),
                    show_grid_overlay=False,
                    free_image_path=self.free_icon_path,
                    free_image=self._get_free_image_rgba(),
                )
                card_number = int(card.get("card_number", generated_count + 1))
                output_path = self.output_dir / f"card_{card_number:02d}.png"
                image.save(output_path)
                generated_count += 1
                self.generate_progress.set(index / total_cards)
                self.generate_status_label.configure(
                    text=f"Generation status: {index}/{total_cards}"
                )
                self.update_idletasks()

            self.generate_status_label.configure(
                text=f"Generation status: done ({generated_count}/{total_cards})"
            )
            messagebox.showinfo(
                "Generation Complete",
                f"Generated {generated_count} cards in:\n{self.output_dir}",
            )
        except Exception as error:
            self.generate_status_label.configure(text="Generation status: failed")
            messagebox.showerror(
                "Generation Error", f"Could not generate cards:\n{error}"
            )
        finally:
            self.generate_button.configure(state="normal")

    def _show_preview_warning(self, message: str):
        self.preview_base_image = None
        self.preview_photo = None
        self.preview_image_id = None
        self.preview_canvas.delete("all")
        canvas_w = max(200, self.preview_canvas.winfo_width())
        canvas_h = max(150, self.preview_canvas.winfo_height())
        self.preview_canvas.create_text(
            canvas_w // 2,
            canvas_h // 2,
            text=message,
            fill="#f59e0b",
            anchor="center",
            width=max(180, canvas_w - 40),
        )
        self.preview_canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))
        self._set_preview_scrollbars_visibility(
            show_horizontal=False, show_vertical=False
        )

    def _set_preview_scrollbars_visibility(
        self, show_horizontal: bool, show_vertical: bool
    ):
        if show_horizontal != self._preview_h_scroll_visible:
            if show_horizontal:
                self.preview_h_scroll.grid(row=1, column=0, sticky="ew")
            else:
                self.preview_h_scroll.grid_remove()
            self._preview_h_scroll_visible = show_horizontal
        if show_vertical != self._preview_v_scroll_visible:
            if show_vertical:
                self.preview_v_scroll.grid(row=0, column=1, sticky="ns")
            else:
                self.preview_v_scroll.grid_remove()
            self._preview_v_scroll_visible = show_vertical

    def _preview_layout(self, render_w: int, render_h: int) -> dict[str, int]:
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        origin_x = max(0, (canvas_w - render_w) // 2)
        origin_y = max(0, (canvas_h - render_h) // 2)
        scroll_w = max(canvas_w, render_w)
        scroll_h = max(canvas_h, render_h)
        return {
            "canvas_w": canvas_w,
            "canvas_h": canvas_h,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "scroll_w": scroll_w,
            "scroll_h": scroll_h,
        }

    def _set_preview_zoom(
        self,
        zoom_value: float,
        anchor_canvas_x: int | None = None,
        anchor_canvas_y: int | None = None,
    ):
        old_zoom = self.preview_zoom
        base_x: float | None = None
        base_y: float | None = None
        pointer_x = anchor_canvas_x
        pointer_y = anchor_canvas_y

        if (
            self.preview_base_image is not None
            and old_zoom > 0
            and anchor_canvas_x is not None
            and anchor_canvas_y is not None
        ):
            base_w, base_h = self.preview_base_image.size
            old_render_w = max(1, int(round(base_w * old_zoom)))
            old_render_h = max(1, int(round(base_h * old_zoom)))
            old_layout = self._preview_layout(old_render_w, old_render_h)
            world_x = self.preview_canvas.canvasx(anchor_canvas_x)
            world_y = self.preview_canvas.canvasy(anchor_canvas_y)
            base_x = (world_x - old_layout["origin_x"]) / old_zoom
            base_y = (world_y - old_layout["origin_y"]) / old_zoom

        self.preview_zoom = max(0.25, min(4.0, zoom_value))
        self.preview_zoom_label_var.set(f"{int(round(self.preview_zoom * 100))}%")
        self._render_preview_image()

        if (
            self.preview_base_image is None
            or base_x is None
            or base_y is None
            or pointer_x is None
            or pointer_y is None
        ):
            return

        base_w, base_h = self.preview_base_image.size
        new_render_w = max(1, int(round(base_w * self.preview_zoom)))
        new_render_h = max(1, int(round(base_h * self.preview_zoom)))
        new_layout = self._preview_layout(new_render_w, new_render_h)

        new_world_x = new_layout["origin_x"] + (base_x * self.preview_zoom)
        new_world_y = new_layout["origin_y"] + (base_y * self.preview_zoom)

        max_x_scroll = max(0, new_layout["scroll_w"] - new_layout["canvas_w"])
        max_y_scroll = max(0, new_layout["scroll_h"] - new_layout["canvas_h"])

        desired_left = new_world_x - pointer_x
        desired_top = new_world_y - pointer_y

        if max_x_scroll > 0:
            clamped_left = max(0, min(max_x_scroll, desired_left))
            self.preview_canvas.xview_moveto(clamped_left / new_layout["scroll_w"])
        else:
            self.preview_canvas.xview_moveto(0)
        if max_y_scroll > 0:
            clamped_top = max(0, min(max_y_scroll, desired_top))
            self.preview_canvas.yview_moveto(clamped_top / new_layout["scroll_h"])
        else:
            self.preview_canvas.yview_moveto(0)

    def _calculate_fit_zoom(self) -> float:
        if self.preview_base_image is None:
            return 1.0
        image_w, image_h = self.preview_base_image.size
        if image_w <= 0 or image_h <= 0:
            return 1.0
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        fit_zoom = min(canvas_w / image_w, canvas_h / image_h)
        return max(0.25, min(4.0, fit_zoom))

    def _zoom_in(self):
        self._set_preview_zoom(self.preview_zoom * 1.1)

    def _zoom_out(self):
        self._set_preview_zoom(self.preview_zoom / 1.1)

    def _zoom_reset(self):
        self._set_preview_zoom(self._calculate_fit_zoom())

    def _on_preview_ctrl_wheel(self, event):
        if event.delta > 0:
            self._set_preview_zoom(self.preview_zoom * 1.1, event.x, event.y)
        else:
            self._set_preview_zoom(self.preview_zoom / 1.1, event.x, event.y)

    def _on_preview_scroll(self, event):
        if event.delta == 0:
            return
        self.preview_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_preview_shift_scroll(self, event):
        if event.delta == 0:
            return
        self.preview_canvas.xview_scroll(int(-event.delta / 120), "units")

    def _on_preview_canvas_configure(self, _event):
        if self._pending_fit_zoom and self.preview_base_image is not None:
            self._pending_fit_zoom = False
            self._set_preview_zoom(self._calculate_fit_zoom())
            return
        self._render_preview_image()

    def _render_preview_image(self):
        if self.preview_base_image is None:
            return
        base_w, base_h = self.preview_base_image.size
        render_w = max(1, int(round(base_w * self.preview_zoom)))
        render_h = max(1, int(round(base_h * self.preview_zoom)))
        rendered = self.preview_base_image.resize(
            (render_w, render_h), Image.Resampling.LANCZOS
        )
        self.preview_photo = ImageTk.PhotoImage(rendered)
        self.preview_canvas.delete("all")
        layout = self._preview_layout(render_w, render_h)
        origin_x = layout["origin_x"]
        origin_y = layout["origin_y"]
        self.preview_image_id = self.preview_canvas.create_image(
            origin_x, origin_y, anchor="nw", image=self.preview_photo
        )
        scroll_w = layout["scroll_w"]
        scroll_h = layout["scroll_h"]
        self.preview_canvas.configure(scrollregion=(0, 0, scroll_w, scroll_h))
        self._set_preview_scrollbars_visibility(
            show_horizontal=render_w > layout["canvas_w"],
            show_vertical=render_h > layout["canvas_h"],
        )

    def _invalidate_preview_caches(self) -> None:
        self._cached_preview_matrix = None
        self._cached_preview_matrix_key = None
    def _invalidate_free_image_cache(self) -> None:
        self._cached_free_image = None
        self._cached_free_image_path = None

    def _preview_matrix_cache_key(self, grid_size: int) -> tuple:
        return (
            str(self.pdf_path) if self.pdf_path else None,
            grid_size,
            tuple(sorted(self.music_name_overrides.items())),
            tuple(
                (track.get("id"), track.get("name"), track.get("artist"))
                for track in self.playlist_tracks
            ),
            bool(self.playlist_include_artist),
        )

    def _get_preview_matrix(self, grid_size: int) -> list[list[str]]:
        cache_key = self._preview_matrix_cache_key(grid_size)
        if (
            self._cached_preview_matrix is not None
            and self._cached_preview_matrix_key == cache_key
        ):
            return self._cached_preview_matrix

        matrix = get_placeholder_matrix(grid_size)
        if self.pdf_path:
            try:
                extracted = extract_first_card_matrix(self.pdf_path, grid_size)
                if extracted and len(extracted) == grid_size:
                    normalized = [
                        [self._canonical_cell_text(cell) for cell in row]
                        for row in extracted
                    ]
                    matrix = self._apply_music_name_overrides(normalized)
            except Exception:
                pass

        self._cached_preview_matrix = matrix
        self._cached_preview_matrix_key = cache_key
        return matrix

    def _get_free_image_rgba(self) -> Image.Image | None:
        icon_path = self.free_icon_path or FREE_IMAGE_PATH
        if (
            self._cached_free_image is not None
            and self._cached_free_image_path == icon_path
        ):
            return self._cached_free_image

        if not icon_path.exists():
            self._cached_free_image = None
            self._cached_free_image_path = icon_path
            return None

        self._cached_free_image = Image.open(icon_path).convert("RGBA")
        self._cached_free_image_path = icon_path
        return self._cached_free_image

    def _schedule_preview_refresh(self) -> None:
        if self._loading_state:
            return
        if self._preview_refresh_after_id is not None:
            self.after_cancel(self._preview_refresh_after_id)
        self._preview_refresh_after_id = self.after(
            PREVIEW_REFRESH_DEBOUNCE_MS, self._run_scheduled_preview_refresh
        )

    def _run_scheduled_preview_refresh(self) -> None:
        self._preview_refresh_after_id = None
        self._refresh_preview()

    def _flush_preview_refresh(self) -> None:
        if self._preview_refresh_after_id is not None:
            self.after_cancel(self._preview_refresh_after_id)
            self._preview_refresh_after_id = None
        self._refresh_preview()

    def _schedule_save_state(self) -> None:
        if self._loading_state:
            return
        if self._save_state_after_id is not None:
            self.after_cancel(self._save_state_after_id)
        self._save_state_after_id = self.after(
            SAVE_STATE_DEBOUNCE_MS, self._run_scheduled_save_state
        )

    def _run_scheduled_save_state(self) -> None:
        self._save_state_after_id = None
        self._save_state()

    def _flush_save_state(self) -> None:
        if self._save_state_after_id is not None:
            self.after_cancel(self._save_state_after_id)
            self._save_state_after_id = None
        self._save_state()

    def _pick_text_color(self):
        initial_color = self._normalize_color(self.text_color_var.get())
        selected, hex_color = colorchooser.askcolor(
            color=initial_color, title="Choose text color"
        )
        if selected is None or not hex_color:
            return
        normalized = hex_color.lower()
        if normalized == initial_color:
            return
        self._stash_customize_undo("color_picker")
        self.text_color_var.set(normalized)
        self._schedule_preview_refresh()

    def _normalize_color(self, value: str) -> str:
        if not value:
            return "#000000"
        color = value.strip()
        if not color.startswith("#"):
            color = f"#{color}"
        if len(color) != 7:
            return "#000000"
        try:
            int(color[1:], 16)
        except ValueError:
            return "#000000"
        return color.lower()

    def _refresh_preview(self):
        if self.template_image is None:
            return

        grid_size = self._effective_grid_size()
        matrix = self._get_preview_matrix(grid_size)

        color_value = self._normalize_color(self.text_color_var.get())
        if color_value != self.text_color_var.get().strip().lower():
            self.text_color_var.set(color_value)
            return

        self.color_swatch.configure(fg_color=color_value)

        preview = build_preview(
            template_image=self.template_image,
            matrix=matrix,
            grid_size=grid_size,
            text_color_hex=color_value,
            font_size=int(self.font_size_var.get()),
            text_offset_x=int(self.text_offset_x_var.get()),
            text_offset_y=int(self.text_offset_y_var.get()),
            free_icon_size=float(self.free_icon_size_var.get()),
            grid_x=int(self.grid_x_var.get()),
            grid_y=int(self.grid_y_var.get()),
            cell_width=int(self.grid_cell_width_var.get()),
            cell_height=int(self.grid_cell_height_var.get()),
            show_grid_overlay=bool(self.show_grid_overlay_var.get()),
            free_image=self._get_free_image_rgba(),
        )

        should_fit_preview = (
            self.preview_base_image is None
            or self.preview_base_image.size != preview.size
        )
        self.preview_base_image = preview
        if should_fit_preview:
            self._pending_fit_zoom = True
            self._render_preview_image()
        else:
            self._render_preview_image()
        self._schedule_save_state()

    def _load_template_file(self, path: Path, show_error: bool):
        self.template_path = path
        try:
            self.template_image = Image.open(self.template_path).convert("RGB")
            self._invalidate_preview_caches()
            if show_error:
                self._reset_grid_placement()
            elif (
                self._pending_legacy_grid_offsets is not None
                or self._pending_legacy_cell_adjustments is not None
            ):
                if self._pending_legacy_grid_offsets is not None:
                    offset_x, offset_y = self._pending_legacy_grid_offsets
                    self._apply_legacy_grid_offsets(offset_x, offset_y)
                    self._pending_legacy_grid_offsets = None
                if self._pending_legacy_cell_adjustments is not None:
                    width_adj, height_adj = self._pending_legacy_cell_adjustments
                    self._apply_legacy_cell_adjustments(width_adj, height_adj)
                    self._pending_legacy_cell_adjustments = None
            self._flush_preview_refresh()
            return True
        except Exception as error:
            self.template_path = None
            self.template_image = None
            if show_error:
                messagebox.showerror(
                    "Template Error", f"Could not read template:\n{error}"
                )
            return False

    def _load_pdf_file(
        self, path: Path, show_error: bool, reset_grid: bool = False
    ):
        previous_layout = self.pdf_layout
        self.pdf_path = path
        self.cached_pdf_cards = None
        if not self._loading_state:
            self.music_name_overrides = {}
        try:
            self.pdf_layout = detect_pdf_layout(self.pdf_path)
            self._update_pdf_layout_label()
            if reset_grid or (
                previous_layout is not None and previous_layout != self.pdf_layout
            ):
                self._reset_grid_placement()
            self.edit_music_button.configure(state="normal")
            self._invalidate_preview_caches()
            self._refresh_music_name_override_aliases()
            self._flush_preview_refresh()
            return True
        except Exception as error:
            self.pdf_path = None
            self.pdf_layout = None
            self.cached_pdf_cards = None
            if not self._loading_state:
                self.music_name_overrides = {}
            self._update_pdf_layout_label()
            self.edit_music_button.configure(state="disabled")
            if show_error:
                messagebox.showerror("PDF Error", f"Could not read PDF:\n{error}")
            return False

    def _playlist_track_label_list(self) -> list[str]:
        if not self.playlist_tracks:
            return []
        return playlist_track_labels(
            self.playlist_tracks, self.playlist_include_artist
        )

    def _canonical_cell_text(self, cell: str) -> str:
        if is_free_cell_text(cell):
            return cell
        labels = self._playlist_track_label_list()
        if labels:
            matched = match_cell_to_playlist_label(cell, labels)
            if matched:
                return matched
        return canonical_music_name(cell)

    def _music_track_key(self, text: str) -> str:
        if is_free_cell_text(text):
            return ""
        labels = self._playlist_track_label_list()
        if labels:
            matched = match_cell_to_playlist_label(text, labels)
            if matched:
                return matched.casefold()
        return song_identity_key(text)

    def _get_cached_valid_cards(self, force_reload: bool = False) -> list[dict]:
        if self.pdf_path is None:
            return []
        if self.cached_pdf_cards is not None and not force_reload:
            return self.cached_pdf_cards
        cards = extract_bingo_cards(self.pdf_path)
        valid_cards: list[dict] = []
        for card in cards:
            matrix = card.get("songs_matrix")
            if not matrix:
                continue
            normalized_matrix = [
                [self._canonical_cell_text(cell) for cell in row] for row in matrix
            ]
            normalized_card = dict(card)
            normalized_card["songs_matrix"] = normalized_matrix
            valid_cards.append(normalized_card)
        self.cached_pdf_cards = valid_cards
        return self.cached_pdf_cards

    def _identity_override_map(self, user_overrides: dict[str, str]) -> dict[str, str]:
        identity_map: dict[str, str] = {}
        for original, updated in user_overrides.items():
            identity = self._music_track_key(original)
            if identity:
                identity_map[identity] = updated
        return identity_map

    def _expand_music_name_overrides(self, user_overrides: dict[str, str]) -> dict[str, str]:
        """Map every cell variant on any card that shares the same song title."""
        if not user_overrides:
            return {}

        identity_targets = self._identity_override_map(user_overrides)
        expanded = dict(user_overrides)

        for card in self._get_cached_valid_cards():
            for row in card.get("songs_matrix") or []:
                for cell in row:
                    if is_free_cell_text(cell):
                        continue
                    identity = self._music_track_key(cell)
                    if identity in identity_targets:
                        expanded[cell] = identity_targets[identity]

        return expanded

    def _refresh_music_name_override_aliases(self) -> None:
        if not self.music_name_overrides or self.pdf_path is None:
            return

        identity_updates = self._identity_override_map(self.music_name_overrides)
        if not identity_updates:
            return

        representative: dict[str, str] = {}
        seen_identities: set[str] = set()
        for card in self._get_cached_valid_cards():
            for row in card.get("songs_matrix") or []:
                for cell in row:
                    if is_free_cell_text(cell):
                        continue
                    identity = self._music_track_key(cell)
                    if (
                        identity in identity_updates
                        and identity not in seen_identities
                    ):
                        representative[cell] = identity_updates[identity]
                        seen_identities.add(identity)

        self.music_name_overrides = self._expand_music_name_overrides(representative)

    def _music_override_value_for(self, display_name: str) -> str:
        identity = self._music_track_key(display_name)
        identity_map = self._identity_override_map(self.music_name_overrides)
        if identity in identity_map:
            return identity_map[identity]
        if display_name in self.music_name_overrides:
            return self.music_name_overrides[display_name]
        return self.music_name_overrides.get(
            canonical_music_name(display_name), display_name
        )

    def _resolve_music_cell_text(self, cell: str) -> str:
        if is_free_cell_text(cell):
            return cell
        identity_map = self._identity_override_map(self.music_name_overrides)
        identity = self._music_track_key(cell)
        if identity in identity_map:
            return identity_map[identity]
        return self.music_name_overrides.get(
            cell,
            self.music_name_overrides.get(canonical_music_name(cell), cell),
        )

    def _apply_music_name_overrides(self, matrix: list[list[str]]) -> list[list[str]]:
        if not self.music_name_overrides:
            return matrix
        return [
            [self._resolve_music_cell_text(cell) for cell in row] for row in matrix
        ]

    def _collect_music_names(self, cards: list[dict]) -> list[str]:
        identity_to_display: dict[str, str] = {}
        for card in cards:
            matrix = card.get("songs_matrix") or []
            for row in matrix:
                for song_name in row:
                    if is_free_cell_text(song_name):
                        continue
                    identity = self._music_track_key(song_name)
                    if identity and identity not in identity_to_display:
                        identity_to_display[identity] = song_name.strip()
        return sorted(identity_to_display.values(), key=str.casefold)

    def _open_music_name_editor(self, tutorial_mode: bool = False):
        if (
            tutorial_mode
            and self._tutorial_music_editor_dialog
            and self._tutorial_music_editor_dialog.winfo_exists()
        ):
            self._tutorial_music_editor_dialog.lift()
            self._tutorial_music_editor_dialog.focus_force()
            return

        names: list[str]
        if tutorial_mode:
            names = self._tutorial_music_editor_sample_names()
            if self.pdf_path is not None:
                try:
                    cards = self._get_cached_valid_cards()
                    collected = self._collect_music_names(cards)
                    if collected:
                        names = collected
                except Exception:
                    pass
        else:
            if self.pdf_path is None:
                messagebox.showwarning(
                    "Missing PDF",
                    "Please import from Spotify playlist first.",
                )
                return
            try:
                cards = self._get_cached_valid_cards()
            except Exception as error:
                messagebox.showerror(
                    "PDF Error", f"Could not parse songs from PDF:\n{error}"
                )
                return
            if not cards:
                messagebox.showwarning(
                    "No Songs Found", "No songs were extracted from the PDF."
                )
                return

            names = self._collect_music_names(cards)
            if not names:
                messagebox.showwarning(
                    "No Songs Found", "No songs were extracted from the PDF."
                )
                return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Music Names")
        dialog.geometry("920x700")
        dialog.transient(self)
        if not tutorial_mode:
            dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        if tutorial_mode:
            self._tutorial_music_editor_dialog = dialog

            def _clear_tutorial_music_dialog_ref(_event=None):
                if self._tutorial_music_editor_dialog is dialog:
                    self._tutorial_music_editor_dialog = None

            dialog.bind("<Destroy>", _clear_tutorial_music_dialog_ref, add="+")

        header_text = "Update song names before generating cards"
        if tutorial_mode and self.pdf_path is None:
            header_text = "Tutorial preview — import a playlist to edit real song names"
        ctk.CTkLabel(
            dialog,
            text=header_text,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        scroll = ctk.CTkScrollableFrame(dialog, corner_radius=10)
        scroll.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_columnconfigure(1, weight=1)

        entry_vars: dict[str, tk.StringVar] = {}
        for index, original_name in enumerate(names):
            ctk.CTkLabel(
                scroll,
                text=original_name,
                anchor="w",
                wraplength=360,
            ).grid(row=index, column=0, padx=(8, 8), pady=4, sticky="ew")
            current_value = self._music_override_value_for(original_name)
            value_var = tk.StringVar(value=current_value)
            entry_vars[original_name] = value_var
            ctk.CTkEntry(scroll, textvariable=value_var).grid(
                row=index, column=1, padx=(8, 8), pady=4, sticky="ew"
            )

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        actions.grid_columnconfigure(2, weight=1)

        def reset_changes():
            for original_name, value_var in entry_vars.items():
                value_var.set(original_name)

        def save_changes():
            updated_overrides: dict[str, str] = {}
            for original_name, value_var in entry_vars.items():
                updated_name = value_var.get().strip()
                if not updated_name:
                    updated_name = original_name
                if updated_name != original_name:
                    updated_overrides[original_name] = updated_name
            if not tutorial_mode:
                self.music_name_overrides = self._expand_music_name_overrides(
                    updated_overrides
                )
                self._invalidate_preview_caches()
            dialog.destroy()
            if not tutorial_mode:
                self._schedule_preview_refresh()
                messagebox.showinfo(
                    "Music Names Updated",
                    f"Saved {len(updated_overrides)} replacement(s).",
                )

        ctk.CTkButton(
            actions,
            text="Reset",
            command=reset_changes,
            fg_color="#6b7280",
            hover_color="#4b5563",
            width=140,
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Cancel",
            command=dialog.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
            width=140,
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(
            actions,
            text="Apply",
            command=save_changes,
            fg_color="#16a34a",
            hover_color="#15803d",
            width=140,
        ).grid(row=0, column=2, padx=(8, 0), sticky="ew")

    def _serialize_state(self) -> dict:
        return {
            "template_path": str(self.template_path) if self.template_path else None,
            "pdf_path": str(self.pdf_path) if self.pdf_path else None,
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "text_color": self.text_color_var.get(),
            "font_size": int(self.font_size_var.get()),
            "text_offset_x": int(self.text_offset_x_var.get()),
            "text_offset_y": int(self.text_offset_y_var.get()),
            "free_icon_size": float(self.free_icon_size_var.get()),
            "free_icon_path": str(self.free_icon_path) if self.free_icon_path else None,
            "pdf_layout": self.pdf_layout,
            "grid_x": int(self.grid_x_var.get()),
            "grid_y": int(self.grid_y_var.get()),
            "grid_cell_width": int(self.grid_cell_width_var.get()),
            "grid_cell_height": int(self.grid_cell_height_var.get()),
            "show_grid_overlay": bool(self.show_grid_overlay_var.get()),
            "music_name_overrides": dict(self.music_name_overrides),
            "playlist_tracks": [
                {
                    "id": track.get("id"),
                    "name": track.get("name"),
                    "artist": track.get("artist"),
                }
                for track in self.playlist_tracks
            ],
            "playlist_include_artist": bool(self.playlist_include_artist),
            "spotify_playlist_url": self.spotify_playlist_url_var.get().strip(),
            "spotify_grid_size": self.spotify_grid_size_var.get(),
            "spotify_card_count": int(self.spotify_card_count_var.get()),
            "spotify_include_artist": bool(self.spotify_include_artist_var.get()),
            "spotify_free_center": bool(self.spotify_free_center_var.get()),
            "text_settings_expanded": bool(self.text_settings_expanded),
            "grid_settings_expanded": bool(self.grid_settings_expanded),
            "tutorial_seen": bool(self.tutorial_seen),
        }

    def _save_state(self):
        if self._loading_state:
            return
        try:
            APP_STATE_PATH.write_text(
                json.dumps(self._serialize_state(), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_state(self):
        if not APP_STATE_PATH.exists():
            return
        try:
            state = json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return

        self._loading_state = True
        try:
            self.text_color_var.set(state.get("text_color", "#000000"))
            self.font_size_var.set(int(state.get("font_size", 26)))
            text_offset_y = int(
                state.get("text_offset_y", state.get("text_y_padding", 0))
            )
            self.text_offset_x_var.set(int(state.get("text_offset_x", 0)))
            self.text_offset_y_var.set(text_offset_y)
            self.free_icon_size_var.set(
                float(state.get("free_icon_size", FREE_ICON_SIZE_DEFAULT))
            )
            free_icon_path = state.get("free_icon_path")
            if free_icon_path and Path(free_icon_path).exists():
                self.free_icon_path = Path(free_icon_path)
            else:
                self.free_icon_path = None
            self.free_icon_path_label.configure(text=self._format_free_icon_label())
            saved_pdf_layout = state.get("pdf_layout")
            if saved_pdf_layout in SUPPORTED_GRID_SIZES:
                self.pdf_layout = int(saved_pdf_layout)
                self._update_pdf_layout_label()
            self._pending_legacy_grid_offsets = None
            if "grid_x" in state or "grid_y" in state:
                self.grid_x_var.set(int(state.get("grid_x", 0)))
                self.grid_y_var.set(int(state.get("grid_y", 0)))
            else:
                self._pending_legacy_grid_offsets = (
                    int(state.get("grid_offset_x", 0)),
                    int(state.get("grid_offset_y", 0)),
                )
            self._pending_legacy_cell_adjustments = None
            if "grid_cell_width" in state or "grid_cell_height" in state:
                self.grid_cell_width_var.set(int(state.get("grid_cell_width", 120)))
                self.grid_cell_height_var.set(int(state.get("grid_cell_height", 120)))
            else:
                self._pending_legacy_cell_adjustments = (
                    int(state.get("manual_cell_width", 0)),
                    int(state.get("manual_cell_height", 0)),
                )
            self.show_grid_overlay_var.set(bool(state.get("show_grid_overlay", True)))
            self.spotify_playlist_url_var.set(
                str(state.get("spotify_playlist_url", "")).strip()
            )
            self.spotify_grid_size_var.set(str(state.get("spotify_grid_size", "5x5")))
            self.spotify_card_count_var.set(int(state.get("spotify_card_count", 20)))
            self.spotify_include_artist_var.set(
                bool(state.get("spotify_include_artist", False))
            )
            self.spotify_free_center_var.set(
                bool(state.get("spotify_free_center", True))
            )
            saved_overrides = state.get("music_name_overrides", {})
            if isinstance(saved_overrides, dict):
                self.music_name_overrides = {
                    str(original): str(updated)
                    for original, updated in saved_overrides.items()
                    if str(original).strip() and str(updated).strip()
                }
            else:
                self.music_name_overrides = {}

            saved_tracks = state.get("playlist_tracks", [])
            if isinstance(saved_tracks, list):
                self.playlist_tracks = [
                    {
                        "id": entry.get("id"),
                        "name": str(entry.get("name", "")),
                        "artist": str(entry.get("artist", "")),
                    }
                    for entry in saved_tracks
                    if isinstance(entry, dict) and str(entry.get("name", "")).strip()
                ]
            else:
                self.playlist_tracks = []
            self.playlist_include_artist = bool(
                state.get("playlist_include_artist", False)
            )

            output_dir = state.get("output_dir")
            if output_dir:
                output_path = Path(output_dir)
                self.output_dir = output_path
            self.output_folder_button.configure(text=self._format_output_button_text())

            if state.get("text_settings_expanded"):
                self.text_settings_expanded = False
                self._toggle_text_settings()

            if state.get("grid_settings_expanded"):
                self.grid_settings_expanded = False
                self._toggle_grid_settings()
            self.tutorial_seen = bool(state.get("tutorial_seen", False))

            template_path = state.get("template_path")
            if template_path and Path(template_path).exists():
                self._load_template_file(Path(template_path), show_error=False)

            pdf_path = state.get("pdf_path")
            if pdf_path and Path(pdf_path).exists():
                self._load_pdf_file(Path(pdf_path), show_error=False)
                saved_overrides = state.get("music_name_overrides", {})
                if isinstance(saved_overrides, dict):
                    self.music_name_overrides = {
                        str(original): str(updated)
                        for original, updated in saved_overrides.items()
                        if str(original).strip() and str(updated).strip()
                    }
                self._refresh_music_name_override_aliases()
        finally:
            self._loading_state = False

        self._customize_undo_stack.clear()
        self._customize_redo_stack.clear()
        self._clear_customize_action_group()
        self._update_customize_undo_redo_buttons()
        self._flush_preview_refresh()

    def _on_close(self):
        self._flush_preview_refresh()
        self._flush_save_state()
        self.destroy()


if __name__ == "__main__":
    app = BingoDesktopApp()
    app.mainloop()
