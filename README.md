# ClipBoarder
<p align="center"><img src="assets/logo.png" alt="Alt Text" width="300" height="300"></p>

A simple command line for copying batches of scripts to the clipboard. Useful for providing contexts to LLM prompts.

# Requirements

pip install -r requirements.txt
## For building (packaging) the executable
pip install -r dev-requirements.txt

# Packaging (optional)

Build a single-file executable:

pyinstaller --onefile --windowed --name Clipboarder-GUI   --icon assets/app.ico   --collect-all tiktoken   --collect-all tiktoken_ext   --hidden-import tkinterdnd2   --hidden-import tiktoken_ext.openai_public   --hidden-import regex   --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." --add-data "README.md;."  src/app.py



# License

MIT © 2025 thbc
See LICENSE. Third-party licenses are listed in THIRD_PARTY_NOTICES.md.