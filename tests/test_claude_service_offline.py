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


def test_safe_choice_keeps_the_hand_and_passes():
    from claude_service import safe_choice
    mull = {"kind": "USE", "prompt": "Mulligan? Your hand has 7 cards", "options": [{"label": "YES mulligan"}, {"label": "NO keep this hand"}]}
    assert safe_choice(mull) == 1
    assert safe_choice({"kind": "PRIORITY", "prompt": "priority", "options": [{"label": "PASS"}, {"label": "Spell | X"}]}) == 0
    assert safe_choice({"kind": "ATTACK", "prompt": "declare attackers", "options": [{"label": "DONE"}, {"label": "Bear attacks"}]}) == 0


def test_seat_env_drops_claude_code_session_auth(monkeypatch):
    from players import ClaudePlayer
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://stale")
    monkeypatch.setenv("CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH", "1")
    p = object.__new__(ClaudePlayer)
    p.effort = "high"
    env = p._env()
    assert "ANTHROPIC_BASE_URL" not in env and "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH" not in env
    assert env["CLAUDE_EFFORT"] == "high" and env["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "5m"
