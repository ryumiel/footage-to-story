"""Repository policy checks; no real job files or remote Git operations."""
from pathlib import Path
import shutil
import subprocess
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = {
    "footage-pipeline", "prepare-analysis", "analyze-footage-gemini", "build-selects",
    "build-story", "build-edit-plan", "review-edit-plan", "export-resolve",
}


def test_exact_canonical_skill_set_and_matching_frontmatter():
    paths = list((ROOT / ".agents/skills").glob("*/SKILL.md"))
    assert {p.parent.name for p in paths} == SKILL_NAMES
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {path.parent.name}\ndescription: ")
        assert "schemas/2.0.0/" in text
        assert "AGENTS.md" in text


def test_no_install_or_copy_layer_is_reintroduced():
    assert not (ROOT / "skills").exists()
    assert not (ROOT / "integrations").exists()
    assert not list((ROOT / "scripts").glob("install*skill*"))
    assert not list((ROOT / "scripts").glob("package*skill*"))


def test_no_unversioned_active_schemas():
    assert not list((ROOT / "schemas").glob("*.schema.json"))
    assert len(list((ROOT / "schemas/2.0.0").glob("*.schema.json"))) == 8


def test_english_source_text_has_no_accidental_korean_prose():
    for suffix in ("*.md", "*.py", "*.yaml", "*.toml"):
        for path in ROOT.rglob(suffix):
            if any(part in {".git", ".venv", "artifacts", ".pytest_cache", "build"} for part in path.parts):
                continue
            assert not re.search(r"[\uac00-\ud7a3]", path.read_text(encoding="utf-8")), path


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable unavailable")
@pytest.mark.parametrize("path,ignored", [
    (".agents/skills/build-story/SKILL.md", False),
    ("schemas/2.0.0/analysis.schema.json", False),
    ("examples/contracts/edit-plan.json", False),
    ("docs/review.md", False),
    ("pyproject.toml", False),
    ("work/private-job/edit_plan.json", True),
    ("work/private-job/story_bible.md", True),
    ("artifacts/validation/junit.xml", True),
    (".ephemeral/m1-implementation-plan.md", True),
    ("cache/model-response.json", True),
    ("logs/private-run.log", True),
    (".agents/logs/session.json", True),
    ("dist/skill.zip", True),
    ("original.MP4", True),
    ("original.Mp4", True),
    ("thumbnail.JPG", True),
    ("thumbnail.PNG", True),
    ("camera.BRAW", True),
    ("timeline.fcpxml", True),
    ("subtitles.srt", True),
    (".env", True),
    (".env.example", False),
])
def test_source_and_runtime_ignore_policy(tmp_path, path, ignored):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    shutil.copy2(ROOT / ".gitignore", tmp_path / ".gitignore")
    result = subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "--no-index", "-q", path],
                            capture_output=True)
    assert result.returncode == (0 if ignored else 1)
