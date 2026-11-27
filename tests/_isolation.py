# Test isolation, imported by tests/__init__.py AND directly by each test module,
# so it applies however the suite is run (package mode or `discover -s tests`).
#
# Isolate the ATS learning store: tests record fake domains/audits, which must
# not leak into the tracked data/ats_learned_domains.json. Copy the seed file to
# a temp location and point ats_learning at it before any test imports it.
import atexit
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEED = os.path.join(_ROOT, "data", "ats_learned_domains.json")
_TMP_DIR = os.environ.get("ATS_TEST_TMP_DIR") or tempfile.mkdtemp(prefix="ats_learning_test_")
os.environ["ATS_TEST_TMP_DIR"] = _TMP_DIR
_TMP_FILE = os.path.join(_TMP_DIR, "ats_learned_domains.json")
if os.path.exists(_SEED) and not os.path.exists(_TMP_FILE):
    shutil.copyfile(_SEED, _TMP_FILE)
os.environ["ATS_LEARNED_DATA_FILE"] = _TMP_FILE

# If ats_learning was somehow imported already, redirect it too.
if "ats_learning" in sys.modules:
    sys.modules["ats_learning"].LEARNED_DATA_FILE = _TMP_FILE

atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)

# The per-job keyword cache must not touch the real database or data/ in tests.
os.environ["ATS_JD_CACHE"] = "file"
os.environ["ATS_JD_CACHE_FILE"] = os.path.join(_TMP_DIR, "jd_keyword_cache.json")
if "llm_matcher" in sys.modules:
    sys.modules["llm_matcher"]._JD_CACHE_FILE = os.environ["ATS_JD_CACHE_FILE"]
