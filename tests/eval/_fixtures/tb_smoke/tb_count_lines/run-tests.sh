mkdir -p tests
cat > tests/test_outputs.py << 'PYEOF'
import subprocess
def test_count():
    r = subprocess.run(["python", "./.app/solution.py"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "3"
PYEOF
python -m pytest tests/test_outputs.py -rA
