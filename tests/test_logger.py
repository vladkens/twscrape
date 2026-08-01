import time
from collections import OrderedDict

from twscrape.logger import LogOnce, logger


def test_log_once_logs_each_key_once(monkeypatch):
    logs = []
    monkeypatch.setattr(LogOnce, "seen", OrderedDict())
    monkeypatch.setattr(logger, "log", lambda level, message: logs.append((level, message)))

    LogOnce.once("a", "WARNING", "first")
    LogOnce.once("a", "WARNING", "duplicate")
    LogOnce.once("b", "WARNING", "second")

    assert logs == [("WARNING", "first"), ("WARNING", "second")]


def test_log_once_bounds_keys(monkeypatch):
    logs = []
    monkeypatch.setattr(LogOnce, "max_keys", 2)
    monkeypatch.setattr(LogOnce, "seen", OrderedDict())
    monkeypatch.setattr(logger, "log", lambda level, message: logs.append((level, message)))

    for key in ("a", "b", "c", "a"):
        LogOnce.once(key, "WARNING", key)

    assert [message for _level, message in logs] == ["a", "b", "c", "a"]
    assert list(LogOnce.seen) == ["c", "a"]


def test_log_throttled_reports_and_resets_count(monkeypatch):
    logs = []
    times = iter([0, 10, 20, 60, 70, 120])
    monkeypatch.setattr(LogOnce, "pending", OrderedDict())
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    monkeypatch.setattr(logger, "log", lambda level, message: logs.append((level, message)))

    for _ in range(6):
        LogOnce.throttled("a", "DEBUG", "message")

    assert logs == [
        ("DEBUG", "message"),
        ("DEBUG", "message (3 occurrences since last log)"),
        ("DEBUG", "message (2 occurrences since last log)"),
    ]


def test_log_throttled_bounds_independent_keys(monkeypatch):
    logs = []
    monkeypatch.setattr(LogOnce, "max_keys", 2)
    monkeypatch.setattr(LogOnce, "pending", OrderedDict())
    monkeypatch.setattr(logger, "log", lambda level, message: logs.append((level, message)))

    for key in ("a", "b", "c"):
        LogOnce.throttled(key, "DEBUG", key)

    assert [message for _level, message in logs] == ["a", "b", "c"]
    assert list(LogOnce.pending) == ["b", "c"]
