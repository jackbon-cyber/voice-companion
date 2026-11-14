import re
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]


def test_readme_has_all_four_sections():
    text = (CORE_ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("前置依赖", "环境变量", "启动顺序", "常用命令"):
        assert heading in text


def test_readme_contains_no_real_credential():
    text = (CORE_ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", text)


def test_quickstart_commands_reference_existing_scripts():
    core_root = CORE_ROOT
    text = (core_root / "README.md").read_text(encoding="utf-8")
    for script in ("scripts/start.ps1", "scripts/stop.ps1", "scripts/fetch-models.ps1", "scripts/chroma.ps1"):
        assert script in text
        assert (core_root / script).exists()
