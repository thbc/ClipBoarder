#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import tkinter as tk
from tkinter import ttk, messagebox
from utils import apply_dark_theme, apply_light_theme, get_tokenizer
from tab_drop import DropCompileTab
from tab_ext import ScanByExtensionTab
from tab_refs import FindCsRefsTab

# Optional tkinterdnd2
try:
    import tkinterdnd2 as tkdnd
    TKDND_AVAILABLE = True
    BaseTk = tkdnd.Tk
    DND_FILES = tkdnd.DND_FILES
except Exception:
    TKDND_AVAILABLE = False
    BaseTk = tk.Tk
    DND_FILES = None

APP_TITLE = "Clipboarder GUI"


# --- add near the top of app.py (after imports) ---
import sys

def _enable_windows_dpi_awareness():
    """Make Tk DPI-aware on Windows to avoid blurry scaling."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                # Windows 8.1+ (per-monitor DPI awareness)
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            except Exception:
                # Fallback (Vista+)
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x720")
        self.minsize(900, 580)

        # Theme (dark default)
        self._text_style_kwargs = apply_dark_theme(self, ttk)
        self._current_theme = "dark"

        self._build_menu()

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=8)

        # Tabs in the NEW order:
        # 1) Drop → Compile/Copy
        self.tab1 = DropCompileTab(nb, self._text_style_kwargs, tkdnd_enabled=TKDND_AVAILABLE, dnd_files=DND_FILES)
        # 2) Scan Folders by Extension
        self.tab2 = ScanByExtensionTab(nb, self._text_style_kwargs)
        # 3) Find C# References (auto-regex)
        self.tab3 = FindCsRefsTab(nb, self._text_style_kwargs)

        nb.add(self.tab1, text="Drop → Compile/Copy")
        nb.add(self.tab2, text="Scan Folders by Extension")
       # nb.add(self.tab3, text="Find C# References")

        # gentle info messages about optional deps
        if get_tokenizer() is None:
            self.after(200, lambda: messagebox.showinfo(
                "Optional Dependency",
                "Install 'tiktoken' for token-based chunking.\n\npip install tiktoken"
            ))

    def _build_menu(self):
        m = tk.Menu(self)
        filemenu = tk.Menu(m, tearoff=False)
        filemenu.add_command(label="Quit", command=self.destroy, accelerator="Ctrl+Q")
        m.add_cascade(label="File", menu=filemenu)

        viewmenu = tk.Menu(m, tearoff=False)
        viewmenu.add_command(label="Dark Mode (default)", command=self._set_dark)
        viewmenu.add_command(label="Light Mode", command=self._set_light)
        m.add_cascade(label="View", menu=viewmenu)

        helpmenu = tk.Menu(m, tearoff=False)
        helpmenu.add_command(label="About", command=lambda: messagebox.showinfo(
            "About",
            f"{APP_TITLE}\nA simple GUI wrapper for your multi-mode clipboard tool."
        ))
        m.add_cascade(label="Help", menu=helpmenu)
        self.config(menu=m)
        self.bind_all("<Control-q>", lambda e: self.destroy())

    def _set_dark(self):
        if self._current_theme == "dark":
            return
        self._text_style_kwargs = apply_dark_theme(self, ttk)
        self._retint_text_widgets()
        self._current_theme = "dark"

    def _set_light(self):
        if self._current_theme == "light":
            return
        self._text_style_kwargs = apply_light_theme(self, ttk)
        self._retint_text_widgets()
        self._current_theme = "light"

    def _retint_text_widgets(self):
        """Re-apply text colors to text-like widgets in tabs."""
        for w in (self.tab1.listbox, self.tab1.status, self.tab2.listbox, self.tab2.status, self.tab3.preview):
            try:
                w.configure(**self._text_style_kwargs)
            except Exception:
                pass

def main():
    _enable_windows_dpi_awareness()
    app = App()
    # Optional: fine-tune Tk's internal scaling (1.0=100%, 1.25=125%)
    try:
        app.tk.call("tk", "scaling", 1.0)  # adjust if you want bigger UI: 1.25 or 1.5
    except Exception:
        pass
    app.mainloop()

if __name__ == "__main__":
    main()
