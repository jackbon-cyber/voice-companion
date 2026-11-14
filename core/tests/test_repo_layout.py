from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_ROOT.parent


def test_core_is_python_package_root():
    assert (CORE_ROOT / "requirements.txt").exists()


def test_model_weights_are_not_tracked():
    ignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "models/" in ignore_text
    assert "*.gguf" in ignore_text


def test_license_is_mit():
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
