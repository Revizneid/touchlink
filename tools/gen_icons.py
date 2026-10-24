"""Sinh icon PNG cho PWA TouchLink (192 & 512)."""
import os

from PIL import Image, ImageDraw

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "icons")
os.makedirs(HERE, exist_ok=True)


def make(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # nền gradient xanh
    top = (37, 99, 235)
    bottom = (11, 18, 32)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,))
    r = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=None)
    # màn hình máy tính
    mw, mh = int(size * 0.62), int(size * 0.42)
    mx, my = int(size * 0.10), int(size * 0.22)
    d.rounded_rectangle([mx, my, mx + mw, my + mh], radius=size // 28, fill=(231, 237, 247, 255))
    d.rounded_rectangle([mx + int(mw*0.06), my + int(mh*0.08), mx + mw - int(mw*0.06), my + mh - int(mh*0.10)],
                        radius=size // 40, fill=(37, 99, 235, 255))
    # chân đế
    d.rectangle([mx + mw // 2 - size // 34, my + mh, mx + mw // 2 + size // 34, my + mh + size // 14],
                fill=(231, 237, 247, 255))
    d.rounded_rectangle([mx + mw // 2 - size // 9, my + mh + size // 14, mx + mw // 2 + size // 9,
                         my + mh + size // 10], radius=size // 60, fill=(231, 237, 247, 255))
    # điện thoại
    pw, ph = int(size * 0.26), int(size * 0.46)
    px, py = int(size * 0.58), int(size * 0.36)
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=size // 22, fill=(231, 237, 247, 255))
    d.rounded_rectangle([px + pw * 0.09, py + ph * 0.09, px + pw * 0.91, py + ph * 0.88],
                        radius=size // 34, fill=(139, 92, 246, 255))
    d.ellipse([px + pw * 0.42, py + ph * 0.905, px + pw * 0.58, py + ph * 0.96], fill=(11, 18, 32, 255))
    # mũi tên nối
    ay = int(size * 0.16)
    ax0, ax1 = mx + mw - int(size*0.02), px
    d.line([(ax0 + 2, ay), (ax1 - 2, ay)], fill=(255, 255, 255, 230), width=max(2, size // 60))
    d.polygon([(ax1, ay), (ax1 - size // 26, ay - size // 52), (ax1 - size // 26, ay + size // 52)],
              fill=(255, 255, 255, 230))
    img.save(os.path.join(HERE, "icon-%d.png" % size))


make(512)
make(192)
print("Đã tạo icons:", os.listdir(HERE))
