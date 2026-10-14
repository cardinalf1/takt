"""
Takt Release & Update Packager
Automatically bundles an update patch zip or complete installer for distributing updates to friends.
Preserves user configurations so friends never lose their custom hotkeys or settings.
"""

import os
import sys
import json
import zipfile
import shutil
import argparse
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(REPO_ROOT, "dist")
TAKT_DIR = os.path.join(DIST_DIR, "Takt")

def package_update(version: str, notes: str = "Takt performance updates and improvements."):
    if not os.path.exists(TAKT_DIR):
        print(f"Error: {TAKT_DIR} does not exist. Run PyInstaller build first.")
        return

    os.makedirs(DIST_DIR, exist_ok=True)
    update_zip_name = f"Takt-Update-v{version}.zip"
    update_zip_path = os.path.join(DIST_DIR, update_zip_name)

    print(f"=== Packaging Takt Update v{version} ===")
    print(f"Output: {update_zip_path}")

    # Files/folders to exclude from the patch zip to avoid clobbering personal user data
    EXCLUDED_RELATIVE = [
        os.path.join("config", "app_config.yaml"),
        "logs",
        "recordings"
    ]

    count = 0
    with zipfile.ZipFile(update_zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(TAKT_DIR):
            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, TAKT_DIR)

                # Skip excluded user files
                if any(rel_path.startswith(ex) or rel_path.endswith(ex) for ex in EXCLUDED_RELATIVE):
                    continue

                zf.write(full_path, rel_path)
                count += 1

    size_mb = os.path.getsize(update_zip_path) / 1024 / 1024
    print(f"Update package complete: {count} files packaged ({size_mb:.1f} MB).")

    # Generate version.json manifest
    manifest = {
        "version": version,
        "release_date": datetime.now().strftime("%Y-%m-%d"),
        "filename": update_zip_name,
        "size_mb": round(size_mb, 2),
        "changelog": notes
    }
    manifest_path = os.path.join(DIST_DIR, "version.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Version manifest generated at: {manifest_path}")
    print("\nHow to send update to friends:")
    print(f"  1. Send them '{update_zip_name}'.")
    print(f"  2. They can double-click 'TaktUpdate.exe' inside it or click 'Install Update' in Takt Settings.")
    print("  3. Their settings, hotkeys, and history will remain 100% intact!\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package Takt Update")
    parser.add_argument("--version", "-v", default="1.0.1", help="Version number (e.g. 1.0.1)")
    parser.add_argument("--notes", "-n", default="Latest performance, audio, and UI enhancements.", help="Changelog notes")
    args = parser.parse_args()

    package_update(args.version, args.notes)
