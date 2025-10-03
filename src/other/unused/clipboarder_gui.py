#!/usr/bin/env python3
"""
Clipboarder GUI

A Tkinter GUI for:
  1) Copy files by extension from multiple selected folders (with filename annotations)
  2) Find C# references (regex) with N lines of context around matches
  3) Drop files to compile/copy (drag-and-drop if tkinterdnd2 is available)

Features:
  - Optional token-based chunking if 'tiktoken' is available (model: gpt-4o)
  - Optional strip-empty-lines in modes 1 & 3 (as in the CLI)
  - File paths in snippet headers for mode 2 are relative to the chosen root
  - Clipboard copy via 'pyperclip' (fallback to Tk clipboard if unavailable)
  - Drag-and-drop for Mode 3 using 'tkinterdnd2' if installed

Dependencies (optional):
  pip install pyperclip tiktoken tkinterdnd2

Packaging (example):
  pyinstaller --onefile --name Clipboarder-GUI ./clipboarder_gui.py --collect-all tiktoken
"""

import os
import re
import sys
import shlex
from urllib.parse import urlparse, unquote
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pyperclip

try:
    import tkinterdnd2 as tkdnd
    TKDND_AVAILABLE = True
    BaseTk = tkdnd.Tk             
    DND_FILES = tkdnd.DND_FILES
except Exception:
    TKDND_AVAILABLE = False
    BaseTk = tk.Tk                 
    DND_FILES = None

# Lazy tiktoken setup that never raises NameError
_TOKENIZER_SENTINEL = object()
TOKENIZER = _TOKENIZER_SENTINEL  # will become an encoder, None, or remain sentinel

def get_tokenizer():
    """Return a tiktoken encoder or None. Never raises if tiktoken is missing."""
    global TOKENIZER
    if TOKENIZER is not _TOKENIZER_SENTINEL:
        return TOKENIZER  # already resolved to encoder or None
    try:
        import tiktoken  # local import so the app works without it
        TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    except Exception:
        TOKENIZER = None
    return TOKENIZER

# --------------------------
# Shared helpers
# --------------------------
def copy_to_clipboard(text: str, tk_root: tk.Tk) -> None:
    """Copy text to clipboard, using pyperclip if available, else Tk."""
    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            return
        except Exception:
            pass
    try:
        tk_root.clipboard_clear()
        tk_root.clipboard_append(text)
        tk_root.update()  # keep clipboard after app closes on macOS
    except Exception as e:
        messagebox.showerror("Clipboard Error", f"Failed to copy to clipboard:\n{e}")
def split_text_by_tokens(text: str, max_tokens: int):
    """Chunk text by token count if tiktoken is available; else return [text]."""
    if not max_tokens or max_tokens <= 0:
        return [text]

    tok = get_tokenizer()
    if tok is None:
        # Optional: show one-time warning if you want
        try:
            from tkinter import messagebox
            messagebox.showwarning(
                "tiktoken not available",
                "tiktoken is not installed; copying everything in one chunk."
            )
        except Exception:
            pass
        return [text]

    lines = text.splitlines(keepends=True)
    chunks, current = [], ""
    for line in lines:
        if len(tok.encode(current + line)) <= max_tokens:
            current += line
        else:
            if current:
                chunks.append(current)
            if len(tok.encode(line)) > max_tokens:
                chunks.append(line)  # oversize single line becomes its own chunk
                current = ""
            else:
                current = line
    if current:
        chunks.append(current)
    return chunks


def strip_empty_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip())


def combine_files_with_annotations(file_paths):
    """Read each file, prepend annotation '# ===== File: name =====' and concat."""
    sections = []
    for path in file_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            sections.append(f"# ===== File: {os.path.basename(path)} =====\n"
                            f"[Warning: Could not read '{path}': {e}]")
            continue
        sections.append(f"# ===== File: {os.path.basename(path)} =====\n{content}")
    return "\n\n".join(sections)


def collect_files(folder_ext_pairs):
    """Walk each folder recursively and collect files matching its extension."""
    all_files = []
    for folder, ext in folder_ext_pairs:
        for root, _, files in os.walk(folder):
            for fname in files:
                if fname.endswith(ext):
                    all_files.append(os.path.join(root, fname))
    return sorted(all_files)


