import subprocess

from filmroom.eval.cli import commit_info


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_commit_info_reports_the_head_and_uncommitted_changes(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    clean = commit_info(tmp_path)
    assert clean is not None and len(clean["sha"]) == 40 and clean["dirty"] is False
    (tmp_path / "a.txt").write_text("b")
    assert commit_info(tmp_path) == {"sha": clean["sha"], "dirty": True}


def test_commit_info_is_none_outside_git(tmp_path):
    assert commit_info(tmp_path) is None
