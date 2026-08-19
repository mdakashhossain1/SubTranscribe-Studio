#!/usr/bin/env python3
"""
Clean Unused SVG Files Tool for SubTranscribe Studio
===================================================
Scans the project codebase to identify referenced Bootstrap SVG icons (and any other SVG assets)
and safely removes or lists the unused SVG files to optimize repository and package size.

Usage:
  python clean_unused_svgs.py           # Scan and show summary (dry-run by default)
  python clean_unused_svgs.py --scan    # Explicit scan / dry-run mode
  python clean_unused_svgs.py --delete  # Delete unused SVG files
  python clean_unused_svgs.py --backup  # Backup unused SVGs before deleting
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Set, Tuple


def get_project_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent


def find_all_svgs(svg_dir: Path) -> Dict[str, Path]:
    """Find all SVG files in the target directory mapped by icon stem name."""
    if not svg_dir.exists():
        return {}
    return {p.stem: p for p in svg_dir.glob("*.svg")}


def find_source_files(root: Path) -> List[Path]:
    """Collect all relevant source and configuration files to scan for references."""
    valid_extensions = {
        ".py", ".spec", ".iss", ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".md", ".txt", ".qss", ".css", ".bat", ".sh"
    }
    ignored_dirs = {".venv", "venv", ".git", ".github", ".claude", ".agents", "__pycache__", "build", "dist"}

    source_files = []
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        # Skip ignored directories
        parts = set(item.parts)
        if parts & ignored_dirs:
            continue
        # Skip the SVG icons directory itself
        if "bs-icons" in parts or "bootstrap-icons-1.11.3" in parts:
            continue
        if item.suffix.lower() in valid_extensions:
            source_files.append(item)
    return source_files


def scan_svg_usage(root: Path, svg_dir: Path) -> Tuple[Dict[str, List[str]], Dict[str, Path]]:
    """
    Scan the project to find which SVGs are used and which are unused.
    Returns:
        (used_icons, unused_icons)
        used_icons: {icon_name: [list of files referencing it]}
        unused_icons: {icon_name: Path}
    """
    all_svgs = find_all_svgs(svg_dir)
    source_files = find_source_files(root)

    file_contents = {}
    for f in source_files:
        try:
            file_contents[f] = f.read_text(encoding="utf-8", errors="ignore")
        except Exception as err:
            print(f"Warning: Could not read {f}: {err}", file=sys.stderr)

    used_icons: Dict[str, List[str]] = {}
    unused_icons: Dict[str, Path] = {}

    for icon_name, svg_path in all_svgs.items():
        # Match as exact word inside string quotes or as filename.svg
        # Examples: "play-fill", 'play-fill', `play-fill`, play-fill.svg
        escaped_name = re.escape(icon_name)
        pattern = re.compile(
            rf'(?:["\'`]{escaped_name}["\'`]|{escaped_name}\.svg)',
            re.IGNORECASE
        )

        matched_files = []
        for src_file, content in file_contents.items():
            if pattern.search(content):
                rel_path = str(src_file.relative_to(root))
                matched_files.append(rel_path)

        if matched_files:
            used_icons[icon_name] = matched_files
        else:
            unused_icons[icon_name] = svg_path

    return used_icons, unused_icons


def format_size(num_bytes: int) -> str:
    """Format bytes to human readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"


def backup_files(files_to_backup: List[Path], backup_zip_path: Path) -> None:
    """Compress unused SVG files into a zip archive before deletion."""
    print(f"Creating backup at: {backup_zip_path} ...")
    backup_zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files_to_backup:
            zf.write(file_path, arcname=file_path.name)
    print(f"Backup created successfully ({format_size(backup_zip_path.stat().st_size)}).")


def main():
    parser = argparse.ArgumentParser(
        description="Clean unused SVG icons from SubTranscribe Studio."
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        default=False,
        help="Scan and list used/unused SVG files (dry-run mode)."
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete unused SVG files from the project."
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=False,
        help="Create a backup zip of unused SVG files before deleting."
    )
    parser.add_argument(
        "--backup-path",
        type=str,
        default="backup_unused_svgs.zip",
        help="Path for backup zip file (default: backup_unused_svgs.zip)."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Print detailed file list and references."
    )

    args = parser.parse_args()

    root = get_project_root()
    svg_dir = root / "subtranscribe" / "assets" / "bs-icons" / "bootstrap-icons-1.11.3"

    if not svg_dir.exists():
        print(f"Error: SVG directory not found at: {svg_dir}", file=sys.stderr)
        sys.exit(1)

    print("=" * 65)
    print(" SubTranscribe Studio - SVG Asset Cleaner")
    print("=" * 65)
    print(f"Project root : {root}")
    print(f"SVG directory: {svg_dir}")
    print("Scanning project source code for SVG icon references...")

    used_icons, unused_icons = scan_svg_usage(root, svg_dir)

    total_svgs = len(used_icons) + len(unused_icons)
    total_size = sum(p.stat().st_size for p in list(unused_icons.values()) + [svg_dir / f"{name}.svg" for name in used_icons if (svg_dir / f"{name}.svg").exists()])
    unused_size = sum(p.stat().st_size for p in unused_icons.values())
    used_size = total_size - unused_size

    print("\n" + "-" * 65)
    print(" Scan Results Summary:")
    print("-" * 65)
    print(f"Total SVG files found : {total_svgs:,} ({format_size(total_size)})")
    print(f"Active / Used SVGs    : {len(used_icons):,} ({format_size(used_size)})")
    print(f"Unused SVGs           : {len(unused_icons):,} ({format_size(unused_size)})")
    print(f"Potential space saving: {format_size(unused_size)} ({(unused_size/total_size*100 if total_size else 0):.1f}% reduction)")
    print("-" * 65)

    print("\nReferenced (Active) Icons in Codebase:")
    for icon_name in sorted(used_icons.keys()):
        files = used_icons[icon_name]
        file_summary = ", ".join(files[:2]) + (f" (+{len(files)-2} more)" if len(files) > 2 else "")
        print(f"  [KEEP] {icon_name}.svg  <- ({file_summary})")

    if args.verbose and unused_icons:
        print("\nUnused Icons List:")
        for name in sorted(unused_icons.keys()):
            print(f"  [REMOVE] {name}.svg")

    # If neither --delete nor --scan was explicitly specified, or --scan was given, show usage help
    if not args.delete:
        print("\n" + "=" * 65)
        print(" [DRY RUN COMPLETE] No files were deleted.")
        print(" To delete the unused SVG files, run:")
        print("   python clean_unused_svgs.py --delete")
        print(" To create a backup zip before deleting, run:")
        print("   python clean_unused_svgs.py --delete --backup")
        print("=" * 65)
        return

    # Deletion process
    if args.backup:
        backup_dest = Path(args.backup_path)
        if not backup_dest.is_absolute():
            backup_dest = root / backup_dest
        backup_files(list(unused_icons.values()), backup_dest)

    print(f"\nDeleting {len(unused_icons):,} unused SVG files...")
    deleted_count = 0
    deleted_bytes = 0

    for icon_name, svg_path in unused_icons.items():
        try:
            size = svg_path.stat().st_size
            svg_path.unlink()
            deleted_count += 1
            deleted_bytes += size
        except Exception as e:
            print(f"Error deleting {svg_path.name}: {e}", file=sys.stderr)

    print(f"Successfully deleted {deleted_count:,} unused SVG files.")
    print(f"Freed disk space: {format_size(deleted_bytes)}.")
    print(f"Remaining active SVG files: {len(used_icons):,}.")
    print("=" * 65)


if __name__ == "__main__":
    main()
