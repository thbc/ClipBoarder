
"""
Interactive script to select multiple folders—each with its own file-extension—and
then copy all matching files (annotated with filenames) to the clipboard.
Supports optional token‐based chunking (requires tiktoken).

Features in this version:
- “Find C# References” mode (mode 2), which walks a folder of .cs files,
  uses a regex to locate a symbol, grabs N lines of context around each hit, and
  copies those snippets to the clipboard (also with optional token chunking).
  File paths in snippet headers are now shown relative to the root folder (for privacy).
- “Drop Files to Compile” mode (mode 3): drag-and-drop files into the terminal to
  stage them; press S to compile/copy (with optional token chunking).
- Modes 1 & 3: optional stripping of empty/whitespace-only lines before copying.
"""

import os
import sys
import re
import shlex
from urllib.parse import urlparse, unquote

try:
    import pyperclip
except ImportError:
    print("Error: 'pyperclip' module not found. Install with 'pip install pyperclip'.")
    sys.exit(1)

try:
    import tiktoken
    TOKENIZER = tiktoken.encoding_for_model("gpt-4o")
except Exception:
    TOKENIZER = None


def get_initial_folder():
    """
    Prompt the user for the starting directory.
    If blank, defaults to the current working directory.
    """
    inp = input("Enter starting directory (leave blank for current directory): ").strip()
    if not inp:
        return os.getcwd()
    if os.path.isdir(inp):
        return os.path.abspath(inp)
    else:
        print(f"→ '{inp}' is not a valid directory. Using current directory instead.")
        return os.getcwd()


def prompt_extension(default_ext=".py"):
    """
    Prompt for a file extension, defaulting to `default_ext` if blank.
    Ensures it starts with a dot.
    """
    inp = input(f"Enter file extension for this folder (default: {default_ext}): ").strip()
    if not inp:
        return default_ext
    return inp if inp.startswith(".") else "." + inp


