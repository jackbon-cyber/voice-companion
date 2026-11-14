from pathlib import Path

from core.edge.dialog.engine import create_dialog_engine


def test_engine_falls_back_when_model_missing():
    engine = create_dialog_engine(Path("D:/definitely/missing.gguf"))
    reply = engine.generate("sadness", "用户说今天很累")
    assert isinstance(reply, str)
    assert reply != ""


def test_engine_without_model_path_uses_phrase_bank():
    engine = create_dialog_engine(None)
    assert engine.generate("joy", "") != ""
