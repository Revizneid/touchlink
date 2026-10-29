from pathlib import Path


def test_release_3_0_metadata_is_present_and_versioned():
    repo = Path(__file__).resolve().parents[1]
    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "version = \"3.0.0\"" in text

    changelog = repo / "CHANGELOG.md"
    accept = repo / "docs" / "ACCEPTANCE.md"
    architecture = repo / "docs" / "ARCHITECTURE.md"
    readme_en = repo / "README.en.md"

    assert changelog.exists()
    assert accept.exists()
    assert architecture.exists()
    assert readme_en.exists()

    assert "3.0.0" in changelog.read_text(encoding="utf-8")
    assert "install" in accept.read_text(encoding="utf-8").lower()
