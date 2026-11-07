import asyncio
import json
import os
import sys

# Thêm desktop/ vào sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "desktop"))

import pytest

from desktop import core
from desktop.security.audit import AuditLogger


class DummyConn:
    def __init__(self, name="TestViewer", view_only=False):
        self.name = name
        self.view_only = view_only
        self.alive = True
        self.caps = []
        self.sent_json = []
        self.sent_bytes = []
        self._need_keyframe = False
        self.tile_engine = core.TileEngine(core.TILE_SIZE_DEFAULT)

    @property
    def supports_tiles(self):
        return "tiles" in self.caps

    def request_keyframe(self):
        self._need_keyframe = True

    def start_sender(self):
        pass

    def offer_frame(self, data):
        pass

    async def send_json(self, data):
        self.sent_json.append(data)

    async def send_bytes(self, data):
        self.sent_bytes.append(data)

    async def close(self):
        self.alive = False


@pytest.mark.asyncio
async def test_view_only_blocks_input_and_settings_and_clipboard():
    conn = DummyConn(name="ViewOnlyClient", view_only=True)

    # 1. Test input is blocked
    await core.handle_client_message(conn, {"type": "input", "kind": "mouse", "action": "click"})
    assert len(conn.sent_json) == 1
    err = conn.sent_json[0]
    assert err["type"] == "error"
    assert err["code"] == "view_only"

    # 2. Test settings is blocked
    conn.sent_json.clear()
    await core.handle_client_message(conn, {"type": "settings", "settings": {"scale": 50}})
    assert len(conn.sent_json) == 1
    assert conn.sent_json[0]["code"] == "view_only"

    # 3. Test clipboard_set is blocked
    conn.sent_json.clear()
    await core.handle_client_message(conn, {"type": "clipboard_set", "text": "evil"})
    assert len(conn.sent_json) == 1
    assert conn.sent_json[0]["code"] == "view_only"

    # 4. Non-control messages (ping, chat) should not be blocked by view_only
    conn.sent_json.clear()
    await core.handle_client_message(conn, {"type": "ping", "t": 12345})
    assert len(conn.sent_json) == 1
    assert conn.sent_json[0]["type"] == "pong"


@pytest.mark.asyncio
async def test_audit_logger_records_session_and_auth_events(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit.jsonl"
    test_logger = AuditLogger(path=str(audit_file))
    monkeypatch.setattr(core, "_audit", test_logger)

    conn = DummyConn(name="AuditedClient", view_only=False)

    # Add client -> session_start
    await core.add_client(conn)
    # Remove client -> session_end
    await core.remove_client(conn, reason="client disconnected")

    assert audit_file.exists()
    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().splitlines()]
    events = [entry["event"] for entry in lines]
    assert "session_start" in events
    assert "session_end" in events


@pytest.mark.asyncio
async def test_relay_client_auth_audit_recording(tmp_path, monkeypatch):
    import relay_client
    audit_file = tmp_path / "audit_relay.jsonl"
    test_logger = AuditLogger(path=str(audit_file))
    monkeypatch.setattr(relay_client, "_audit", test_logger)

    class DummyWS:
        def __init__(self):
            self.closed = False
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    client = relay_client.RelayClient()
    client.ws = DummyWS()

    # Wrong password -> records auth_fail
    import secure
    monkeypatch.setattr(secure, "verify_password", lambda p, enc: False)
    await client._handle_auth({"password_enc": "hash"}, {"password": "bad", "viewer_ip": "1.2.3.4"})

    lines = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").strip().splitlines()]
    assert any(entry["event"] == "auth_fail" and entry["auth_method"] == "relay_password" for entry in lines)


@pytest.mark.asyncio
async def test_file_transfer_view_only_blocked_and_normal_allowed(tmp_path, monkeypatch):
    import base64
    import hashlib

    # 1. Test view_only blocks file_offer
    conn_vo = DummyConn(name="ViewOnlyUser", view_only=True)
    await core.handle_client_message(conn_vo, {
        "type": "file_offer",
        "id": "t-vo-1",
        "name": "doc.pdf",
        "size": 100,
        "sha256": hashlib.sha256(b"hello").hexdigest(),
    })
    assert len(conn_vo.sent_json) == 1
    assert conn_vo.sent_json[0]["code"] == "view_only"

    # 2. Test normal client file transfer end-to-end
    conn = DummyConn(name="NormalUser", view_only=False)
    conn.download_dir = str(tmp_path)
    test_content = b"touchlink file content 123"
    content_hash = hashlib.sha256(test_content).hexdigest()

    # Offer
    await core.handle_client_message(conn, {
        "type": "file_offer",
        "id": "t-norm-1",
        "name": "test_doc.txt",
        "size": len(test_content),
        "sha256": content_hash,
    })
    assert len(conn.sent_json) == 1
    assert conn.sent_json[0]["type"] == "file_accept"

    # Chunk (final)
    conn.sent_json.clear()
    chunk_b64 = base64.b64encode(test_content).decode("ascii")
    await core.handle_client_message(conn, {
        "type": "file_chunk",
        "id": "t-norm-1",
        "seq": 0,
        "data": chunk_b64,
        "final": True,
    })
    types_sent = [msg["type"] for msg in conn.sent_json]
    assert "file_ack" in types_sent
    assert "file_done" in types_sent


@pytest.mark.asyncio
async def test_non_controller_and_prohibited_keys_blocked(monkeypatch):
    # 1. Non-controller role cannot issue input
    sub_viewer = DummyConn(name="SecondaryViewer", view_only=False)
    sub_viewer.role = "viewer"
    tapped = []
    monkeypatch.setattr(core.inp, "tap_key", lambda k, m: tapped.append((k, m)))
    monkeypatch.setattr(core.inp, "mouse", lambda *args, **kwargs: tapped.append(args))

    await core.handle_client_message(sub_viewer, {"type": "input", "kind": "key", "key": "a"})
    assert len(tapped) == 0

    # 2. Controller with prohibited key (e.g. win+l or ctrl+alt+delete)
    controller = DummyConn(name="ControllerViewer", view_only=False)
    controller.role = "controller"
    await core.handle_client_message(controller, {"type": "input", "kind": "key", "key": "l", "mods": ["win"]})
    assert len(tapped) == 0

    # 3. Allowed key succeeds
    await core.handle_client_message(controller, {"type": "input", "kind": "key", "key": "enter", "mods": []})
    assert len(tapped) == 1
    assert tapped[0] == ("enter", [])



