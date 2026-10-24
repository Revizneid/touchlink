"""Giới hạn thử mật khẩu sai (brute-force protection)."""
import collections
import threading
import time


class RateLimiter:
    def __init__(self, max_fails=5, window=300, ban=180):
        self.max_fails = max_fails
        self.window = window
        self.ban = ban
        self.fails = collections.defaultdict(collections.deque)
        self.banned_until = {}
        self.lock = threading.Lock()

    def is_banned(self, key: str) -> bool:
        with self.lock:
            return time.time() < self.banned_until.get(key, 0)

    def ban_remaining(self, key: str) -> int:
        with self.lock:
            return max(0, int(self.banned_until.get(key, 0) - time.time()))

    def fail(self, key: str):
        with self.lock:
            dq = self.fails[key]
            now = time.time()
            dq.append(now)
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.max_fails:
                self.banned_until[key] = now + self.ban
                dq.clear()

    def reset(self, key: str):
        with self.lock:
            self.fails.pop(key, None)
            self.banned_until.pop(key, None)
