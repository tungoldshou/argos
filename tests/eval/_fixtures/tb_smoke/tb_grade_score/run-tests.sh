pip install -q pytest 2>/dev/null
mkdir -p tests
cat > tests/test_outputs.py << 'PYEOF'
import sys, importlib
sys.path.insert(0, "./.app")
mod = importlib.import_module("solution")
def test_grade():
    assert mod.grade(95) == "A"
    assert mod.grade(90) == "A"
    assert mod.grade(85) == "B"
    assert mod.grade(80) == "B"
    assert mod.grade(75) == "C"
    assert mod.grade(70) == "C"
    assert mod.grade(65) == "D"
    assert mod.grade(60) == "D"
    assert mod.grade(59) == "F"
    assert mod.grade(0) == "F"
PYEOF
python -m pytest tests/test_outputs.py -rA
