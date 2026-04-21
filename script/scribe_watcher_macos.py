#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "settings" / "config_macos.json"
DEFAULT_LABELS_PATH = Path(__file__).resolve().parent.parent / "settings" / "notebook_labels.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return cleaned or "Untitled Notebook"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


@dataclass
class Config:
    kindle_name_substring: str
    volume_root: Path
    notebooks_relative_paths: List[str]
    guid_pattern: str
    nbk_file_name: str
    destination_path: Path
    output_epub_directory: Path
    output_pdf_directory: Path
    calibre_path: str
    ebook_convert_path: str
    plugin_name: str
    settings_directory: Path
    labels_file_path: Path
    poll_seconds: int
    update_obsidian: bool
    obsidian_target_dir: Path
    obsidian_attachments_subdir: str


def load_config(config_path: Path) -> Config:
    raw = load_json(config_path, None)
    if raw is None:
        raise FileNotFoundError(
            f"Config not found at {config_path}. Run setup_macos.py first."
        )

    settings_directory = Path(raw.get("settings_directory", config_path.parent)).expanduser()
    labels_file_path = Path(raw.get("labels_file_path", settings_directory / "notebook_labels.json")).expanduser()

    return Config(
        kindle_name_substring=raw.get("kindle_name_substring", "Kindle"),
        volume_root=Path(raw.get("volume_root", "/Volumes")).expanduser(),
        notebooks_relative_paths=raw.get(
            "notebooks_relative_paths",
            [".notebooks", os.path.join("Internal Storage", ".notebooks")],
        ),
        guid_pattern=raw.get(
            "guid_pattern",
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        ),
        nbk_file_name=raw.get("nbk_file_name", "nbk"),
        destination_path=Path(raw["destination_path"]).expanduser(),
        output_epub_directory=Path(raw["output_epub_directory"]).expanduser(),
        output_pdf_directory=Path(raw["output_pdf_directory"]).expanduser(),
        calibre_path=raw["calibre_path"],
        ebook_convert_path=raw["ebook_convert_path"],
        plugin_name=raw.get("plugin_name", "KFX Input"),
        settings_directory=settings_directory,
        labels_file_path=labels_file_path,
        poll_seconds=int(raw.get("poll_seconds", 5)),
        update_obsidian=bool(raw.get("update_obsidian", True)),
        obsidian_target_dir=Path(raw.get("obsidian_target_dir", "~/ObsidianVault")).expanduser(),
        obsidian_attachments_subdir=raw.get("obsidian_attachments_subdir", "assets/pdf"),
    )


def find_notebooks_dir(mount_point: Path, relative_paths: List[str]) -> Optional[Path]:
    for rel in relative_paths:
        candidate = mount_point / rel
        if candidate.is_dir():
            return candidate
    return None


def discover_kindle_mounts(config: Config) -> Dict[Path, Path]:
    mounts: Dict[Path, Path] = {}
    if not config.volume_root.exists():
        return mounts

    for entry in config.volume_root.iterdir():
        if not entry.is_dir():
            continue
        if config.kindle_name_substring.lower() not in entry.name.lower():
            continue
        notebooks_dir = find_notebooks_dir(entry, config.notebooks_relative_paths)
        if notebooks_dir is not None:
            mounts[entry] = notebooks_dir
    return mounts


def ensure_dirs(config: Config) -> None:
    config.destination_path.mkdir(parents=True, exist_ok=True)
    config.output_epub_directory.mkdir(parents=True, exist_ok=True)
    config.output_pdf_directory.mkdir(parents=True, exist_ok=True)
    config.settings_directory.mkdir(parents=True, exist_ok=True)


def run_command(command: List[str]) -> None:
    print("Executing:", " ".join(command))
    subprocess.run(command, check=True)


def label_for_notebook(notebook_id: str, labels: Dict[str, str]) -> str:
    if notebook_id not in labels:
        labels[notebook_id] = f"Scribe Notebook {datetime.now().strftime('%Y-%m-%d %H-%M-%S')}"
    return labels[notebook_id]


