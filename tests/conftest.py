import os
import tempfile

# Point the app at an isolated, throwaway SQLite file before anything else
# imports app.config/app.db, so tests never touch a real dev database.
_tmp_dir = tempfile.mkdtemp(prefix="entracte-test-")
os.environ.setdefault("ENTRACTE_DB_PATH", os.path.join(_tmp_dir, "test.db"))

from app.db import init_db  # noqa: E402

init_db()
