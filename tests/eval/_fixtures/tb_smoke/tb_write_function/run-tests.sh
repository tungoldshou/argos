pip install -q pytest 2>/dev/null
mkdir -p tests
cat > tests/test_outputs.py << 'PYEOF'
import sys
sys.path.insert(0, "./.app")
import importlib
mod = importlib.import_module("solution")
def test_add():
    assert mod.add(2, 3) == 5
    assert mod.add(-1, 1) == 0
PYEOF
python -m pytest tests/test_outputs.py -rA
