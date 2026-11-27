# Tests package
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
_TMP_DIR = tempfile.mkdtemp(prefix="ats_learning_test_")
_TMP_FILE = os.path.join(_TMP_DIR, "ats_learned_domains.json")
if os.path.exists(_SEED):
    shutil.copyfile(_SEED, _TMP_FILE)
os.environ["ATS_LEARNED_DATA_FILE"] = _TMP_FILE

# If ats_learning was somehow imported already, redirect it too.
if "ats_learning" in sys.modules:
    sys.modules["ats_learning"].LEARNED_DATA_FILE = _TMP_FILE

atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)
