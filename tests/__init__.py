"""Keep test action journals out of the user's persistent history."""
import os
import tempfile

_state = None
if "DEVOPS_AGENT_STATE_DIR" not in os.environ:
    _state = tempfile.TemporaryDirectory(prefix="devops-test-state-")
    os.environ["DEVOPS_AGENT_STATE_DIR"] = _state.name
