"""battery-connectivity-v1 matching rules; no database needed."""

import sys
from datetime import UTC, datetime, timedelta

from conftest import all_services

all_services()  # registers the service handler modules
CORRELATION = sys.modules["signal_correlation_handlers"]
Signal = CORRELATION.Signal
RULE = CORRELATION.RULES_BY_ID["battery-connectivity-v1"]

T0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def battery(event_id: str, minute: float, voltage: float = 11.5) -> Signal:
    return Signal(event_id, "battery_voltage", "warning", at(minute), {"voltage": voltage})


def missed(event_id: str, minute: float) -> Signal:
    return Signal(event_id, "heartbeat_missed", "warning", at(minute), {})


def diagnostic(event_id: str, minute: float, code: str = "P0562") -> Signal:
    return Signal(event_id, "diagnostic_failure", "critical", at(minute), {"dtcCode": code})


def ids(match) -> list[str]:
    return [signal.event_id for _, signal in match] if match else []


def test_sequence_within_window_matches_in_any_arrival_order() -> None:
    signals = [diagnostic("evt_c", 9), battery("evt_a", 0), missed("evt_b", 5)]
    assert ids(RULE.match(signals)) == ["evt_a", "evt_b", "evt_c"]
    assert [step.name for step, _ in RULE.match(signals)] == [
        "low_battery", "heartbeat_missed", "diagnostic_failure"
    ]


def test_window_is_twelve_minutes_inclusive() -> None:
    assert RULE.match([battery("evt_a", 0), missed("evt_b", 6), diagnostic("evt_c", 12)])
    late = [battery("evt_a", 0), missed("evt_b", 6), diagnostic("evt_c", 12.01)]
    assert RULE.match(late) is None


def test_order_matters_and_voltage_must_be_low() -> None:
    assert RULE.match([missed("evt_b", 0), battery("evt_a", 1), diagnostic("evt_c", 2)]) is None
    assert RULE.match([battery("evt_a", 0), diagnostic("evt_c", 1), missed("evt_b", 2)]) is None
    healthy = [battery("evt_a", 0, voltage=11.8), missed("evt_b", 1), diagnostic("evt_c", 2)]
    assert RULE.match(healthy) is None


def test_equal_timestamps_are_ordered_by_event_id() -> None:
    same = [battery("evt_1", 0), missed("evt_2", 0), diagnostic("evt_3", 0)]
    assert ids(RULE.match(same)) == ["evt_1", "evt_2", "evt_3"]
    reversed_ids = [battery("evt_3", 0), missed("evt_2", 0), diagnostic("evt_1", 0)]
    assert RULE.match(reversed_ids) is None


def test_earliest_finish_then_earliest_start_then_lowest_ids() -> None:
    signals = [
        battery("evt_a1", 0), battery("evt_a2", 1), missed("evt_b1", 2), missed("evt_b0", 2),
        diagnostic("evt_c1", 4), diagnostic("evt_c2", 5),
    ]
    assert ids(RULE.match(signals)) == ["evt_a1", "evt_b0", "evt_c1"]
    # A second battery reading too early to fit with the earliest diagnostic is skipped.
    shifted = [battery("evt_a0", -10), *signals]
    assert ids(RULE.match(shifted)) == ["evt_a1", "evt_b0", "evt_c1"]


def test_include_restricts_to_matches_using_the_new_signal() -> None:
    signals = [battery("evt_a", 0), missed("evt_b", 1), diagnostic("evt_c", 2),
               diagnostic("evt_d", 3)]
    assert ids(RULE.match(signals, include="evt_d")) == ["evt_a", "evt_b", "evt_d"]
    assert RULE.match(signals, include="evt_unrelated") is None


def test_case_symptoms_and_ids_are_stable() -> None:
    match = RULE.match([battery("evt_a", 0), missed("evt_b", 1), diagnostic("evt_c", 2)])
    triggers = [(step.name, signal) for step, signal in match]
    assert CORRELATION.case_symptoms(RULE, triggers) == [
        "diagnostic_failure", "dtc_p0562", "low_voltage", "missed_heartbeat"
    ]
    first = CORRELATION.incident_ids(RULE, "veh_1", "evt_a")
    assert first == CORRELATION.incident_ids(RULE, "veh_1", "evt_a")
    assert first != CORRELATION.incident_ids(RULE, "veh_2", "evt_a")
    assert first[0].startswith("inc_") and first[1].startswith("trace_")