def navigate_and_select_folders(start_dir):
    """
    Let the user navigate directories and build a list of (folder, extension) pairs.
    Commands when viewing `current` directory:
      [number]  → navigate into the numbered subdirectory
      A         → “Add” the current folder (prompts for extension)
      U         → go up to parent directory
      S         → done adding (requires at least one folder added)
      Q         → quit immediately
    Returns:
      List of tuples: [(folder_path, extension), ...]
    """
    selections = []
    current = start_dir

    while True:
        print(f"\nCurrent directory: {current}")
        try:
            subdirs = sorted(
                [d for d in os.listdir(current) if os.path.isdir(os.path.join(current, d))]
            )
        except PermissionError:
            print("→ Permission denied. Staying in the same directory.")
            subdirs = []

        # List subdirectories with indices
        for idx, name in enumerate(subdirs, start=1):
            print(f"  [{idx}] {name}/")

        print("Options:")
        print("  [number] → enter that subdirectory")
        print("  A        → Add CURRENT folder (choose its extension)")
        print("  U        → Go UP to parent folder")
        print("  S        → Start compiling (requires ≥1 selection)")
        print("  Q        → Quit")

        choice = input("Your choice: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(subdirs):
                current = os.path.join(current, subdirs[idx])
            else:
                print("→ Invalid number. Try again.")
        else:
            cmd = choice.upper()
            if cmd == "A":
                # Prompt for extension when adding this folder
                ext = prompt_extension(default_ext=".py")
                pair = (current, ext)
                if pair not in selections:
                    selections.append(pair)
                    print(f"→ Added: '{current}'  with extension '{ext}'")
                else:
                    print("→ Already added that exact folder+extension pair.")
            elif cmd == "U":
                parent = os.path.dirname(current)
                if parent and parent != current and os.path.isdir(parent):
                    current = parent
                else:
                    print("→ Cannot go up. Already at root or no permission.")
            elif cmd == "S":
                if not selections:
                    print("→ No folders added yet. Use ‘A’ to add at least one.")
                else:
                    return selections
            elif cmd == "Q":
                print("Exiting.")
                sys.exit(0)
            else:
                print("→ Unknown command. Try again.")


def collect_files(folder_ext_pairs):
    """
    Given a list of (folder, extension) pairs, walk each folder recursively
    and collect all files matching its extension. Returns a sorted list of paths.
    """
    all_files = []
    for folder, ext in folder_ext_pairs:
        for root, _, files in os.walk(folder):
            for fname in files:
                if fname.endswith(ext):
                    all_files.append(os.path.join(root, fname))
    return sorted(all_files)


def combine_files_with_annotations(file_paths):
    """
    Read each file, prepend an annotation line with its filename,
    and concatenate everything into a single string.
    """
    sections = []
    for path in file_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read '{path}': {e}")
            continue
        sections.append(f"# ===== File: {os.path.basename(path)} =====\n{content}")
    return "\n\n".join(sections)


def split_text_by_tokens(text, max_tokens):
    """
    If tiktoken is available, split the text into chunks that
    do not exceed `max_tokens`. Otherwise, return [text] as-is.
    """
    if TOKENIZER is None:
        print("Warning: tiktoken not available. Copying all at once.")
        return [text]

    lines = text.splitlines(keepends=True)
    chunks = []
    current = ""
    for line in lines:
        if len(TOKENIZER.encode(current + line)) <= max_tokens:
            current += line
        else:
            if current:
                chunks.append(current)
            # If a single line is already too big, put it alone
            if len(TOKENIZER.encode(line)) > max_tokens:
                print("Warning: One line exceeds max token size; it becomes its own chunk.")
                chunks.append(line)
                current = ""
            else:
                current = line
    if current:
        chunks.append(current)
    return chunks


def find_references_with_context(root_folder, pattern, before=3, after=3):
    """
    Walk through all .cs files under root_folder, search for 'pattern', and for
    each match return a snippet (with context). Returns a list of snippet strings.
    Each snippet looks like:

    ========
    relative/path/to/File.cs (line 47):
      44:    ...
      45:    ...
    >>47:    matching line
      48:    ...
      49:    ...
    """
    regex = re.compile(pattern)
    snippets = []

    for dirpath, _, filenames in os.walk(root_folder):
        for fname in filenames:
            if not fname.lower().endswith('.cs'):
                continue
            path = os.path.join(dirpath, fname)
            try:
                with open(path, encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except OSError:
                continue

            for idx, line in enumerate(lines):
                if regex.search(line):
                    start = max(0, idx - before)
                    end = min(len(lines), idx + after + 1)
                    snippet_lines = []
                    snippet_lines.append("=" * 80)

                    # Compute relative path for privacy
                    rel_path = os.path.relpath(path, root_folder)
                    snippet_lines.append(f"{rel_path} (line {idx+1}):")

                    for i in range(start, end):
                        prefix = ">>" if i == idx else "  "
                        num = str(i + 1).rjust(4)
                        snippet_lines.append(f"{prefix} {num}: {lines[i].rstrip()}")
                    snippet_lines.append("")  # blank line at end
                    snippets.append("\n".join(snippet_lines))

    return snippets


# -----------------------------
# Helpers for Mode 3 (drop files)
# -----------------------------
def _normalize_dropped_path(p):
    """
    Normalize a dropped path token:
    - Handle file:// URIs
    - URL-decode percent escapes
    - Trim leading '/' on Windows like '/C:/path'
    - Expand ~
    - Return absolute normalized path
    """
    p = p.strip()
    # Handle file:// URIs
    try:
        parsed = urlparse(p)
    except Exception:
        parsed = None

    if parsed and parsed.scheme == "file":
        p = unquote(parsed.path or "")
        # On Windows, file:///C:/... becomes /C:/... -> strip leading slash
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", p):
            p = p.lstrip("/")
    else:
        # URL-decode if someone pasted percent-escaped path without file://
        p = unquote(p)

    # Expand ~
    p = os.path.expanduser(p)
    # Normalize
    return os.path.abspath(p)


def _parse_dropped_input(line):
    """
    Parse a line of dragged-in paths. Robust to quotes and spaces.
    Uses Windows-aware splitting on Windows.
    """
    if not line.strip():
        return []
    try:
        tokens = shlex.split(line, posix=(os.name != "nt"))
    except Exception:
        tokens = line.split()
    return [_normalize_dropped_path(tok) for tok in tokens]



def drop_files_mode():
    """
    Mode 3: Let the user drag & drop files into the terminal to stage them.
    Commands:
      - Drop/paste paths and press Enter to add
      - L → list current staged files
      - R → remove by index (comma/space separated)
      - C → clear all
      - S → start compile/copy
      - Q → back to main menu
    """
    staged = []

    print("\n=== Drop Files Mode ===")
    print("Instructions:")
    print("  • Drag & drop file(s) into this window, then press Enter to add them.")
    print("  • Or type a path manually. Use quotes if it contains spaces.")
    print("  • Commands:  L=list, R=remove, C=clear, S=start, Q=back\n")

    while True:
        prompt = f"[staged: {len(staged)}] Drop files or command (L/R/C/S/Q): "
        line = input(prompt)

        if not line.strip():
            continue

        cmd = line.strip().upper()
        if cmd == "L":
            if not staged:
                print("→ No files staged yet.")
            else:
                print("Currently staged files:")
                for i, p in enumerate(staged, 1):
                    print(f"  {i:>3}. {p}")
            continue

        if cmd.startswith("R"):
            # Accept "R 2 5 7" or "R 2,5,7"
            parts = line[1:].strip().replace(",", " ").split()
            if not parts:
                print("→ Usage: R <index> [more indices...]")
                continue
            to_remove = sorted({int(x) for x in parts if x.isdigit()}, reverse=True)
            removed = 0
            for idx in to_remove:
                if 1 <= idx <= len(staged):
                    staged.pop(idx - 1)
                    removed += 1
            print(f"→ Removed {removed} item(s).")
            continue

        if cmd == "C":
            staged.clear()
            print("→ Cleared all staged files.")
            continue

        if cmd == "Q":
            print("Returning to main menu.")
            return

        if cmd == "S":
            if not staged:
                print("→ Nothing staged yet. Drop some files first.")
                continue

            print(f"Found {len(staged)} file(s) staged.")
            combined = combine_files_with_annotations(staged)

            #optional empty-line stripping (mode 3 only)
            strip_choice = input("Strip empty lines before copying? (y/N): ").strip().lower()
            if strip_choice in ("y", "yes"):
                combined = strip_empty_lines(combined)

            tok_input = input("Enter max token size to chunk (blank = no chunking): ").strip()
            if tok_input:
                try:
                    max_tokens = int(tok_input)
                except ValueError:
                    print("→ Invalid number. Will copy everything in one shot.")
                    max_tokens = None
            else:
                max_tokens = None

            if max_tokens:
                chunks = split_text_by_tokens(combined, max_tokens)
                for idx, chunk in enumerate(chunks, start=1):
                    pyperclip.copy(chunk)
                    print(f"[{idx}/{len(chunks)}] chunk copied to clipboard. Press Enter to continue...")
                    input()
            else:
                pyperclip.copy(combined)
                print("All content copied to clipboard in one go.")

            again = input("Done. Press ‘C’ to return to Drop Files mode or any other key to main menu: ").strip().upper()
            if again == "C":
                continue
            else:
                return

        # Otherwise: treat as dropped/pasted path list
        paths = _parse_dropped_input(line)
        added = 0
        skipped = 0
        for p in paths:
            if os.path.isfile(p):
                if p not in staged:
                    staged.append(p)
                    added += 1
            else:
                # Ignore directories for Mode 3; you can handle directories via Mode 1
                skipped += 1
        print(f"→ Added {added} file(s). Skipped {skipped} non-file path(s).")

def strip_empty_lines(text: str) -> str:
    """Remove lines that are empty or whitespace-only."""
    return "\n".join(line for line in text.splitlines() if line.strip())



def main():
    while True:
        print("\n=== Choose Mode ===")
        print("1) Copy files by extension")
        print("2) Find C# references (with context) and copy snippets for quickly locating and exporting code references with context")
        print("3) Drop files to compile/copy")
        print("Q) Quit")
        mode = input("Your choice: ").strip().upper()

        if mode == "1":
            # === Original “copy files by extension” flow ===
            start_dir = get_initial_folder()
            selections = navigate_and_select_folders(start_dir)

            print("\nYou have added the following folder+extension pairs:")
            for folder, ext in selections:
                print(f"  - {folder}    (ext = '{ext}')")

            all_files = collect_files(selections)
            if not all_files:
                print("No files found with those extensions in the selected folders.")
                retry = input("Press ‘C’ to choose again or any other key to return to main menu: ").strip().upper()
                if retry == "C":
                    continue
                else:
                    continue  # back to mode selection

            print(f"Found {len(all_files)} file(s) total across all selections.")
            combined = combine_files_with_annotations(all_files)
            # optional empty-line stripping (mode 1 only)
            strip_choice = input("Strip empty lines before copying? (y/N): ").strip().lower()
            if strip_choice in ("y", "yes"):
                combined = strip_empty_lines(combined)

            tok_input = input("Enter max token size to chunk (blank = no chunking): ").strip()
            if tok_input:
                try:
                    max_tokens = int(tok_input)
                except ValueError:
                    print("→ Invalid number. Will copy everything in one shot.")
                    max_tokens = None
            else:
                max_tokens = None

            if max_tokens:
                chunks = split_text_by_tokens(combined, max_tokens)
                for idx, chunk in enumerate(chunks, start=1):
                    pyperclip.copy(chunk)
                    print(f"[{idx}/{len(chunks)}] chunk copied to clipboard. Press Enter to continue...")
                    input()
            else:
                pyperclip.copy(combined)
                print("All content copied to clipboard in one go.")

            again = input("Done. Press ‘C’ to return to main menu or any other key to exit: ").strip().upper()
            if again == "C":
                continue
            else:
                break

        elif mode == "2":
            # === New “find C# references + copy snippets” flow ===
            root_folder = get_initial_folder()
            print(f"Searching under: {root_folder}")
            pattern = input(
                "Enter regex pattern to search for (e.g. \"\\bSettingsManager\\b\" or \"SetDisplay\\(\"): "
            ).strip()
            if not pattern:
                print("→ No pattern provided. Returning to main menu.")
                continue

            # Ask for context lines (before/after)
            before_input = input("Lines of context BEFORE match (default = 3): ").strip()
            after_input = input("Lines of context AFTER match (default = 3): ").strip()
            try:
                before = int(before_input) if before_input else 3
            except ValueError:
                print("→ Invalid number for 'before'; using default = 3.")
                before = 3
            try:
                after = int(after_input) if after_input else 3
            except ValueError:
                print("→ Invalid number for 'after'; using default = 3.")
                after = 3

            print("\nSearching for references. This may take a moment...")
            snippets = find_references_with_context(root_folder, pattern, before=before, after=after)

            if not snippets:
                print("No references found for that pattern.")
                back = input("Press ‘C’ to try again or any other key to return to main menu: ").strip().upper()
                if back == "C":
                    continue
                else:
                    continue  # back to mode selection

            # Combine all snippets into one big string (with double-newlines between snippet blocks)
            combined_snippets = "\n\n".join(snippets)

            # Ask about token chunking
            tok_input = input("Enter max token size to chunk (blank = no chunking): ").strip()
            if tok_input:
                try:
                    max_tokens = int(tok_input)
                except ValueError:
                    print("→ Invalid number. Will copy everything in one shot.")
                    max_tokens = None
            else:
                max_tokens = None

            if max_tokens:
                chunks = split_text_by_tokens(combined_snippets, max_tokens)
                for idx, chunk in enumerate(chunks, start=1):
                    pyperclip.copy(chunk)
                    print(f"[{idx}/{len(chunks)}] chunk copied to clipboard. Press Enter to continue...")
                    input()
            else:
                pyperclip.copy(combined_snippets)
                print("All reference snippets copied to clipboard in one go.")

            again = input("Done. Press ‘C’ to return to main menu or any other key to exit: ").strip().upper()
            if again == "C":
                continue
            else:
                break

        elif mode == "3":
            # === New “drop files to compile/copy” flow ===
            drop_files_mode()

        elif mode == "Q":
            print("Quitting.")
            sys.exit(0)
        else:
            print("→ Unknown option. Please type 1, 2, 3, or Q.")


if __name__ == "__main__":
    main()

