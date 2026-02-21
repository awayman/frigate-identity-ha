#!/usr/bin/env python3
"""Release automation for frigate-identity-ha.

Usage:
    python release.py 0.2.0          # Release specific version
    python release.py patch           # Bump patch: 0.1.1 -> 0.1.2
    python release.py minor           # Bump minor: 0.1.1 -> 0.2.0
    python release.py major           # Bump major: 0.1.1 -> 1.0.0
    python release.py 0.2.0 --dry-run # Preview without making changes
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
MANIFEST_JSON = REPO_ROOT / "custom_components" / "frigate_identity" / "manifest.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def run(cmd: list[str], check: bool = True, capture: bool = False) -> str:
    """Run a shell command from the repo root."""
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, check=check,
        capture_output=capture, text=True,
    )
    return result.stdout.strip() if capture else ""


def get_current_version() -> str:
    """Read version from manifest.json."""
    data = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version:
        sys.exit("ERROR: Could not find version in manifest.json")
    return version


def bump_version(current: str, bump_type: str) -> str:
    """Compute the next version given a bump type."""
    major, minor, patch = map(int, current.split("."))
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        sys.exit(f"ERROR: Unknown bump type '{bump_type}'")


def validate_semver(version: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


def update_manifest_json(new_version: str) -> None:
    """Update version in manifest.json."""
    data = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    data["version"] = new_version
    MANIFEST_JSON.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  Updated {MANIFEST_JSON.relative_to(REPO_ROOT)} -> {new_version}")


def update_changelog(new_version: str) -> None:
    """Move [Unreleased] contents to a new version section with today's date."""
    text = CHANGELOG.read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Replace [Unreleased] with new version, add fresh [Unreleased] section
    new_header = f"## [Unreleased]\n\n## [{new_version}] - {today}"
    updated = text.replace("## [Unreleased]", new_header, 1)

    CHANGELOG.write_text(updated, encoding="utf-8")
    print(f"  Updated CHANGELOG.md with [{new_version}] - {today}")


def check_clean_working_tree() -> None:
    """Ensure no uncommitted changes (except what we're about to modify)."""
    status = run(["git", "status", "--porcelain"], capture=True)
    if status:
        print("WARNING: Working tree has uncommitted changes:")
        print(status)
        response = input("Continue anyway? [y/N] ").strip().lower()
        if response != "y":
            sys.exit("Aborted.")


def check_tag_exists(version: str) -> bool:
    """Check if a git tag already exists."""
    tags = run(["git", "tag", "--list", f"v{version}"], capture=True)
    return bool(tags)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a release for frigate-identity-ha")
    parser.add_argument("version", help="Version number (e.g. 0.2.0) or bump type (major/minor/patch)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying them")
    parser.add_argument("--no-push", action="store_true", help="Commit and tag locally but don't push")
    args = parser.parse_args()

    current = get_current_version()
    print(f"Current version: {current}")

    # Determine new version
    if args.version in ("major", "minor", "patch"):
        new_version = bump_version(current, args.version)
    elif validate_semver(args.version):
        new_version = args.version
    else:
        sys.exit(f"ERROR: '{args.version}' is not a valid semver or bump type (major/minor/patch)")

    if new_version == current:
        sys.exit(f"ERROR: New version {new_version} is the same as current version")

    print(f"New version:     {new_version}")

    if check_tag_exists(new_version):
        sys.exit(f"ERROR: Tag v{new_version} already exists")

    if args.dry_run:
        print("\n[DRY RUN] Would perform:")
        print(f"  1. Update manifest.json version to {new_version}")
        print(f"  2. Update CHANGELOG.md with [{new_version}] - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
        print(f"  3. git commit -m 'Release v{new_version}'")
        print(f"  4. git tag v{new_version}")
        print(f"  5. git push origin main --tags")
        return

    check_clean_working_tree()

    # Apply changes
    print("\nApplying changes:")
    update_manifest_json(new_version)
    update_changelog(new_version)

    # Git operations
    print("\nGit operations:")
    run(["git", "add", str(MANIFEST_JSON), str(CHANGELOG)])
    run(["git", "commit", "-m", f"Release v{new_version}"])
    print(f"  Committed: Release v{new_version}")

    run(["git", "tag", "-a", f"v{new_version}", "-m", f"Release v{new_version}"])
    print(f"  Tagged: v{new_version}")

    if args.no_push:
        print("\n--no-push specified. To push later:")
        print(f"  git push origin main --tags")
    else:
        run(["git", "push", "origin", "main", "--tags"])
        print(f"  Pushed to origin/main with tag v{new_version}")

    print(f"\nRelease v{new_version} complete!")
    print("GitHub Actions will now create the GitHub Release.")


if __name__ == "__main__":
    main()
