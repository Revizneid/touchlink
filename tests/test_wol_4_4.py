from desktop.wol import (
    build_magic_packet,
    is_valid_mac_address,
    validate_wake_request,
)


def test_magic_packet_and_wake_request_validation():
    packet = build_magic_packet("00:11:22:33:44:55")
    assert len(packet) == 6 + 16 * 6
    assert packet[:6] == b"\xff\xff\xff\xff\xff\xff"
    assert is_valid_mac_address("00:11:22:33:44:55") is True
    assert is_valid_mac_address("99:99:99:99:99") is False

    assert validate_wake_request({"target_mac": "00:11:22:33:44:55", "device_id": "123456789", "permission": "wake"}) is True
    assert validate_wake_request({"target_mac": "00:11:22:33:44:55", "device_id": "123456789", "permission": "guest"}) is False
    assert validate_wake_request({"target_mac": "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ", "device_id": "123456789", "permission": "wake"}) is False
