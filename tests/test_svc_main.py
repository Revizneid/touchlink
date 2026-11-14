import threading


def test_serve_pipes_starts_one_handler_per_pipe(monkeypatch):
    import desktop.svc_main as svc_main

    stop_evt = threading.Event()
    thread_calls = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            thread_calls.append((target, args, daemon))

        def start(self):
            return None

    monkeypatch.setattr(svc_main.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        svc_main,
        "_get_pipe_security_attributes",
        lambda: None,
    )
    monkeypatch.setattr(
        svc_main.win32pipe,
        "CreateNamedPipe",
        lambda *args, **kwargs: (stop_evt.set(), "pipe-handle")[1],
    )
    monkeypatch.setattr(svc_main.win32pipe, "ConnectNamedPipe", lambda *args, **kwargs: None)

    svc_main.serve_pipes(stop_evt, object(), False)

    assert len(thread_calls) == 1, f"expected one pipe handler thread, got {len(thread_calls)}"
