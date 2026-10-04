"""Pure function tests for the P2P silence alert rule."""

from datetime import timedelta
from yupay.core.clock import now
from yupay_scheduler.jobs.p2p_sweep import silence_alert_due


def test_silence_alert_rule() -> None:
    """Test the silence alert logic against various conditions."""
    t = now()
    assert silence_alert_due(None, 1, t)
    assert silence_alert_due(t - timedelta(hours=7), 1, t)
    assert not silence_alert_due(t - timedelta(hours=1), 1, t)
    assert not silence_alert_due(t - timedelta(hours=7), 0, t)
