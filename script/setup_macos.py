#!/usr/bin/env python3
import json
import shutil
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "settings" / "config_macos.json"


def prompt(message: str, default: str) -> str:
    value = input(f"{message} [{default}]: ").strip()
    return value if value else default


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    settings_dir = repo_root / "settings"

    print("macOS configuration. Press enter to accept default values.")

    calibre_debug_default = shutil.which("calibre-debug") or "/Applications/calibre.app/Contents/MacOS/calibre-debug"
    ebook_convert_default = shutil.which("ebook-convert") or "/Applications/calibre.app/Contents/MacOS/ebook-convert"

    update_obsidian = prompt("Create markdown files with PDF attachments for Obsidian", "Yes")

    config = {
        "kindle_name_substring": prompt("Kindle volume name contains", "Kindle"),
        "volume_root": prompt("Volumes root", "/Volumes"),
        "notebooks_relative_paths": [
            ".notebooks",
            "Internal Storage/.notebooks",
        ],
        "guid_pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        "nbk_file_name": "nbk",
        "destination_path": prompt("Native notebook export path", str(repo_root / "exported_notebooks")),
        "output_epub_directory": prompt("EPUB output path", str(repo_root / "epub")),
        "output_pdf_directory": prompt("PDF output path", str(repo_root / "pdf")),
        "calibre_path": prompt("Path to calibre-debug", calibre_debug_default),
        "ebook_convert_path": prompt("Path to ebook-convert", ebook_convert_default),
        "plugin_name": prompt("Calibre plugin name", "KFX Input"),
        "settings_directory": str(settings_dir),
        "labels_file_path": str(settings_dir / "notebook_labels.json"),
        "poll_seconds": int(prompt("Watcher poll interval seconds", "5")),
        "update_obsidian": update_obsidian.lower() in {"yes", "y", "true", "1"},
        "obsidian_target_dir": prompt("Obsidian target directory", str(Path.home() / "Obsidian")),
        "obsidian_attachments_subdir": prompt("Obsidian attachments subdirectory", "assets/pdf"),
    }

    settings_dir.mkdir(parents=True, exist_ok=True)
    with DEFAULT_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"Configuration file created at {DEFAULT_CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
