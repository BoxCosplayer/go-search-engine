import re
from pathlib import Path

from backend.app import __version__


def test_version_matches_latest_changelog_entry():
    changelog_lines = Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    version_line = next((line for line in changelog_lines if re.match(r"^##\s+\d+\.\d+\.\d+", line)), None)
    assert version_line, "No version heading found in CHANGELOG.md"
    changelog_version = re.match(r"^##\s+(\d+\.\d+\.\d+)", version_line).group(1)  # type: ignore[union-attr]
    assert __version__ == changelog_version, f"""__version__ {__version__} 
                                                does not match changelog {changelog_version}"""
