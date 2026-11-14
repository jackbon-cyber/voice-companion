import pytest

from core.edge.session.state_machine import (
    DEFAULT_INTERRUPT_LATENCY_MS,
    SessionState,
    SessionStateMachine,
)


def test_initial_state_is_idle():
    assert SessionStateMachine().state() is SessionState.IDLE


def test_user_speech_moves_to_listening():
    machine = SessionStateMachine()

    machine.on_user_speech_start(0)

    assert machine.state() is SessionState.LISTENING


def test_local_processing_moves_to_thinking():
    machine = SessionStateMachine()
    machine.on_user_speech_start(0)

    machine.on_local_processing_started(100)

    assert machine.state() is SessionState.THINKING


def test_cloud_wait_moves_to_waiting_cloud():
    machine = SessionStateMachine()

    machine.on_cloud_wait_started(0)

    assert machine.state() is SessionState.WAITING_CLOUD


def test_playback_moves_to_speaking_and_back_to_idle():
    machine = SessionStateMachine()

    machine.on_playback_started(0)
    assert machine.state() is SessionState.SPEAKING

    machine.on_playback_finished(500)
    assert machine.state() is SessionState.IDLE


def test_barge_in_during_speaking_reports_event():
    machine = SessionStateMachine()
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(120)

    assert event is not None
    assert event.state is SessionState.SPEAKING
    assert machine.state() is SessionState.INTERRUPTED


def test_barge_in_preserves_recognized_text():
    """打断只丢未播出的音频，已识别文本必须保留。"""
    machine = SessionStateMachine()
    machine.on_recognized("今天天气不错")
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(100)

    assert event is not None
    assert event.retained_text == "今天天气不错"


def test_barge_in_discards_pending_audio():
    machine = SessionStateMachine()
    machine.on_playback_started(0)
    machine.on_playback_queued(4096)

    event = machine.on_user_speech_start(100)

    assert event is not None
    assert event.discarded_audio_bytes == 4096


def test_barge_in_latency_within_limit_has_no_warning():
    machine = SessionStateMachine()
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(DEFAULT_INTERRUPT_LATENCY_MS)

    assert event is not None
    assert event.notes == []


def test_barge_in_latency_over_limit_is_reported():
    machine = SessionStateMachine()
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(DEFAULT_INTERRUPT_LATENCY_MS + 1)

    assert event is not None
    assert event.notes


def test_speech_start_when_not_speaking_is_not_barge_in():
    machine = SessionStateMachine()

    event = machine.on_user_speech_start(0)

    assert event is None


def test_timeout_returns_to_idle():
    """卡在等待云端意味着麦克风不再听，必须能超时回到空闲。"""
    machine = SessionStateMachine(state_timeout_ms=1000)
    machine.on_cloud_wait_started(0)

    transition = machine.on_timeout(1500)

    assert transition is not None
    assert transition.current is SessionState.IDLE
    assert machine.state() is SessionState.IDLE


def test_timeout_not_triggered_before_deadline():
    machine = SessionStateMachine(state_timeout_ms=1000)
    machine.on_cloud_wait_started(0)

    assert machine.on_timeout(500) is None
    assert machine.state() is SessionState.WAITING_CLOUD


def test_timeout_on_idle_is_noop():
    machine = SessionStateMachine(state_timeout_ms=1000)

    assert machine.on_timeout(99_999) is None
    assert machine.state() is SessionState.IDLE


def test_last_transition_records_reason():
    machine = SessionStateMachine()

    machine.on_user_speech_start(0)
    transition = machine.last_transition()

    assert transition is not None
    assert transition.previous is SessionState.IDLE
    assert transition.current is SessionState.LISTENING
    assert transition.reason == "user_speech_start"


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        SessionStateMachine(interrupt_latency_ms=0)
    with pytest.raises(ValueError):
        SessionStateMachine(state_timeout_ms=-1)
