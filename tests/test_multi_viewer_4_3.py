import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

from desktop.multi_viewer import (
    MacroPolicy,
    MultiViewerSession,
    default_macro_policy,
    evaluate_macro,
    resolve_controller,
)
import desktop.core as core


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
    assert evaluate_macro(policy, "ctrl+alt+delete") is False
    assert evaluate_macro(policy, "type:hello") is True
    assert evaluate_macro(policy, "type:" + ("x" * 5000)) is False
    assert evaluate_macro(policy, "open:calc") is False


def test_multi_viewer_explicitly_blocks_non_controller_input():
    session = MultiViewerSession(max_viewers=4, controller="v1")
    session.register_viewer("v1", role="controller")
    session.register_viewer("v2", role="viewer")
    session.register_viewer("v3", role="viewer")
    assert session.can_send_input("v1") is True
    assert session.can_send_input("v2") is False


def test_multi_viewer_unregister_and_auto_promote():
    session = MultiViewerSession(max_viewers=4)
    session.register_viewer("v1", role="controller")
    session.register_viewer("v2", role="viewer")
    session.register_viewer("v3", role="viewer")

    assert session.controller == "v1"
    assert session.get_role("v1") == "controller"
    assert session.get_role("v2") == "viewer"

    # Unregister controller v1 -> auto-promotes v2
    unreg_ok = session.unregister_viewer("v1")
    assert unreg_ok is True
    assert session.controller == "v2"
    assert session.get_role("v2") == "controller"
    assert session.can_send_input("v2") is True
    assert len(session.list_viewers()) == 2


@pytest.mark.asyncio
async def test_core_multi_viewer_coordination():
    # Reset multi viewer session
    core.multi_viewer_session = MultiViewerSession(max_viewers=4)
    core.clients.clear()

    sent_v1 = []
    sent_v2 = []

    class MockConn:
        def __init__(self, name, sent_list):
            self.name = name
            self.sent = sent_list
            self.alive = True
            self.since = "12:00:00"
            self.role = "viewer"
            self.view_only = False
            self.peer_caps = []

        async def send_json(self, d):
            self.sent.append(d)

        def start_sender(self):
            pass

        async def close(self):
            pass

    c1 = MockConn("Client1", sent_v1)
    c2 = MockConn("Client2", sent_v2)

    await core.add_client(c1)
    assert c1.role == "controller"
    assert core.multi_viewer_session.controller == "Client1"

    await core.add_client(c2)
    assert c2.role == "viewer"
    assert core.multi_viewer_session.can_send_input("Client1") is True
    assert core.multi_viewer_session.can_send_input("Client2") is False

    # Check snapshot format for GUI
    snap = core.clients_snapshot()
    assert len(snap) == 2
    c1_info = next(item for item in snap if item[0] == "Client1")
    c2_info = next(item for item in snap if item[0] == "Client2")
    assert c1_info[2] == "controller" and c1_info[3] is True
    assert c2_info[2] == "viewer" and c2_info[3] is False

    # Client 2 requests controller
    await core.handle_client_message(c2, {"type": "request_controller"})
    assert c2.role == "controller"
    assert c1.role == "viewer"
    assert core.multi_viewer_session.controller == "Client2"

    # Core set_active_controller via GUI
    ok = core.set_active_controller("Client1")
    assert ok is True
    assert c1.role == "controller"
    assert c2.role == "viewer"

    # Remove Client1 -> Client2 promoted
    await core.remove_client(c1)
    assert c2.role == "controller"
    assert core.multi_viewer_session.controller == "Client2"

    await core.remove_client(c2)
    assert len(core.clients) == 0