def find_references_with_context(root_folder, pattern, before=3, after=3):
    """Search .cs files for regex pattern and return list of context snippets."""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}") from e

    snippets = []
    for dirpath, _, filenames in os.walk(root_folder):
        for fname in filenames:
            if not fname.lower().endswith(".cs"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except OSError:
                continue

            for idx, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, idx - before)
                    end = min(len(lines), idx + after + 1)
                    snippet_lines = []
                    snippet_lines.append("=" * 80)
                    rel_path = os.path.relpath(path, root_folder)
                    snippet_lines.append(f"{rel_path} (line {idx+1}):")
                    for i in range(start, end):
                        prefix = ">>" if i == idx else "  "
                        num = str(i + 1).rjust(4)
                        snippet_lines.append(f"{prefix} {num}: {lines[i].rstrip()}")
                    snippet_lines.append("")
                    snippets.append("\n".join(snippet_lines))
    return snippets


# --------- Drop mode path parsing (from your CLI) ----------
def _normalize_dropped_path(p):
    p = p.strip()
    try:
        parsed = urlparse(p)
    except Exception:
        parsed = None

    if parsed and parsed.scheme == "file":
        p = unquote(parsed.path or "")
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", p):
            p = p.lstrip("/")
    else:
        p = unquote(p)

    p = os.path.expanduser(p)
    return os.path.abspath(p)


def _parse_dropped_input(line: str):
    if not line.strip():
        return []
    try:
        tokens = shlex.split(line, posix=(os.name != "nt"))
    except Exception:
        tokens = line.split()
    return [_normalize_dropped_path(tok) for tok in tokens]


