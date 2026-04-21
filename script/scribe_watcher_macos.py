#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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
    mtp_enabled: bool
    mtp_device_name_substring: str
    mtp_detect_command: str
    mtp_folders_command: str
    mtp_files_command: str
    mtp_get_file_command: str


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
        mtp_enabled=bool(raw.get("mtp_enabled", True)),
        mtp_device_name_substring=raw.get("mtp_device_name_substring", "Kindle"),
        mtp_detect_command=raw.get("mtp_detect_command", "mtp-detect"),
        mtp_folders_command=raw.get("mtp_folders_command", "mtp-folders"),
        mtp_files_command=raw.get("mtp_files_command", "mtp-files"),
        mtp_get_file_command=raw.get("mtp_get_file_command", "mtp-getfile"),
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


def run_command_output(command: List[str]) -> str:
    print("Executing:", " ".join(command))
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout


def parse_mtp_blocks(output: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    current: Dict[str, str] = {}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip()

    if current:
        blocks.append(current)
    return blocks


def first_non_empty(data: Dict[str, str], keys: List[str]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return ""


def parse_numeric_id(value: str) -> Optional[int]:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.lower().startswith("0x"):
        try:
            return int(cleaned, 16)
        except ValueError:
            return None
    if cleaned.isdigit():
        return int(cleaned)
    return None


def parse_mtp_folder_paths(output: str) -> Dict[int, str]:
    records: Dict[int, Tuple[Optional[int], str]] = {}
    for block in parse_mtp_blocks(output):
        folder_id = parse_numeric_id(first_non_empty(block, ["Folder ID", "ID"]))
        parent_id = parse_numeric_id(first_non_empty(block, ["Parent ID", "ParentID"]))
        name = first_non_empty(block, ["Name", "Folder name", "Folder Name"])
        if folder_id is None or not name:
            continue
        records[folder_id] = (parent_id, name.strip("/"))

    cache: Dict[int, str] = {}

    def build_path(folder_id: int, seen: Set[int]) -> str:
        if folder_id in cache:
            return cache[folder_id]
        if folder_id in seen:
            return ""
        parent_id, name = records.get(folder_id, (None, ""))
        if not name:
            return ""

        if parent_id in (None, 0, folder_id):
            path = name
        elif parent_id in records:
            parent_path = build_path(parent_id, seen | {folder_id})
            path = f"{parent_path}/{name}" if parent_path else name
        else:
            path = name

        cache[folder_id] = path.strip("/")
        return cache[folder_id]

    for folder_id in records:
        build_path(folder_id, set())
    return cache


def discover_mtp_notebooks(config: Config) -> Dict[str, int]:
    if not config.mtp_enabled:
        return {}

    detect_cmd = shlex.split(config.mtp_detect_command)
    folders_cmd = shlex.split(config.mtp_folders_command)
    files_cmd = shlex.split(config.mtp_files_command)
    if not detect_cmd or not folders_cmd or not files_cmd:
        return {}

    try:
        detection_output = run_command_output(detect_cmd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"MTP detection skipped: {e}")
        return {}

    detection_text = detection_output.lower()
    if "no raw devices found" in detection_text:
        return {}
    if config.mtp_device_name_substring.lower() not in detection_text:
        return {}

    try:
        folder_output = run_command_output(folders_cmd)
        file_output = run_command_output(files_cmd)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"MTP listing failed: {e}")
        return {}

    folder_paths = parse_mtp_folder_paths(folder_output)
    notebooks: Dict[str, int] = {}
    guid_re = re.compile(config.guid_pattern)
    relative_paths = [p.replace("\\", "/").strip("/") for p in config.notebooks_relative_paths]

    for block in parse_mtp_blocks(file_output):
        file_id = parse_numeric_id(first_non_empty(block, ["File ID", "Item ID", "ID"]))
        parent_id = parse_numeric_id(first_non_empty(block, ["Parent ID", "ParentID"]))
        filename = first_non_empty(block, ["Filename", "Name", "File Name"])
        if file_id is None or parent_id is None or filename != config.nbk_file_name:
            continue

        parent_path = folder_paths.get(parent_id, "").strip("/")
        if not parent_path:
            continue
        guid = parent_path.split("/")[-1]
        if not guid_re.match(guid):
            continue

        for relative in relative_paths:
            if parent_path == f"{relative}/{guid}":
                notebooks[guid] = file_id
                break

    return notebooks


def pull_mtp_nbk_file(config: Config, file_id: int, destination: Path) -> None:
    get_cmd = shlex.split(config.mtp_get_file_command)
    if not get_cmd:
        raise RuntimeError("MTP get-file command is not configured.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_command([*get_cmd, str(file_id), str(destination)])


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


def process_notebook_nbk(
    config: Config,
    guid: str,
    nbk_src: Path,
    labels: Dict[str, str],
    converted: List[Tuple[str, Path]],
) -> None:
    label = label_for_notebook(guid, labels)
    guid_dest = config.destination_path / guid
    guid_dest.mkdir(parents=True, exist_ok=True)
    nbk_dest = guid_dest / config.nbk_file_name

    previous_hash = sha256_file(nbk_dest) if nbk_dest.exists() else ""
    if nbk_src.resolve() != nbk_dest.resolve():
        shutil.copy2(nbk_src, nbk_dest)
    current_hash = sha256_file(nbk_dest)

    if current_hash == previous_hash:
        print(f"Notebook unchanged - {nbk_dest}")
        return

    print(f"Notebook change detected. Processing: {nbk_dest}")
    pdf_path = convert_notebook(config, guid, guid_dest, label)
    converted.append((label, pdf_path))


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
        process_notebook_nbk(config, folder.name, nbk_src, labels, converted)

    save_json(config.labels_file_path, labels)
    update_obsidian(config, converted)
    print("Notebook conversion complete.")


def process_mtp_device(config: Config, notebooks: Optional[Dict[str, int]] = None) -> None:
    print("Kindle Scribe MTP connection detected")
    ensure_dirs(config)

    labels = load_json(config.labels_file_path, {})
    converted: List[Tuple[str, Path]] = []
    if notebooks is None:
        notebooks = discover_mtp_notebooks(config)
    if not notebooks:
        print("No Kindle Scribe notebooks found over MTP.")
        return

    with tempfile.TemporaryDirectory(prefix="scribe_mtp_") as temp_dir:
        temp_path = Path(temp_dir)
        for guid, file_id in notebooks.items():
            local_nbk = temp_path / f"{guid}.nbk"
            try:
                pull_mtp_nbk_file(config, file_id, local_nbk)
                process_notebook_nbk(config, guid, local_nbk, labels, converted)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"Failed to pull MTP notebook for {guid}: {e}")

    save_json(config.labels_file_path, labels)
    update_obsidian(config, converted)
    print("Notebook conversion complete.")


def watch(config: Config) -> None:
    print("Watching for Kindle Scribe... Connect your device with a USB cable to sync your notebooks.")
    connected: Set[str] = set()

    while True:
        mounts = discover_kindle_mounts(config)
        mtp_notebooks: Dict[str, int] = {}
        current: Set[str] = {str(mount) for mount in mounts.keys()}
        if not mounts:
            mtp_notebooks = discover_mtp_notebooks(config)
            if mtp_notebooks:
                current.add("mtp://kindle")

        disconnected = connected - current
        for source in disconnected:
            print(f"Kindle Scribe disconnection detected at {source}")

        if "mtp://kindle" in current and "mtp://kindle" not in connected:
            try:
                process_mtp_device(config, notebooks=mtp_notebooks)
            except Exception as e:
                print(f"Error while processing Kindle Scribe over MTP: {e}")

        for mount_point, notebooks_dir in mounts.items():
            mount_key = str(mount_point)
            if mount_key not in connected:
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
    if mounts:
        for mount_point, notebooks_dir in mounts.items():
            process_device(config, mount_point, notebooks_dir)
        return 0

    mtp_notebooks = discover_mtp_notebooks(config)
    if mtp_notebooks:
        process_mtp_device(config, notebooks=mtp_notebooks)
        return 0

    print("No Kindle Scribe mount or MTP device found.")
    return 1


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
