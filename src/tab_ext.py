#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from utils import collect_files, combine_files_with_annotations, strip_empty_lines, split_text_by_tokens, copy_to_clipboard

class ScanByExtensionTab(ttk.Frame):
    def __init__(self, master, themed_text_kwargs):
        super().__init__(master)
        self._themed_text_kwargs = dict(themed_text_kwargs)

        top = ttk.Frame(self); top.pack(fill="x", pady=(8, 4))
        ttk.Button(top, text="Add Folder + Extension", command=self._add_pair).pack(side="left")
        ttk.Button(top, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Clear All", command=self._clear_all).pack(side="left", padx=(8, 0))

        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, pady=(4, 4))
        self.listbox = tk.Listbox(mid, height=12, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        self._apply_text_theme(self.listbox)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", padx=2, pady=(6, 4))
        self.strip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Strip empty/whitespace-only lines", variable=self.strip_var).pack(anchor="w", padx=6, pady=4)
        row = ttk.Frame(opts); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tokens = ttk.Entry(row, width=10); self.tokens.pack(side="left", padx=6)

        bottom = ttk.Frame(self); bottom.pack(fill="x", pady=(4, 2))
        ttk.Button(bottom, text="Scan & Copy to Clipboard", command=self._run).pack(side="left")

        self.status = tk.Text(self, height=10)
        self.status.pack(fill="both", expand=False, pady=(6, 8))
        self._apply_text_theme(self.status)
        self._set_readonly(self.status)

    def _apply_text_theme(self, widget):
        try:
            widget.configure(**self._themed_text_kwargs)
        except Exception:
            pass

    def _add_pair(self):
        folder = filedialog.askdirectory(title="Choose folder")
        if not folder:
            return
        win = tk.Toplevel(self)
        win.title("Choose Extension")
        ttk.Label(win, text="File extension (with or without dot):").pack(padx=10, pady=(10, 4))
        entry = ttk.Entry(win); entry.insert(0, ".py"); entry.pack(padx=10, pady=4)
        def ok():
            ext = entry.get().strip()
            if ext and not ext.startswith("."): ext = "." + ext
            if not ext:
                messagebox.showerror("Error", "Please provide an extension.")
                return
            self.listbox.insert("end", f"{folder} || {ext}")
            win.destroy()
        ttk.Button(win, text="OK", command=ok).pack(pady=(6, 10))
        entry.focus_set()

    def _remove_selected(self):
        sel = list(self.listbox.curselection()); sel.reverse()
        for i in sel: self.listbox.delete(i)

    def _clear_all(self):
        self.listbox.delete(0, "end")

    def _run(self):
        pairs = []
        for i in range(self.listbox.size()):
            item = self.listbox.get(i)
            if "||" in item:
                folder, ext = [s.strip() for s in item.split("||", 1)]
                if os.path.isdir(folder) and ext:
                    pairs.append((folder, ext))
        if not pairs:
            messagebox.showwarning("No selections", "Add at least one folder + extension pair.")
            return

        self._set_status("Scanning folders...\n")
        files = collect_files(pairs)
        self._append_status(f"Found {len(files)} files.\n")
        if not files:
            return

        combined = combine_files_with_annotations(files)
        if self.strip_var.get():
            combined = strip_empty_lines(combined)

        max_tokens = self._parse_int_entry(self.tokens)
        chunks = split_text_by_tokens(combined, max_tokens)
        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self._append_status("Copied everything in one chunk to clipboard.\n")
        else:
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                self._append_status(f"Copied chunk {idx}/{len(chunks)}. Paste now, then press OK.\n")
                if idx != len(chunks):
                    from tkinter import messagebox as mb
                    mb.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self._append_status("All chunks copied.\n")

    def _parse_int_entry(self, entry: ttk.Entry):
        raw = entry.get().strip()
        if not raw: return None
        try:
            v = int(raw); return v if v > 0 else None
        except ValueError:
            from tkinter import messagebox as mb
            mb.showwarning("Invalid number", f"'{raw}' is not a valid integer; proceeding without chunking.")
            return None

    def _set_readonly(self, text_widget: tk.Text):
        text_widget.config(state="disabled", wrap="word")

    def _set_status(self, text: str):
        self.status.config(state="normal"); self.status.delete("1.0", "end"); self.status.insert("1.0", text); self.status.config(state="disabled")

    def _append_status(self, text: str):
        self.status.config(state="normal"); self.status.insert("end", text); self.status.see("end"); self.status.config(state="disabled")
