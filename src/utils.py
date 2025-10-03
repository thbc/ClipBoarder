#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import os, re, shlex
from urllib.parse import urlparse, unquote

# -------- Optional deps (lazy) --------
try:
    import pyperclip
except Exception:
    pyperclip = None

_TOKENIZER_SENTINEL = object()
TOKENIZER = _TOKENIZER_SENTINEL

def get_tokenizer():
    """Return a tiktoken encoder or None (never raises)."""
    global TOKENIZER
    if TOKENIZER is not _TOKENIZER_SENTINEL:
        return TOKENIZER
    try:
        import tiktoken
        TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
    except Exception:
        TOKENIZER = None
    return TOKENIZER

# ---------- Clipboard ----------
def copy_to_clipboard(text: str, tk_root) -> None:
    """Copy text via pyperclip if available, else via Tk."""
    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            return
        except Exception:
            pass
    try:
        tk_root.clipboard_clear()
        tk_root.clipboard_append(text)
        tk_root.update()
    except Exception as e:
        from tkinter import messagebox
        messagebox.showerror("Clipboard Error", f"Failed to copy to clipboard:\n{e}")

# ---------- Chunking / text utils ----------
def split_text_by_tokens(text: str, max_tokens: int):
    if not max_tokens or max_tokens <= 0:
        return [text]
    tok = get_tokenizer()
    if tok is None:
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
                chunks.append(line)
                current = ""
            else:
                current = line
    if current:
        chunks.append(current)
    return chunks

def strip_empty_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip())

def combine_files_with_annotations(file_paths):
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
    all_files = []
    for folder, ext in folder_ext_pairs:
        for root, _, files in os.walk(folder):
            for fname in files:
                if fname.endswith(ext):
                    all_files.append(os.path.join(root, fname))
    return sorted(all_files)

# ---------- DnD path parsing ----------
def _normalize_dropped_path(p):
    p = p.strip()
    try:
        parsed = urlparse(p)
    except Exception:
        parsed = None
    if parsed and parsed.scheme == "file":
        p = unquote(parsed.path or "")
        import os as _os, re as _re
        if _os.name == "nt" and _re.match(r"^/[A-Za-z]:", p):
            p = p.lstrip("/")
    else:
        p = unquote(p)
    p = os.path.expanduser(p)
    return os.path.abspath(p)

def parse_dropped_input(line: str):
    if not line.strip():
        return []
    try:
        tokens = shlex.split(line, posix=(os.name != "nt"))
    except Exception:
        tokens = line.split()
    return [_normalize_dropped_path(tok) for tok in tokens]

# ---------- Regex helpers ----------
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def guess_csharp_regex_from_text(user_text: str) -> str:
    """
    Build a practical regex for C# based on simple user text:
      - pure identifier -> \bName\b
      - identifier + '(' anywhere -> \bName\s*\(
      - dotted path like A.B.C -> \bA\.B\.C\b  (also allow generic: <...> optional)
      - contains regex metachars already? If user clearly wrote regex (heuristic), return as-is.
      - otherwise -> literal (re.escape)
    Also handle common C# method name patterns like 'DoThingAsync' w/ optional generic angles.
    """
    s = user_text.strip()
    if not s:
        return ""

    # If the user already provided obvious regex constructs, trust them
    if any(ch in s for ch in r".*+?[]{}|()^$\\"):
        # but if it looks like a bare identifier with paren, still help out
        base = s.rstrip()
        # Leave advanced users' input untouched
        return s

    # has parentheses -> likely a call
    if "(" in s or s.endswith("()"):
        name = s.split("(")[0].strip()
        if _IDENTIFIER_RE.match(name):
            return rf"\b{name}\s*\("
        return re.escape(s)

    # dotted path like Namespace.Class.Method
    if "." in s:
        parts = s.split(".")
        if all(_IDENTIFIER_RE.match(p) for p in parts):
            # allow optional generic args: Foo<...> (keep it literal for now)
            esc = r"\.".join(map(re.escape, parts))
            return rf"\b{esc}\b"
        return re.escape(s)

    # plain identifier
    if _IDENTIFIER_RE.match(s):
        return rf"\b{s}\b"

    # fallback literal
    return re.escape(s)

def find_cs_references_with_context(root_folder, pattern, before=3, after=3):
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