# --------------------------
# GUI app
# --------------------------
class ClipboarderGUI(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Clipboarder GUI")
        self.geometry("980x680")
        self.minsize(880, 560)

        self._build_menu()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # Tabs
        self.tab1 = ttk.Frame(nb)
        self.tab2 = ttk.Frame(nb)
        self.tab3 = ttk.Frame(nb)
        nb.add(self.tab1, text="Mode 1 — Copy by Extension")
        nb.add(self.tab2, text="Mode 2 — Find C# References")
        nb.add(self.tab3, text="Mode 3 — Drop Files to Compile")

        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

        if get_tokenizer() is None:
            self.after(200, lambda: messagebox.showinfo(
                "Info",
                "Optional: Install 'tiktoken' for token-based chunking.\n\npip install tiktoken"
            ))
        if not pyperclip:
            self.after(300, lambda: messagebox.showinfo(
                "Info",
                "Optional: Install 'pyperclip' for robust clipboard copy.\n\npip install pyperclip"
            ))
        if not TKDND_AVAILABLE:
            self.after(400, lambda: messagebox.showinfo(
                "Drag & Drop",
                "Optional: Install 'tkinterdnd2' to enable drag-and-drop in Mode 3.\n\npip install tkinterdnd2"
            ))

    # ------------------ Menu ------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=False)
        filemenu.add_command(label="Quit", command=self.destroy, accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=filemenu)

        helpmenu = tk.Menu(menubar, tearoff=False)
        helpmenu.add_command(label="About", command=lambda: messagebox.showinfo(
            "About",
            "Clipboarder GUI\nA simple GUI wrapper for your multi-mode clipboard tool."
        ))
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.config(menu=menubar)
        self.bind_all("<Control-q>", lambda e: self.destroy())

    # ------------------ Tab 1 ------------------
    def _build_tab1(self):
        # Top controls: add/remove folder+ext pairs
        top = ttk.Frame(self.tab1)
        top.pack(fill="x", pady=(8, 4))

        add_btn = ttk.Button(top, text="Add Folder + Extension", command=self._tab1_add_pair)
        add_btn.pack(side="left")

        remove_btn = ttk.Button(top, text="Remove Selected", command=self._tab1_remove_selected)
        remove_btn.pack(side="left", padx=(8, 0))

        clear_btn = ttk.Button(top, text="Clear All", command=self._tab1_clear_all)
        clear_btn.pack(side="left", padx=(8, 0))

        # List of pairs
        mid = ttk.Frame(self.tab1)
        mid.pack(fill="both", expand=True, pady=(4, 4))

        self.tab1_list = tk.Listbox(mid, height=12, selectmode="extended")
        self.tab1_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tab1_list.yview)
        sb.pack(side="right", fill="y")
        self.tab1_list.config(yscrollcommand=sb.set)

        # Options
        opts = ttk.LabelFrame(self.tab1, text="Options")
        opts.pack(fill="x", padx=2, pady=(6, 4))

        self.tab1_strip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Strip empty/whitespace-only lines", variable=self.tab1_strip_var).pack(anchor="w", padx=6, pady=4)

        row = ttk.Frame(opts); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tab1_tokens = ttk.Entry(row, width=10)
        self.tab1_tokens.pack(side="left", padx=6)

        # Action + output
        bottom = ttk.Frame(self.tab1)
        bottom.pack(fill="x", pady=(4, 2))
        ttk.Button(bottom, text="Scan & Copy to Clipboard", command=self._tab1_run).pack(side="left")

        self.tab1_status = tk.Text(self.tab1, height=10)
        self.tab1_status.pack(fill="both", expand=False, pady=(6, 8))
        self._set_readonly(self.tab1_status)

    def _tab1_add_pair(self):
        folder = filedialog.askdirectory(title="Choose folder")
        if not folder:
            return
        ext_win = tk.Toplevel(self)
        ext_win.title("Choose Extension")
        ttk.Label(ext_win, text="File extension (with or without dot):").pack(padx=10, pady=(10, 4))
        ext_entry = ttk.Entry(ext_win)
        ext_entry.insert(0, ".py")
        ext_entry.pack(padx=10, pady=4)
        def ok():
            ext = ext_entry.get().strip()
            if ext and not ext.startswith("."):
                ext = "." + ext
            if not ext:
                messagebox.showerror("Error", "Please provide an extension.")
                return
            self.tab1_list.insert("end", f"{folder} || {ext}")
            ext_win.destroy()
        ttk.Button(ext_win, text="OK", command=ok).pack(pady=(6, 10))
        ext_entry.focus_set()

    def _tab1_remove_selected(self):
        sel = list(self.tab1_list.curselection())
        sel.reverse()
        for i in sel:
            self.tab1_list.delete(i)

    def _tab1_clear_all(self):
        self.tab1_list.delete(0, "end")

    def _tab1_run(self):
        pairs = []
        for i in range(self.tab1_list.size()):
            item = self.tab1_list.get(i)
            if "||" in item:
                folder, ext = [s.strip() for s in item.split("||", 1)]
                if os.path.isdir(folder) and ext:
                    pairs.append((folder, ext))
        if not pairs:
            messagebox.showwarning("No selections", "Add at least one folder + extension pair.")
            return

        self._set_status(self.tab1_status, "Scanning folders...\n")
        files = collect_files(pairs)
        self._append_status(self.tab1_status, f"Found {len(files)} files.\n")
        if not files:
            return

        combined = combine_files_with_annotations(files)
        if self.tab1_strip_var.get():
            combined = strip_empty_lines(combined)

        max_tokens = self._parse_int_entry(self.tab1_tokens)
        chunks = split_text_by_tokens(combined, max_tokens)
        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self._append_status(self.tab1_status, "Copied everything in one chunk to clipboard.\n")
        else:
            # copy all chunks sequentially with a preview message
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                self._append_status(self.tab1_status, f"Copied chunk {idx}/{len(chunks)} to clipboard. (Paste now, then press OK)\n")
                if idx != len(chunks):
                    messagebox.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self._append_status(self.tab1_status, "All chunks copied.\n")

    # ------------------ Tab 2 ------------------
    def _build_tab2(self):
        top = ttk.LabelFrame(self.tab2, text="Search Settings")
        top.pack(fill="x", padx=4, pady=6)

        row1 = ttk.Frame(top); row1.pack(fill="x", padx=6, pady=4)
        ttk.Label(row1, text="Root folder:").pack(side="left")
        self.tab2_root = ttk.Entry(row1)
        self.tab2_root.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row1, text="Browse…", command=self._tab2_browse_root).pack(side="left")

        row2 = ttk.Frame(top); row2.pack(fill="x", padx=6, pady=4)
        ttk.Label(row2, text="Regex pattern:").pack(side="left")
        self.tab2_pattern = ttk.Entry(row2)
        self.tab2_pattern.pack(side="left", fill="x", expand=True, padx=6)

        row3 = ttk.Frame(top); row3.pack(fill="x", padx=6, pady=4)
        ttk.Label(row3, text="Lines before:").pack(side="left")
        self.tab2_before = ttk.Spinbox(row3, from_=0, to=50, width=5)
        self.tab2_before.delete(0, "end"); self.tab2_before.insert(0, "3")
        self.tab2_before.pack(side="left", padx=(6, 12))
        ttk.Label(row3, text="Lines after:").pack(side="left")
        self.tab2_after = ttk.Spinbox(row3, from_=0, to=50, width=5)
        self.tab2_after.delete(0, "end"); self.tab2_after.insert(0, "3")
        self.tab2_after.pack(side="left", padx=(6, 12))

        row4 = ttk.Frame(top); row4.pack(fill="x", padx=6, pady=4)
        ttk.Label(row4, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tab2_tokens = ttk.Entry(row4, width=10)
        self.tab2_tokens.pack(side="left", padx=6)

        actions = ttk.Frame(self.tab2)
        actions.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Button(actions, text="Search & Copy", command=self._tab2_run).pack(side="left")

        # Preview
        prev = ttk.LabelFrame(self.tab2, text="Preview (first 50 lines of results)")
        prev.pack(fill="both", expand=True, padx=4, pady=(4, 8))
        self.tab2_preview = tk.Text(prev, height=18)
        self.tab2_preview.pack(fill="both", expand=True)
        self._set_readonly(self.tab2_preview)

        self.tab2_status = tk.StringVar(value="")
        ttk.Label(self.tab2, textvariable=self.tab2_status).pack(anchor="w", padx=6, pady=(0, 8))

    def _tab2_browse_root(self):
        folder = filedialog.askdirectory(title="Choose root folder (C# project)")
        if folder:
            self.tab2_root.delete(0, "end")
            self.tab2_root.insert(0, folder)

    def _tab2_run(self):
        root = self.tab2_root.get().strip() or os.getcwd()
        if not os.path.isdir(root):
            messagebox.showerror("Invalid Folder", "Root folder is not a directory.")
            return
        pattern = self.tab2_pattern.get().strip()
        if not pattern:
            messagebox.showwarning("Missing Pattern", "Enter a regex to search (e.g. \\bSettingsManager\\b).")
            return
        try:
            before = int(self.tab2_before.get())
            after = int(self.tab2_after.get())
        except ValueError:
            messagebox.showerror("Invalid Context", "Before/After must be integers.")
            return

        self.tab2_status.set("Searching… this may take a moment.")
        self.update_idletasks()

        try:
            snippets = find_references_with_context(root, pattern, before=before, after=after)
        except ValueError as e:
            messagebox.showerror("Regex Error", str(e))
            self.tab2_status.set("")
            return

        if not snippets:
            self.tab2_status.set("No references found for that pattern.")
            self._set_text(self.tab2_preview, "")
            return

        combined = "\n\n".join(snippets)
        # preview: first 50 lines
        preview = "\n".join(combined.splitlines()[:50])
        if len(combined.splitlines()) > 50:
            preview += "\n… (truncated in preview)"
        self._set_text(self.tab2_preview, preview)

        max_tokens = self._parse_int_entry(self.tab2_tokens)
        chunks = split_text_by_tokens(combined, max_tokens)

        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self.tab2_status.set(f"Copied {len(snippets)} snippet block(s) to clipboard.")
        else:
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                if idx != len(chunks):
                    messagebox.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self.tab2_status.set(f"Copied {len(snippets)} snippet block(s) to clipboard in {len(chunks)} chunks.")

    # ------------------ Tab 3 ------------------
    def _build_tab3(self):
        info = ttk.LabelFrame(self.tab3, text="Instructions")
        info.pack(fill="x", padx=4, pady=6)
        ttk.Label(
            info,
            text=("Drag & drop files below (requires tkinterdnd2), or click 'Add Files…'.\n"
                  "Then click 'Compile/Copy'.")
        ).pack(anchor="w", padx=6, pady=6)

        mid = ttk.Frame(self.tab3); mid.pack(fill="both", expand=True, padx=4)

        self.tab3_list = tk.Listbox(mid, selectmode="extended")
        self.tab3_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tab3_list.yview)
        sb.pack(side="left", fill="y")
        self.tab3_list.config(yscrollcommand=sb.set)

        # DnD binding (if available)
        if TKDND_AVAILABLE and DND_FILES:
            self.tab3_list.drop_target_register(DND_FILES)
            self.tab3_list.dnd_bind("<<Drop>>", self._tab3_on_drop)

        side = ttk.Frame(mid); side.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(side, text="Add Files…", command=self._tab3_add_files).pack(fill="x")
        ttk.Button(side, text="Remove Selected", command=self._tab3_remove_selected).pack(fill="x", pady=(6, 0))
        ttk.Button(side, text="Clear All", command=self._tab3_clear).pack(fill="x", pady=(6, 0))

        opts = ttk.LabelFrame(self.tab3, text="Options")
        opts.pack(fill="x", padx=4, pady=(6, 4))
        self.tab3_strip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Strip empty/whitespace-only lines", variable=self.tab3_strip_var).pack(anchor="w", padx=6, pady=4)

        row = ttk.Frame(opts); row.pack(fill="x", padx=6, pady=4)
        ttk.Label(row, text="Max tokens per chunk (blank = no chunking):").pack(side="left")
        self.tab3_tokens = ttk.Entry(row, width=10)
        self.tab3_tokens.pack(side="left", padx=6)

        actions = ttk.Frame(self.tab3); actions.pack(fill="x", padx=4, pady=(6, 8))
        ttk.Button(actions, text="Compile/Copy", command=self._tab3_run).pack(side="left")

        self.tab3_status = tk.Text(self.tab3, height=8)
        self.tab3_status.pack(fill="both", expand=False, padx=4, pady=(0, 8))
        self._set_readonly(self.tab3_status)

    def _tab3_on_drop(self, event):
        raw = event.data  # may be a brace-quoted TCL list on some platforms
        # Convert possible TCL-style list into space-separated
        if raw.startswith("{") and raw.endswith("}"):
            # naive split respecting braces
            items = []
            current = []
            brace = 0
            token = ""
            for ch in raw:
                if ch == "{":
                    brace += 1
                    if brace == 1:
                        continue
                elif ch == "}":
                    brace -= 1
                    if brace == 0:
                        items.append("".join(current))
                        current = []
                        continue
                if brace > 0:
                    current.append(ch)
                elif ch == " ":
                    pass
            paths = items
        else:
            paths = raw.split()

        added = 0
        for p in paths:
            norm = _normalize_dropped_path(p)
            if os.path.isfile(norm):
                if norm not in self.tab3_list.get(0, "end"):
                    self.tab3_list.insert("end", norm)
                    added += 1
        self._set_status(self.tab3_status, f"Added {added} file(s) via drag-and-drop.\n")

    def _tab3_add_files(self):
        files = filedialog.askopenfilenames(title="Choose files")
        for f in files:
            if f not in self.tab3_list.get(0, "end"):
                self.tab3_list.insert("end", f)

    def _tab3_remove_selected(self):
        sel = list(self.tab3_list.curselection())
        sel.reverse()
        for i in sel:
            self.tab3_list.delete(i)

    def _tab3_clear(self):
        self.tab3_list.delete(0, "end")

    def _tab3_run(self):
        files = list(self.tab3_list.get(0, "end"))
        if not files:
            messagebox.showwarning("No Files", "Add some files first.")
            return
        self._set_status(self.tab3_status, f"Found {len(files)} staged file(s).\n")

        combined = combine_files_with_annotations(files)
        if self.tab3_strip_var.get():
            combined = strip_empty_lines(combined)

        max_tokens = self._parse_int_entry(self.tab3_tokens)
        chunks = split_text_by_tokens(combined, max_tokens)
        if len(chunks) == 1:
            copy_to_clipboard(chunks[0], self)
            self._append_status(self.tab3_status, "Copied all content in one go.\n")
        else:
            for idx, ch in enumerate(chunks, 1):
                copy_to_clipboard(ch, self)
                self._append_status(self.tab3_status, f"Copied chunk {idx}/{len(chunks)}. Paste now, then press OK.\n")
                if idx != len(chunks):
                    messagebox.showinfo("Chunk copied", f"Chunk {idx}/{len(chunks)} copied.\nPaste it, then click OK for the next chunk.")
            self._append_status(self.tab3_status, "All chunks copied.\n")

    # ------------------ Utilities ------------------
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
        text_widget.config(state="disabled", wrap="word", font=("Consolas", 10))

    def _set_text(self, text_widget: tk.Text, text: str):
        text_widget.config(state="normal")
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", text)
        text_widget.config(state="disabled")

    def _set_status(self, text_widget: tk.Text, text: str):
        text_widget.config(state="normal")
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", text)
        text_widget.config(state="disabled")

    def _append_status(self, text_widget: tk.Text, text: str):
        text_widget.config(state="normal")
        text_widget.insert("end", text)
        text_widget.see("end")
        text_widget.config(state="disabled")


def main():
    app = ClipboarderGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
