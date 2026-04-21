# Kindle Scribe notebook automation

This repository exports Kindle Scribe notebooks, converts them to PDFs, and imports them into markdown-based note systems.

## What’s included

- **Windows (existing):** PowerShell scripts under `script/*.ps1`
- **macOS (new):** Python + launchd workflow:
  - `script/setup_macos.py`
  - `script/scribe_watcher_macos.py`
  - `script/install_launchd.sh`

## macOS requirements

- Python 3 (available by default on most macOS setups as `python3`)
- [Calibre](https://calibre-ebook.com/)
- Calibre **KFX Input** plugin
- `libmtp` tools (for MTP access): `brew install libmtp`

## macOS setup

From the repository root:

```bash
python3 script/setup_macos.py
```

This creates:

- `settings/config_macos.json`
- `settings/notebook_labels.json` (created on first sync)

## Run once (manual sync)

```bash
python3 script/scribe_watcher_macos.py once --config settings/config_macos.json
```

## Run as a background daemon (launchd)

```bash
chmod +x script/install_launchd.sh
./script/install_launchd.sh
```

This installs and loads:

- `~/Library/LaunchAgents/com.scribepdfgetter.watcher.plist`

Useful commands:

```bash
launchctl unload ~/Library/LaunchAgents/com.scribepdfgetter.watcher.plist
launchctl load ~/Library/LaunchAgents/com.scribepdfgetter.watcher.plist
```

Logs:

- `settings/scribe_watcher.stdout.log`
- `settings/scribe_watcher.stderr.log`

## macOS behavior

When a Kindle Scribe is connected over USB, the watcher:

1. Detects the device over MTP (`mtp-detect`, `mtp-folders`, `mtp-files`, `mtp-getfile`) and pulls native notebook `nbk` files from `.notebooks/<GUID>/nbk`
2. Falls back to mounted-volume detection in `/Volumes` when applicable
3. Converts changed notebooks via Calibre to EPUB and then PDF
4. Imports converted PDFs into an Obsidian-compatible target directory by:
   - copying PDFs to the configured attachment folder (default `assets/pdf`)
   - creating/updating one `.md` file per notebook with a link to its PDF

## Notes

- Notebook labels are tracked in `settings/notebook_labels.json`.
- Label text is used as the PDF/markdown filename (with invalid filename characters removed).
- Existing Windows scripts remain unchanged.
