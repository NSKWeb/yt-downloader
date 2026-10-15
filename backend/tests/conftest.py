"""Test configuration.

Points storage at a temp directory and avoids any real Redis connection. The
env vars are set before the app package is imported, since Settings() is
instantiated at import time.
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="ytdl-test-")
os.environ.setdefault("DOWNLOAD_DIR", _TMP)
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
