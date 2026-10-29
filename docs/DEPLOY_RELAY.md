# docs/DEPLOY_RELAY.md — Hướng dẫn triển khai TouchLink Relay

## So sánh tùy chọn hosting

| Tùy chọn | Chi phí | Relay có ngủ không? | Ghi chú |
|---|---|---|---|
| **VPS riêng** | ~$4–6/tháng | **Không** — chạy 24/7 | Hoàn toàn kiểm soát; khuyến nghị |
| **Fly.io** | ~$0–2/tháng | **Không** (cấu hình đúng) | Free tier 3 máy; `auto_stop=false` |
| **Oracle Cloud Free Tier** | **Miễn phí vĩnh viễn** | **Không** | VM ARM 4 core / 24GB; phải dùng Ubuntu |
| **Render** | $0 (free) / $7+ (paid) | ⚠ **Có** — ngủ sau 15 phút không dùng | Chỉ dùng khi chấp nhận độ trễ đánh thức |

> **Khuyến nghị:** VPS $4–6/tháng (DigitalOcean, Hetzner, Vultr) hoặc Oracle Free Tier cho relay
> luôn chạy. Fly.io phù hợp nếu muốn zero-ops.

---

## 1. VPS riêng với systemd + Caddy TLS

### 1.1 Chuẩn bị VPS

```bash
# Ubuntu 22.04+
sudo apt update && sudo apt install -y python3 python3-pip git

# Clone repo hoặc copy relay_server.py
git clone https://github.com/<bạn>/touchlink.git /opt/touchlink
pip3 install aiohttp
```

### 1.2 Systemd service

Tạo file `/etc/systemd/system/touchlink-relay.service`:

```ini
[Unit]
Description=TouchLink Relay Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/touchlink/relay
ExecStart=/usr/bin/python3 -u relay_server.py \
    --port 8430 \
    --trusted-proxy \
    --anonymize-logs
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=touchlink-relay

# Biến môi trường — hoặc đặt trong /etc/touchlink-relay.env
Environment=RELAY_MAX_CONNS_IP=20
Environment=RELAY_MAX_CONN_ID=10
Environment=RELAY_AUTH_BAN_S=180
# Environment=RELAY_METRICS_TOKEN=your-secret-token

# Bảo mật
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/opt/touchlink/relay

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now touchlink-relay
sudo systemctl status touchlink-relay
# Xem log:
sudo journalctl -fu touchlink-relay
```

### 1.3 Caddy TLS (tự động Let's Encrypt)

Cài Caddy: https://caddyserver.com/docs/install

`/etc/caddy/Caddyfile`:

```caddy
touchlink.example.com {
    reverse_proxy 127.0.0.1:8430

    # Header để relay nhận IP thật (--trusted-proxy đã bật)
    header_up X-Forwarded-For {remote_host}

    # Bảo mật
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options "nosniff"
        -Server
    }

    # Giữ kết nối WebSocket mở lâu
    @ws {
        header Connection *Upgrade*
        header Upgrade websocket
    }
    handle @ws {
        reverse_proxy 127.0.0.1:8430 {
            transport http {
                read_timeout 0
                write_timeout 0
            }
        }
    }

    log {
        output file /var/log/caddy/touchlink.log
        format json
    }
}
```

```bash
sudo systemctl reload caddy
```

**Kết quả:** relay chạy tại `wss://touchlink.example.com/ws`

### 1.4 Mở firewall

```bash
# Ubuntu UFW
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# KHÔNG mở 8430 ra ngoài (Caddy xử lý TLS)
```

---

## 2. Fly.io (zero-ops, không ngủ)

### 2.1 Cài Fly CLI

```bash
curl -L https://fly.io/install.sh | sh
fly auth signup  # hoặc fly auth login
```

### 2.2 Chuẩn bị

```bash
# Từ thư mục gốc repo:
cp relay/relay_server.py deploy/relay_server.py
```

### 2.3 Triển khai

