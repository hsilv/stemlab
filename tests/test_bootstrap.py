import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.py"
spec = importlib.util.spec_from_file_location("stemlab_bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_auto_picks_cuda_only_with_a_gpu():
    assert bootstrap.choose_extra("auto", gpu=True) == "cuda"
    assert bootstrap.choose_extra("auto", gpu=False) == "inference"


def test_an_explicit_extra_wins_over_detection():
    assert bootstrap.choose_extra("inference", gpu=True) == "inference"
    assert bootstrap.choose_extra("cuda", gpu=False) == "cuda"


def test_the_sync_command_is_frozen_and_names_the_extra(tmp_path):
    command = bootstrap.sync_command("uv", tmp_path, "cuda")
    assert command[:3] == ["uv", "sync", "--frozen"]
    assert command[-2:] == ["--extra", "cuda"]
    assert str(tmp_path) in command


def test_dry_run_prints_the_command_and_changes_nothing(tmp_path, capsys):
    code = bootstrap.main(["--extra", "inference", "--uv", "/bin/true", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "--extra inference" in out and "--frozen" in out


def test_a_missing_uv_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: None)
    assert bootstrap.main(["--extra", "inference"]) == 2
    assert "uv was not found" in capsys.readouterr().err
