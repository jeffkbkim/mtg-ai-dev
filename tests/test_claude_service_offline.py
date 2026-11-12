"""claude_service.offline_reason: the short reason shown in the game when the model can't be reached."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine" / "playmat"), str(ROOT / "play")]
from claude_service import offline_reason  # noqa: E402


def test_not_logged_in():
    assert offline_reason(RuntimeError("claude error: Not logged in · Please run /login")).startswith("not logged in")


def test_usage_limit_and_other_errors():
    assert offline_reason(RuntimeError("Claude usage limit reached")) == "usage limit reached"
    assert offline_reason(ValueError("boom\nmore")) == "its model call failed (boom)"
    assert offline_reason(TimeoutError()) == "its model call failed (TimeoutError)"
