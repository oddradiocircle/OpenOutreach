from linkedin.actions.message import _message_type_timeout_ms


def test_message_type_timeout_keeps_default_for_short_messages():
    assert _message_type_timeout_ms("Hello") == 30_000


def test_message_type_timeout_scales_for_long_messages():
    assert _message_type_timeout_ms("x" * 533) == 53_300
