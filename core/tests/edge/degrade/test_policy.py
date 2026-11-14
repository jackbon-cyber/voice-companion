from core.edge.degrade.policy import DEGRADE_ORDER, DegradeLevel, DegradePolicy


def test_consecutive_failures_degrade_to_network_level():
    policy = DegradePolicy(failure_threshold=3)
    assert policy.record_uplink_failure() == DegradeLevel.NORMAL
    assert policy.record_uplink_failure() == DegradeLevel.NORMAL
    assert policy.record_uplink_failure() == DegradeLevel.DEGRADED_NETWORK


def test_model_failure_jumps_to_minimal_level():
    policy = DegradePolicy()
    assert policy.record_model_failure() == DegradeLevel.MINIMAL


def test_recovery_ascends_one_level_at_a_time():
    policy = DegradePolicy(failure_threshold=1, recovery_success_threshold=1)
    policy.record_uplink_failure()
    assert policy.current() == DegradeLevel.DEGRADED_NETWORK
    assert policy.record_uplink_success() == DegradeLevel.NORMAL


def test_recovery_never_jumps_from_offline_to_normal():
    policy = DegradePolicy(failure_threshold=1, recovery_success_threshold=1)
    policy.record_uplink_failure()
    policy.record_uplink_failure()
    assert policy.current() == DegradeLevel.OFFLINE
    assert policy.record_uplink_success() == DegradeLevel.DEGRADED_NETWORK
    assert policy.record_uplink_success() == DegradeLevel.NORMAL


def test_intermittent_failures_do_not_oscillate():
    policy = DegradePolicy(failure_threshold=3, recovery_success_threshold=3)
    for _ in range(10):
        policy.record_uplink_success()
        policy.record_uplink_failure()
    assert policy.current() == DegradeLevel.NORMAL


def test_degrade_order_is_monotonic():
    assert DEGRADE_ORDER == (
        DegradeLevel.NORMAL,
        DegradeLevel.DEGRADED_NETWORK,
        DegradeLevel.OFFLINE,
        DegradeLevel.MINIMAL,
    )


def test_connection_failure_drops_to_offline_immediately():
    """连接被拒是对端明确不可达的证据，不该等三次失败才降级。"""
    policy = DegradePolicy(failure_threshold=3)
    assert policy.record_connection_failure() == DegradeLevel.OFFLINE


def test_connection_failure_resets_counters():
    """连接失败后计数器必须清零，否则恢复时会带着脏计数。"""
    policy = DegradePolicy(failure_threshold=3, recovery_success_threshold=3)
    policy.record_uplink_failure()
    policy.record_connection_failure()
    assert policy.record_uplink_success() == DegradeLevel.OFFLINE
    assert policy.record_uplink_success() == DegradeLevel.OFFLINE
    assert policy.record_uplink_success() == DegradeLevel.DEGRADED_NETWORK
