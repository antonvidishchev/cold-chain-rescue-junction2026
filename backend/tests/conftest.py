import os
import tempfile

# Point the app at a throwaway database before anything imports app.config.
_tmpdir = tempfile.mkdtemp(prefix="coldchain-test-")
os.environ["COLDCHAIN_DB_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["COLDCHAIN_GRACE_SECONDS"] = "0"
