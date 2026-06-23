"""Unit tests for the SSE progress broker (per-kit pub/sub fan-out)."""
from app.detection.application.progress_broker import ProgressBroker

KIT = "uflex-kit-001"


def test_publish_reaches_subscriber():
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    broker.publish(KIT, {"reps_detected": 1})
    assert q.get_nowait() == {"reps_detected": 1}


def test_two_subscribers_both_receive():
    broker = ProgressBroker()
    a = broker.subscribe(KIT)
    b = broker.subscribe(KIT)
    broker.publish(KIT, {"reps_detected": 2})
    assert a.get_nowait() == {"reps_detected": 2}
    assert b.get_nowait() == {"reps_detected": 2}


def test_publish_to_other_serial_not_received():
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    broker.publish("other-kit", {"reps_detected": 9})
    assert q.empty()


def test_unsubscribe_stops_delivery():
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    broker.unsubscribe(KIT, q)
    broker.publish(KIT, {"reps_detected": 1})
    assert q.empty()


def test_full_queue_drops_without_raising():
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    for i in range(200):  # well past the queue's bound
        broker.publish(KIT, {"i": i})
    assert q.full()  # capped, and no exception was raised
