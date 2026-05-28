import os
import tkinter as tk
from ctypes import wintypes
import ctypes

import customtkinter as ctk
from PIL import Image, ImageTk

from bingo_cards.ui.toolbar_icons import dim_toolbar_icon


def get_windows_work_area() -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    rect = wintypes.RECT()
    SPI_GETWORKAREA = 0x0030
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
    )
    if not ok:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


class HoverToolTip:
    def __init__(self, widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._tip_window: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event=None):
        self._cancel_schedule()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel_schedule(self) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        label = tk.Label(
            tip,
            text=self.text,
            justify="center",
            background="#111827",
            foreground="#f9fafb",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            padx=8,
            pady=4,
            font=("Segoe UI", 9),
        )
        label.pack()
        tip.update_idletasks()
        tip_width = tip.winfo_width()
        tip.wm_geometry(f"+{max(0, x - tip_width // 2)}+{y}")
        self._tip_window = tip

    def _on_leave(self, _event=None):
        self._cancel_schedule()
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


class IconToolbarButton(ctk.CTkFrame):
    """Icon-only toolbar control using tk.PhotoImage (avoids CTkImage scaling bugs)."""

    def __init__(
        self,
        master,
        pil_image: Image.Image,
        command,
        size: int = 36,
        fg_color: str = "#374151",
        hover_color: str = "#4b5563",
        disabled_color: str = "#1f2937",
        pil_image_disabled: Image.Image | None = None,
        state: str = "normal",
        corner_radius: int = 6,
        **kwargs,
    ):
        super().__init__(
            master,
            width=size,
            height=size,
            fg_color=fg_color,
            corner_radius=corner_radius,
            **kwargs,
        )
        self.grid_propagate(False)
        self.pack_propagate(False)
        self._command = command
        self._fg_color = fg_color
        self._hover_color = hover_color
        self._disabled_color = disabled_color
        self._state = state
        self._photo_enabled = ImageTk.PhotoImage(pil_image)
        self._photo_disabled = ImageTk.PhotoImage(pil_image)
        self._icon_label = tk.Label(
            self,
            image=self._photo_enabled,
            borderwidth=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self._icon_label.place(relx=0.5, rely=0.5, anchor="center")
        for widget in (self, self._icon_label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)
        self.set_icon_images(pil_image, pil_image_disabled)
        self._state = state
        self._apply_state()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "state" in kwargs:
            self._state = kwargs.pop("state")
        if "fg_color" in kwargs:
            self._fg_color = kwargs.pop("fg_color")
        if "hover_color" in kwargs:
            self._hover_color = kwargs.pop("hover_color")
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "pil_image" in kwargs:
            pil_image = kwargs.pop("pil_image")
            self.set_icon_images(pil_image, kwargs.pop("pil_image_disabled", None))
        if "pil_image_disabled" in kwargs:
            self.set_icon_images(
                kwargs.pop("pil_image", self._pil_image_enabled),
                kwargs.pop("pil_image_disabled"),
            )
        self._apply_state()
        super().configure(**kwargs)

    def set_icon_images(
        self,
        enabled_image: Image.Image,
        disabled_image: Image.Image | None = None,
    ) -> None:
        self._pil_image_enabled = enabled_image
        self._pil_image_disabled = (
            disabled_image
            if disabled_image is not None
            else dim_toolbar_icon(enabled_image)
        )
        self._photo_enabled = ImageTk.PhotoImage(self._pil_image_enabled)
        self._photo_disabled = ImageTk.PhotoImage(self._pil_image_disabled)
        self._apply_state()

    def cget(self, key):
        if key == "state":
            return self._state
        return super().cget(key)

    def _current_bg(self) -> str:
        if self._state == "disabled":
            return self._disabled_color
        return self._fg_color

    def _apply_state(self) -> None:
        bg = self._current_bg()
        is_disabled = self._state == "disabled"
        super().configure(fg_color=bg)
        self._icon_label.configure(
            image=self._photo_disabled if is_disabled else self._photo_enabled,
            bg=bg,
            cursor="arrow" if is_disabled else "hand2",
        )

    def _on_enter(self, _event=None) -> None:
        if self._state != "disabled":
            super().configure(fg_color=self._hover_color)
            self._icon_label.configure(bg=self._hover_color)

    def _on_leave(self, _event=None) -> None:
        self._apply_state()

    def _on_click(self, _event=None) -> None:
        if self._state != "disabled" and self._command:
            self._command()
