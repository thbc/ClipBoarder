#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from utils import combine_files_with_annotations, strip_empty_lines, split_text_by_tokens, copy_to_clipboard

class DropCompileTab(ttk.Frame):
    def __init__(self, master, themed_text_kwargs, tkdnd_enabled=False, dnd_files=None):
        super().__init__(master)
        self._themed_text_kwargs = dict(themed_text_kwargs)  # for Text widgets
        self.tkdnd_enabled = tkdnd_enabled
        self.dnd_files = dnd_files

        info = ttk.LabelFrame(self, text="Instructions")
        info.pack(fill="x", padx=4, pady=6)
        ttk.Label(
            info,
            text=("Drag & drop files below (if enabled), or click 'Add Files…'.\n"
                  "Then click 'Compile/Copy' to copy annotated content to clipboard.")
        ).pack(anchor="w", padx=6, pady=6)

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=4)
        self.listbox = tk.Listbox(mid, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        self._apply_text_theme(self.listbox)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.listbox.yview)
        sb.pack(side="left", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        # DnD
        if self.tkdnd_enabled and self.dnd_files:
            self.listbox.drop_target_register(self.dnd_files)
            self.listbox.dnd_bind("<<Drop>>", self._on_drop)

        side = ttk.Frame(mid); side.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(side, text="Add Files…", command=self._add_files).pack(fill="x")
        ttk.Button(side, text="Remove Selected", command=self._remove_selected).pack(fill="x", pady=(6, 0))
        ttk.Button(side, text="Clear All", command=self._clear).pack(fill="x", pady=(6, 0))

        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", padx=4, pady=(6, 4))
        self.strip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Strip empty/whitespace-only lines", variable=self.strip_var).pack(anchor="w", padx=6, pady=4)

        row = ttk.Frame(opts); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tokens = ttk.Entry(row, width=10)
        self.tokens.pack(side="left", padx=6)

        actions = ttk.Frame(self); actions.pack(fill="x", padx=4, pady=(6, 8))
        ttk.Button(actions, text="Compile/Copy", command=self._run).pack(side="left")

        self.status = tk.Text(self, height=8)
        self.status.pack(fill="both", expand=False, padx=4, pady=(0, 8))
        self._apply_text_theme(self.status)
        self._set_readonly(self.status)

    def _apply_text_theme(self, widget):
        try:
            widget.configure(**self._themed_text_kwargs)
        except Exception:
            pass

    def _on_drop(self, event):
        raw = event.data
        # tkinterdnd2 provides already-split paths in most cases; keep it simple
        paths = self.tk.splitlist(raw)
        added = 0
        for p in paths:
            if os.path.isfile(p) and p not in self.listbox.get(0, "end"):
                self.listbox.insert("end", p)
                added += 1
        self._set_status(f"Added {added} file(s) via drag-and-drop.\n")

    def _add_files(self):
        files = filedialog.askopenfilenames(title="Choose files")
        for f in files:
            if f not in self.listbox.get(0, "end"):
                self.listbox.insert("end", f)

    def _remove_selected(self):
        sel = list(self.listbox.curselection())
        sel.reverse()
        for i in sel:
            self.listbox.delete(i)

    def _clear(self):
        self.listbox.delete(0, "end")

    def _run(self):
        files = list(self.listbox.get(0, "end"))
        if not files:
            messagebox.showwarning("No Files", "Add some files first.")
            return
        self._set_status(f"Found {len(files)} staged file(s).\n")

        combined = combine_files_with_annotations(files)
        if self.strip_var.get():
            combined = strip_empty_lines(combined)

        max_tokens = self._parse_int_entry(self.tokens)
        chunks = split_text_by_tokens(combined, max_tokens)
        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self._append_status("Copied all content in one go.\n")
        else:
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                self._append_status(f"Copied chunk {idx}/{len(chunks)}. Paste now, then press OK.\n")
                if idx != len(chunks):
                    messagebox.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self._append_status("All chunks copied.\n")

    # utilities
    def _parse_int_entry(self, entry: ttk.Entry):
        raw = entry.get().strip()
        if not raw:
            return None
        try:
            v = int(raw)
            return v if v > 0 else None
        except ValueError:
            messagebox.showwarning("Invalid number", f"'{raw}' is not a valid integer; proceeding without chunking.")
            return None

    def _set_readonly(self, text_widget: tk.Text):
        text_widget.config(state="disabled", wrap="word")

    def _set_status(self, text: str):
        self.status.config(state="normal"); self.status.delete("1.0", "end"); self.status.insert("1.0", text); self.status.config(state="disabled")

    def _append_status(self, text: str):
        self.status.config(state="normal"); self.status.insert("end", text); self.status.see("end"); self.status.config(state="disabled")
