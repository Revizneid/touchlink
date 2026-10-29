from desktop.multi_viewer import (
    MacroPolicy,
    MultiViewerSession,
    default_macro_policy,
    evaluate_macro,
    resolve_controller,
)


def test_controller_selection_and_viewer_limits():
    session = MultiViewerSession(max_viewers=4)
    session.register_viewer("v1", role="viewer")
    session.register_viewer("v2", role="viewer")
    session.register_viewer("v3", role="viewer")
    session.register_viewer("v4", role="viewer")
    assert session.can_register("v5") is False
    assert resolve_controller(session.viewers) == "v1"
    session.set_controller("v2")
    assert session.controller == "v2"


def test_macro_policy_rejects_unsafe_or_too_long_actions():
    policy = default_macro_policy()
    assert evaluate_macro(policy, "ctrl+alt+delete") == False
    assert evaluate_macro(policy, "type:hello") == True
    assert evaluate_macro(policy, "type:" + ("x" * 5000)) == False
    assert evaluate_macro(policy, "open:calc") == False


def test_multi_viewer_explicitly_blocks_non_controller_input():
    session = MultiViewerSession(max_viewers=4, controller="v1")
    session.register_viewer("v1", role="controller")
    session.register_viewer("v2", role="viewer")
    session.register_viewer("v3", role="viewer")
    assert session.can_send_input("v1") is True
    assert session.can_send_input("v2") is False