# ---------- Simple theming ----------
def apply_dark_theme(root, ttk):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # avoid native themes that ignore fieldbackground
    except Exception:
        pass

    bg  = "#121212"  # window background
    fg  = "#e6e6e6"  # text color
    mid = "#1e1e1e"  # input fields / text area background
    acc = "#2a2a2a"  # buttons / tabs
    sel = "#2d4f74"  # selection background
    sfg = "#ffffff"  # selection foreground

    # Root bg
    root.configure(bg=bg)

    # ttk palette
    style.configure(".", background=bg, foreground=fg, fieldbackground=mid)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("TButton", background=acc, foreground=fg)
    style.configure("TNotebook", background=bg)
    style.configure("TNotebook.Tab", background=mid, foreground=fg, padding=(10, 6))
    style.map("TNotebook.Tab", background=[("selected", acc)])
    style.configure("TLabelframe", background=bg, foreground=fg)
    style.configure("TLabelframe.Label", background=bg, foreground=fg)
    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.configure("TEntry", fieldbackground=mid, foreground=fg, insertcolor=fg)
    style.configure("TSpinbox", fieldbackground=mid, foreground=fg, insertcolor=fg)

    # Classic Tk widgets (Text, Listbox) do not obey ttk.Style.
    # Use the option database to enforce defaults app-wide.
    root.option_clear()
    root.option_add("*Background", bg)
    root.option_add("*Foreground", fg)

    # Text & Listbox specifics
    root.option_add("*Text.background", mid)
    root.option_add("*Text.foreground", fg)
    root.option_add("*Text.insertBackground", fg)
    root.option_add("*Text.selectBackground", sel)
    root.option_add("*Text.selectForeground", sfg)

    root.option_add("*Listbox.background", mid)
    root.option_add("*Listbox.foreground", fg)
    root.option_add("*Listbox.selectBackground", sel)
    root.option_add("*Listbox.selectForeground", sfg)
    root.option_add("*Listbox.highlightThickness", 0)

    # Entry/Spinbox selection colors (some platforms)
    root.option_add("*Entry.background", mid)
    root.option_add("*Entry.foreground", fg)
    root.option_add("*Entry.insertBackground", fg)
    root.option_add("*Entry.selectBackground", sel)
    root.option_add("*Entry.selectForeground", sfg)

    # Scrollbar track
    style.configure("Vertical.TScrollbar", background=mid)

    # Return kwargs that work when we explicitly set on Text/Listbox instances
    return {
        "bg": mid,
        "fg": fg,
        "insertbackground": fg,
        "selectbackground": sel,
        "selectforeground": sfg,
        "highlightthickness": 0,
        "bd": 0,
    }


def apply_light_theme(root, ttk):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    bg  = "#f4f4f4"
    fg  = "#222222"
    mid = "#ffffff"
    acc = "#e6e6e6"
    sel = "#cde2ff"
    sfg = "#000000"

    root.configure(bg=bg)

    style.configure(".", background=bg, foreground=fg, fieldbackground=mid)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("TButton", background=acc, foreground=fg)
    style.configure("TNotebook", background=bg)
    style.configure("TNotebook.Tab", background=acc, foreground=fg, padding=(10, 6))
    style.map("TNotebook.Tab", background=[("selected", mid)])
    style.configure("TLabelframe", background=bg, foreground=fg)
    style.configure("TLabelframe.Label", background=bg, foreground=fg)
    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.configure("TEntry", fieldbackground=mid, foreground=fg, insertcolor=fg)
    style.configure("TSpinbox", fieldbackground=mid, foreground=fg, insertcolor=fg)
    style.configure("Vertical.TScrollbar", background=mid)

    root.option_clear()
    root.option_add("*Background", bg)
    root.option_add("*Foreground", fg)

    root.option_add("*Text.background", mid)
    root.option_add("*Text.foreground", fg)
    root.option_add("*Text.insertBackground", fg)
    root.option_add("*Text.selectBackground", sel)
    root.option_add("*Text.selectForeground", sfg)

    root.option_add("*Listbox.background", mid)
    root.option_add("*Listbox.foreground", fg)
    root.option_add("*Listbox.selectBackground", sel)
    root.option_add("*Listbox.selectForeground", sfg)
    root.option_add("*Listbox.highlightThickness", 0)

    root.option_add("*Entry.background", mid)
    root.option_add("*Entry.foreground", fg)
    root.option_add("*Entry.insertBackground", fg)
    root.option_add("*Entry.selectBackground", sel)
    root.option_add("*Entry.selectForeground", sfg)

    return {
        "bg": mid,
        "fg": fg,
        "insertbackground": fg,
        "selectbackground": sel,
        "selectforeground": sfg,
        "highlightthickness": 0,
        "bd": 0,
    }
