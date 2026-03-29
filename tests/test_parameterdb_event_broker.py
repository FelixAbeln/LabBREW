from __future__ import annotations

import queue

from Services.parameterDB.parameterdb_service.event_broker import EventBroker



def test_event_broker_subscribe_publish_filter_and_unsubscribe() -> None:
    broker = EventBroker(default_max_queue=10)

    token_all, q_all, size_all = broker.subscribe()
    token_filtered, q_filtered, size_filtered = broker.subscribe(names=["temp"])

    assert size_all == 10
    assert size_filtered == 10
    assert broker.subscriber_count() == 2

    broker.publish({"event": "value_changed", "name": "temp", "value": 20})
    broker.publish({"event": "value_changed", "name": "pressure", "value": 2})

    all_events = [q_all.get_nowait(), q_all.get_nowait()]
    filtered_events = [q_filtered.get_nowait()]

    assert [item["name"] for item in all_events] == ["temp", "pressure"]
    assert [item["name"] for item in filtered_events] == ["temp"]

    broker.unsubscribe(token_filtered)
    assert broker.subscriber_count() == 1

    broker.unsubscribe(token_all)
    assert broker.subscriber_count() == 0



def test_event_broker_enforces_min_queue_size() -> None:
    broker = EventBroker(default_max_queue=0)

    _token, _queue, size = broker.subscribe(max_queue=0)

    assert size == 1



def test_event_broker_overflow_emits_notice_and_disconnects_stale_subscriber() -> None:
    broker = EventBroker(default_max_queue=1)
    token, q, _size = broker.subscribe(max_queue=1)

    broker.publish({"event": "value_changed", "name": "temp", "value": 1})
    broker.publish({"event": "value_changed", "name": "temp", "value": 2})

    overflow_notice = q.get_nowait()

    assert overflow_notice["event"] == "subscription_overflow"
    assert overflow_notice["subscription_id"] == token
    assert overflow_notice["dropped_events"] == 1
    assert broker.subscriber_count() == 0



def test_event_broker_publish_with_non_matching_filter_does_not_enqueue() -> None:
    broker = EventBroker(default_max_queue=5)
    _token, q, _size = broker.subscribe(names=["temp"])

    broker.publish({"event": "value_changed", "name": "ph", "value": 4.5})

    try:
        q.get_nowait()
        raise AssertionError("Queue should be empty for non-matching filtered event")
    except queue.Empty:
        pass
