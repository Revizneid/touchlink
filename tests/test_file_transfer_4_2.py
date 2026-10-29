import hashlib

from desktop.file_transfer import (
    FileTransferSession,
    build_file_offer,
    is_valid_destination,
    sanitize_file_name,
    validate_file_offer,
)


def test_file_offer_and_sanitize_file_name_are_safe():
    safe = sanitize_file_name("..\\../report.txt")
    assert safe == "report.txt"
    assert validate_file_offer(
        {
            "id": "file-123",
            "name": "report.txt",
            "size": 128,
            "sha256": hashlib.sha256(b"abc").hexdigest(),
        }
    ) is True
    assert validate_file_offer({"id": "file-123", "name": "payload.exe", "size": 128, "sha256": "00"}) is False


def test_session_rejects_git_traversal_and_hash_mismatch():
    allowed = ["C:/safe"]
    assert is_valid_destination("C:/safe/folder/report.txt", allowed) is True
    assert is_valid_destination("C:/other/file.txt", allowed) is False

    session = FileTransferSession(
        transfer_id="t-1",
        file_name="report.txt",
        file_size=4,
        expected_sha256=hashlib.sha256(b"abcd").hexdigest(),
        destination_dir="C:/safe",
        allowlist=["C:/safe"],
    )
    assert session.accept() == {"type": "file_accept", "id": "t-1"}
    assert session.receive_chunk(0, b"ab", expect_final=False) is True
    assert session.receive_chunk(1, b"cd", expect_final=True) is True
    assert session.is_complete is True

    bad = FileTransferSession(
        transfer_id="t-2",
        file_name="bad.txt",
        file_size=4,
        expected_sha256=hashlib.sha256(b"zzzz").hexdigest(),
        destination_dir="C:/safe",
        allowlist=["C:/safe"],
    )
    assert bad.receive_chunk(0, b"ab", expect_final=False) is True
    assert bad.receive_chunk(1, b"cd", expect_final=True) is False


def test_resume_window_keeps_chunks_ordered():
    session = FileTransferSession(
        transfer_id="t-3",
        file_name="resume.txt",
        file_size=8,
        expected_sha256=hashlib.sha256(b"abcdefgh").hexdigest(),
        destination_dir="C:/safe",
        allowlist=["C:/safe"],
    )
    assert session.receive_chunk(1, b"efgh", expect_final=False) is True
    assert session.receive_chunk(0, b"abcd", expect_final=False) is True
    assert session.receive_chunk(2, b"gh", expect_final=False) is False
    assert build_file_offer("t-3", "resume.txt", 8, hashlib.sha256(b"abcdefgh").hexdigest())["type"] == "file_offer"