```bash
fly launch --no-deploy --config deploy/fly.toml
fly secrets set RELAY_METRICS_TOKEN="$(openssl rand -hex 32)"
fly deploy --config deploy/fly.toml
```

### 2.4 Xác nhận không ngủ

File `deploy/fly.toml` đã đặt:
```toml
auto_stop_machines = false
min_machines_running = 1
```

> **Quan trọng:** Fly.io free tier cho phép 3 shared machines. Với 1 machine `shared-cpu-1x`
> relay không bao giờ bị dừng.

### 2.5 Kiểm tra

```bash
fly status --config deploy/fly.toml
curl https://<app-name>.fly.dev/healthz
```

---

## 3. Oracle Cloud Free Tier (miễn phí vĩnh viễn)

### 3.1 Tạo VM

1. Đăng ký tại https://cloud.oracle.com/
2. Tạo **Compute Instance**: `VM.Standard.A1.Flex` (ARM) — **4 core / 24GB RAM** — miễn phí
3. OS: Ubuntu 22.04 Minimal (ARM)
4. Thêm SSH key

### 3.2 Cài đặt

```bash
# SSH vào VM
sudo apt update && sudo apt install -y python3-pip caddy git
pip3 install aiohttp

git clone https://github.com/<bạn>/touchlink.git /opt/touchlink
```

Tạo systemd service (giống mục 1.2), bật Caddy TLS (mục 1.3).

### 3.3 Firewall Oracle

Oracle dùng VCN Security List (không phải ufw mặc định):
- Thêm Ingress Rule: TCP port 80 và 443 từ 0.0.0.0/0

```bash
# Bật ufw bổ sung:
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
# Tắt iptables chặn từ Oracle:
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
```

---

## 4. Render (free tier — CÓ ngủ)

> ⚠ **Cảnh báo:** Render free tier ngủ sau 15 phút không có request HTTP.
> Kết nối WebSocket đầu tiên sau khi ngủ phải chờ 30–60 giây đánh thức.
> PWA đã tích hợp UX đánh thức (đếm giây + retry backoff) để xử lý trường hợp này.

### Cấu hình

File `render.yaml` (đã có trong repo):

```yaml
services:
  - type: web
    name: touchlink-relay
    runtime: python
    buildCommand: pip install aiohttp
    startCommand: python relay/relay_server.py --trusted-proxy
    envVars:
      - key: RELAY_TRUSTED_PROXY
        value: "1"
      - key: RELAY_METRICS_TOKEN
        generateValue: true
```

**Deploy:** kết nối GitHub repo tới Render, chọn `render.yaml`.

### Cấu hình trong app máy tính

```
Relay URL: wss://touchlink-relay.onrender.com/ws
```

---

## 5. Kiểm tra sau triển khai

```bash
# Healthcheck (không cần auth)
curl https://your-relay.example.com/healthz
# → {"status":"ok","app":"touchlink-relay"}

# Metrics (cần token nếu cấu hình)
curl -H "Authorization: Bearer <token>" https://your-relay.example.com/metrics

# WebSocket test (cần wscat: npm install -g wscat)
wscat -c wss://your-relay.example.com/ws
> {"type":"ping","t":1}
< {"type":"pong","t":1}
```

---

## 6. Cấu hình trong app TouchLink

Sau khi relay chạy, cập nhật trong app máy tính:

```
Relay URL: wss://touchlink.example.com/ws
Bật relay: ✓
Áp dụng relay
```

Hoặc qua CLI:
```bash
python desktop/main.py --relay --relay-url wss://touchlink.example.com/ws
```

---

## 7. Lưu ý bảo mật

- **Luôn dùng TLS (wss://)** — relay thấy password trong transit.
- **Đặt RELAY_METRICS_TOKEN** để bảo vệ endpoint `/metrics`.
- **Tự vận hành relay** nếu có thông tin nhạy cảm — không dùng relay công cộng.
- E2E encryption dự kiến ở Giai đoạn 2–3.
