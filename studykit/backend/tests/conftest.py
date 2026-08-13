import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
STUDYKIT_DIR = BACKEND_DIR.parent

# Support both invocation styles: `pytest` from backend/ (flat imports like
# `import main`) and `pytest backend/tests` from studykit/ (as CI does, using
# `from backend.difficulty_engine import ...`).
for path in (BACKEND_DIR, STUDYKIT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("LLAMA_CLOUD_API_KEY", "test-llama-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
os.environ.setdefault("ENV", "test")