def convert_notebook(config: Config, guid: str, guid_folder_path: Path, label: str) -> Path:
    output_epub_path = config.output_epub_directory / f"{guid}.epub"
    safe_label = safe_filename(label)
    output_pdf_path = config.output_pdf_directory / f"{safe_label}.pdf"

    run_command([
        config.calibre_path,
        "-r",
        config.plugin_name,
        "--",
        str(guid_folder_path),
        str(output_epub_path),
    ])
    run_command([
        config.ebook_convert_path,
        str(output_epub_path),
        str(output_pdf_path),
    ])
    return output_pdf_path


def update_obsidian(config: Config, converted_pdfs: List[Tuple[str, Path]]) -> None:
    if not config.update_obsidian or not converted_pdfs:
        return

    obsidian_target = config.obsidian_target_dir
    attachments_dir = obsidian_target / config.obsidian_attachments_subdir
    attachments_dir.mkdir(parents=True, exist_ok=True)

    for label, pdf_path in converted_pdfs:
        safe_label = safe_filename(label)
        copied_pdf = attachments_dir / pdf_path.name
        shutil.copy2(pdf_path, copied_pdf)

        md_path = obsidian_target / f"{safe_label}.md"
        rel = copied_pdf.relative_to(obsidian_target)
        content = [
            f"# {safe_label}",
            "",
            f"- Attachment: [{copied_pdf.name}]({rel.as_posix()})",
            "",
        ]
        md_path.write_text("\n".join(content), encoding="utf-8")


def process_device(config: Config, mount_point: Path, notebooks_dir: Path) -> None:
    print(f"Kindle Scribe connection detected at {mount_point}")
    ensure_dirs(config)

    labels = load_json(config.labels_file_path, {})
    guid_re = re.compile(config.guid_pattern)
    converted: List[Tuple[str, Path]] = []

    for folder in notebooks_dir.iterdir():
        if not folder.is_dir() or not guid_re.match(folder.name):
            continue

        nbk_src = folder / config.nbk_file_name
        if not nbk_src.is_file():
            continue

        label = label_for_notebook(folder.name, labels)
        guid_dest = config.destination_path / folder.name
        guid_dest.mkdir(parents=True, exist_ok=True)
        nbk_dest = guid_dest / config.nbk_file_name

        previous_hash = sha256_file(nbk_dest) if nbk_dest.exists() else ""
        shutil.copy2(nbk_src, nbk_dest)
        current_hash = sha256_file(nbk_dest)

        if current_hash == previous_hash:
            print(f"Notebook unchanged - {nbk_dest}")
            continue

        print(f"Notebook change detected. Processing: {nbk_dest}")
        pdf_path = convert_notebook(config, folder.name, guid_dest, label)
        converted.append((label, pdf_path))

    save_json(config.labels_file_path, labels)
    update_obsidian(config, converted)
    print("Notebook conversion complete.")


def watch(config: Config) -> None:
    print("Watching for Kindle Scribe... Connect your device with a USB cable to sync your notebooks.")
    connected: Set[Path] = set()

    while True:
        mounts = discover_kindle_mounts(config)
        current = set(mounts.keys())

        disconnected = connected - current
        for mount in disconnected:
            print(f"Kindle Scribe disconnection detected at {mount}")

        for mount_point, notebooks_dir in mounts.items():
            if mount_point not in connected:
                try:
                    process_device(config, mount_point, notebooks_dir)
                except subprocess.CalledProcessError as e:
                    print(f"Command failed with exit code {e.returncode}: {e}")
                except Exception as e:
                    print(f"Error while processing device {mount_point}: {e}")

        connected = current
        time.sleep(max(config.poll_seconds, 1))


def run_once(config: Config) -> int:
    mounts = discover_kindle_mounts(config)
    if not mounts:
        print("No Kindle Scribe mount found.")
        return 1

    for mount_point, notebooks_dir in mounts.items():
        process_device(config, mount_point, notebooks_dir)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kindle Scribe watcher and exporter for macOS")
    parser.add_argument("mode", choices=["watch", "once"], help="Run continuously or process once")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to config JSON (default: {DEFAULT_CONFIG_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config).expanduser())
    if args.mode == "once":
        return run_once(config)
    watch(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
