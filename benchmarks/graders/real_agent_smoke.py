import importlib.util
import sys
from pathlib import Path


workspace = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("calculator", workspace / "calculator.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

assert module.safe_divide(7, 2) == 3.5, "division must preserve fractional values"
assert module.safe_divide(-3, 2) == -1.5, "negative division must preserve fractional values"
assert module.safe_divide(1, 0) is None, "zero denominator must return None"
print("hidden grader passed")
