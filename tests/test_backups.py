import pytest
from pathlib import Path
import json
import hashlib
from proseview.server import _create_file_backup

def test_create_file_backup(tmp_path):
    # Setup mock repo
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manuscript = repo_root / "manuscript"
    manuscript.mkdir()
    scene = manuscript / "scene.md"
    scene.write_text("Hello", encoding="utf-8")
    
    # Run backup
    _create_file_backup(scene, "Hello", "Hello World", "Manual Save", str(repo_root))
    
    # Verify backup exists
    rel_path = scene.relative_to(repo_root).as_posix()
    path_hash = hashlib.md5(rel_path.encode("utf-8")).hexdigest()
    backups_dir = repo_root / ".proseview" / "backups" / path_hash
    assert backups_dir.exists()
    backups = list(backups_dir.glob("*.json"))
    assert len(backups) == 1
    
    # Check metadata
    with open(backups[0], "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["source"] == "Manual Save"
        assert meta["content"] == "Hello"
        assert "Hello World" not in meta["content"]
        assert meta["word_count"] == 1
        assert "lines" in meta["diff_summary"] or meta["diff_summary"] == "No changes"
