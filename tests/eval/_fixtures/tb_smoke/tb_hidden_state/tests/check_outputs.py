import pathlib, pytest
def test_answer():
    assert pathlib.Path("/app/answer.txt").read_text().strip() == "ground-truth-answer"
