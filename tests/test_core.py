"""Non-regression tests for Pulse core."""
import time, threading
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pulse.collectors.base import Collector, SampleState
from pulse.collectors.cpu import CpuCollector
from pulse.history import History
from pulse.app import Sampler, PulseApp


def test_cpu_stat_fields():
    c = CpuCollector()
    result = c.collect()
    total = result.get("total")
    breakdown = result.get("breakdown") or {}
    # steal doit exister après correction du slicing
    assert "steal" in breakdown, f"steal absent: {breakdown.keys()}"
    print("test_cpu_stat_fields OK")


def test_history_gpu_separate():
    h = History()
    h.update({"gpu": {"gpus": [{"util": 42, "temp": 55}]}})
    vals = h.values("gpu_util_0")
    assert len(vals) == 1 and vals[0] == 42.0
    print("test_history_gpu_separate OK")


def test_sampler_stop():
    from pulse.collectors import Registry
    reg = Registry()
    s = Sampler(reg, 0.1)
    s.start()
    time.sleep(0.25)
    s.stop()
    s.join(timeout=1.0)
    assert not s.is_alive(), "Sampler did not stop cleanly"
    print("test_sampler_stop OK")


if __name__ == "__main__":
    test_cpu_stat_fields()
    test_history_gpu_separate()
    test_sampler_stop()
