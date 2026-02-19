import sys
import os

# Tell Python: "Look in backend/ for imports"
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)
