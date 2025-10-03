#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from utils import guess_csharp_regex_from_text, find_cs_references_with_context, split_text_by_tokens, copy_to_clipboard

class FindCsRefsTab(ttk.Frame):
    def __init__(self, master, themed_text_kwargs):
        super().__init__(master)
        self._themed_text_kwargs = dict(themed_text_kwargs)

        top = ttk.LabelFrame(self, text="Search Settings")
        top.pack(fill="x", padx=4, pady=6)

        r1 = ttk.Frame(top); r1.pack(fill="x", padx=6, pady=4)
        ttk.Label(r1, text="Root folder:").pack(side="left")
        self.root_entry = ttk.Entry(r1); self.root_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r1, text="Browse…", command=self._browse_root).pack(side="left")

        r2 = ttk.Frame(top); r2.pack(fill="x", padx=6, pady=4)
        ttk.Label(r2, text="Search text:").pack(side="left")
        self.user_text = ttk.Entry(r2)
        self.user_text.pack(side="left", fill="x", expand=True, padx=6)
        self.user_text.bind("<KeyRelease>", lambda e: self._auto_update_regex())

        r3 = ttk.Frame(top); r3.pack(fill="x", padx=6, pady=4)
        ttk.Label(r3, text="Generated regex:").pack(side="left")
        self.regex_entry = ttk.Entry(r3)
        self.regex_entry.pack(side="left", fill="x", expand=True, padx=6)

        r4 = ttk.Frame(top); r4.pack(fill="x", padx=6, pady=4)
        ttk.Label(r4, text="Lines before:").pack(side="left")
        self.before = ttk.Spinbox(r4, from_=0, to=50, width=5)
        self.before.delete(0, "end"); self.before.insert(0, "3")
        self.before.pack(side="left", padx=(6, 12))
        ttk.Label(r4, text="Lines after:").pack(side="left")
        self.after = ttk.Spinbox(r4, from_=0, to=50, width=5)
        self.after.delete(0, "end"); self.after.insert(0, "3")
        self.after.pack(side="left", padx=(6, 12))

        r5 = ttk.Frame(top); r5.pack(fill="x", padx=6, pady=4)
        ttk.Label(r5, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tokens = ttk.Entry(r5, width=10); self.tokens.pack(side="left", padx=6)

        actions = ttk.Frame(self); actions.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Button(actions, text="Search & Copy", command=self._run).pack(side="left")

        prev = ttk.LabelFrame(self, text="Preview (first 50 lines of results)")
        prev.pack(fill="both", expand=True, padx=4, pady=(4, 8))
        self.preview = tk.Text(prev, height=18)
        self.preview.pack(fill="both", expand=True)
        self._apply_text_theme(self.preview)
        self._set_readonly(self.preview)

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status).pack(anchor="w", padx=6, pady=(0, 8))

    def _apply_text_theme(self, widget):
        try:
            widget.configure(**self._themed_text_kwargs)
        except Exception:
            pass

    def _browse_root(self):
        folder = filedialog.askdirectory(title="Choose root folder (C# project)")
        if folder:
            self.root_entry.delete(0, "end")
            self.root_entry.insert(0, folder)

    def _auto_update_regex(self):
        text = (self.user_text.get() or "").strip()
        regex = guess_csharp_regex_from_text(text)
        self.regex_entry.delete(0, "end")
        self.regex_entry.insert(0, regex)

    def _run(self):
        root = (self.root_entry.get() or os.getcwd()).strip()
        if not os.path.isdir(root):
            messagebox.showerror("Invalid Folder", "Root folder is not a directory.")
            return

        pattern = (self.regex_entry.get() or "").strip()
        if not pattern:
            # last-ditch: generate from user text now
            pattern = guess_csharp_regex_from_text((self.user_text.get() or "").strip())
            if not pattern:
                messagebox.showwarning("Missing Pattern", "Enter search text to generate a regex.")
                return

        try:
            before = int(self.before.get()); after = int(self.after.get())
        except ValueError:
            messagebox.showerror("Invalid Context", "Before/After must be integers.")
            return

        self.status.set("Searching… this may take a moment.")
        self.update_idletasks()

        try:
            snippets = find_cs_references_with_context(root, pattern, before=before, after=after)
        except ValueError as e:
            messagebox.showerror("Regex Error", str(e))
            self.status.set("")
            return

        if not snippets:
            self.status.set("No references found for that pattern.")
            self._set_text(self.preview, "")
            return

        combined = "\n\n".join(snippets)
        preview = "\n".join(combined.splitlines()[:50])
        if len(combined.splitlines()) > 50:
            preview += "\n… (truncated in preview)"
        self._set_text(self.preview, preview)

        # Chunk & copy
        raw = self.tokens.get().strip()
        max_tokens = int(raw) if raw.isdigit() and int(raw) > 0 else None
        chunks = split_text_by_tokens(combined, max_tokens)
        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self.status.set(f"Copied {len(snippets)} snippet block(s) to clipboard.")
        else:
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                if idx != len(chunks):
                    messagebox.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self.status.set(f"Copied {len(snippets)} snippet block(s) to clipboard in {len(chunks)} chunks.")

    # text helpers
    def _set_readonly(self, text_widget: tk.Text):
        text_widget.config(state="disabled", wrap="word")

    def _set_text(self, text_widget: tk.Text, text: str):
        text_widget.config(state="normal"); text_widget.delete("1.0", "end"); text_widget.insert("1.0", text); text_widget.config(state="disabled")
