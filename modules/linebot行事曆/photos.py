"""行事曆的圖片：收進來（HEIC 轉 JPG）、畫面用的縮圖、公開版縮小並拿掉中繼資料（D91 的一部分）。

sips（macOS 內建）一律用清單參數、不經過 shell；測試把 run 換成假的。拿掉中繼資料是純 Python、用白名單：
JPEG 只留 JFIF、ICC 色彩描述、Adobe 色彩轉換與影像本身的段落，到影像結尾（EOI）為止——APP1（EXIF、XMP）、APP13（IPTC）、
APP6 這類相機自己的資料、註解、EOI 之後藏的第二張圖都不留；PNG 只留影像與色彩的區塊，到 IEND 為止；GIF 照原樣。
不 import core、不 import diary。"""

import base64
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 30 * 1024 * 1024
THUMB_SOURCE_MAX = 5 * 1024 * 1024  # 沒有 sips 時，原圖這麼小以內就直接當縮圖
SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif")
PUBLISHABLE = (".jpg", ".jpeg", ".png", ".gif")
HEIC = (".heic", ".heif")
THUMBS = ".縮圖"
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
TOO_BIG = "{name}：太大（超過 30 MB）"
NOT_IMAGE = "{name}：不是圖片"
NO_JPEG = "{name}：轉不成 JPG，Chrome 看不到"
JPEG_TABLES = {0xC4, 0xCC, 0xDB, 0xDD} | ({*range(0xC0, 0xD0)} - {0xC8})  # DHT、DAC、DQT、DRI、SOFn
JPEG_APPS = {0xE0: (b"JFIF\x00", b"JFXX\x00"), 0xE2: (b"ICC_PROFILE\x00",), 0xEE: (b"Adobe",)}
PNG_KEEP = (b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"cICP")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def clean_name(name: str) -> str:
    """只取 basename，拿掉 :、控制字元、開頭的點；空了就是「圖片」。其餘一個字都不改。"""
    base = re.split(r"[/\\]", str(name))[-1]
    base = "".join(c for c in base if c != ":" and c.isprintable())
    return base.lstrip(".") or "圖片"


def _taken(folder: Path, name: str) -> bool:
    """同名（不分大小寫）就算有了；同 stem 的 HEIC 與 JPG 算同一個名字（HEIC 轉出來的 JPG 會用那個 stem）。"""
    try:
        names = [p.name.lower() for p in folder.iterdir()]
    except OSError:
        return False
    stem, suffix = Path(name).stem.lower(), Path(name).suffix.lower()
    if name.lower() in names:
        return True
    linked = HEIC + (".jpg",)
    return suffix in linked and any(Path(n).stem == stem and Path(n).suffix in linked for n in names)


def unique_name(folder: Path, name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 1
    while _taken(folder, candidate):
        n += 1
        candidate = f"{stem} {n}{suffix}"
    return candidate


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _sips(argv: list[str], out: Path, run) -> bool:
    try:
        done = run(argv, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and out.exists()


def to_jpeg(path: Path, run=subprocess.run) -> Path | None:
    out = path.with_suffix(".jpg")
    return out if _sips(["sips", "-s", "format", "jpeg", str(path), "--out", str(out)], out, run) else None


def add_image(folder: Path, name: str, data: bytes, *, run=subprocess.run,
              platform: str = sys.platform) -> tuple[str | None, str | None]:
    """收一張圖：回 (存成的檔名, 問題那一句或 None)。"""
    name = clean_name(name)
    if len(data) > MAX_BYTES:
        return None, TOO_BIG.format(name=name)
    if Path(name).suffix.lower() not in SUFFIXES:
        return None, NOT_IMAGE.format(name=name)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = unique_name(folder, name)
    _write(folder / name, data)
    heic = Path(name).suffix.lower() in HEIC
    if heic and (platform != "darwin" or to_jpeg(folder / name, run) is None):
        return name, NO_JPEG.format(name=name)
    return name, None


def shrink(src: Path, dst: Path, run=subprocess.run) -> bool:
    return _sips(["sips", "-Z", "1600", str(src), "--out", str(dst)], dst, run)


def _keep_jpeg(marker: int, body: bytes) -> bool:
    if marker in JPEG_TABLES or marker == 0xDA:
        return True
    return any(body.startswith(head) for head in JPEG_APPS.get(marker, ()))


def _scan_end(data: bytes, i: int) -> int:
    """SOS 之後的影像資料到哪裡：遇到不是位元填充（FF 00）、不是 RSTn、不是補位 FF 的標記就停。"""
    while i < len(data) - 1:
        if data[i] == 0xFF and data[i + 1] not in (0x00, 0xFF) and not 0xD0 <= data[i + 1] <= 0xD7:
            return i
        i += 1
    return len(data)


def _strip_jpeg(data: bytes) -> bytes:
    out, i = bytearray(data[:2]), 2
    while i + 1 < len(data):
        if data[i] != 0xFF:
            raise ValueError("JPEG 的段落壞了")
        marker = data[i + 1]
        if marker == 0xFF:  # 段落之間的補位
            i += 1
            continue
        if marker == 0xD9:  # 影像結尾：之後的東西（第二張圖、附加的資料）一律不要
            return bytes(out + b"\xff\xd9")
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        if i + 4 > len(data):
            break
        end = i + 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        if _keep_jpeg(marker, data[i + 4:end]):
            out += data[i:end]
        i = end
        if marker == 0xDA:
            j = _scan_end(data, i)
            out += data[i:j]
            i = j
    if b"\xff\xda" not in out:
        raise ValueError("JPEG 沒有影像資料")
    return bytes(out)  # 沒有結尾標記（檔案被截斷）：影像資料照樣留著


def _strip_png(data: bytes) -> bytes:
    out, i = bytearray(PNG_SIGNATURE), len(PNG_SIGNATURE)
    while i + 8 <= len(data):
        length, kind = struct.unpack(">I", data[i:i + 4])[0], data[i + 4:i + 8]
        end = i + 12 + length
        if kind in PNG_KEEP:
            out += data[i:end]
        if kind == b"IEND":
            return bytes(out)
        i = end
    raise ValueError("PNG 沒有結尾")


def strip_metadata(src: Path, dst: Path) -> None:
    """拿掉拍攝地點等中繼資料，寫到 dst（先寫暫存再換）；不是 JPEG、PNG、GIF 丟 ValueError。"""
    data = Path(src).read_bytes()
    if data[:2] == b"\xff\xd8":
        out = _strip_jpeg(data)
    elif data[:8] == PNG_SIGNATURE:
        out = _strip_png(data)
    elif data[:4] == b"GIF8":
        out = data
    else:
        raise ValueError("不是 JPEG、PNG、GIF")
    _write(Path(dst), out)


def public_copy(src: Path, dst: Path, *, run=subprocess.run, platform: str = sys.platform) -> None:
    """公開版的一張圖：macOS 上 JPEG／PNG 先縮到長邊 1600，再拿掉中繼資料；GIF 與其他系統只拿掉中繼資料。
    縮小的那一張還帶著中繼資料，所以放在系統的暫存資料夾、不放在 發佈/ 裡：中途被中斷，發佈/ 裡也只會有拿掉過的檔。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = Path(src)
    with tempfile.TemporaryDirectory(prefix="iplot-行事曆-") as work:
        small = Path(work) / f"small{dst.suffix}"
        if platform == "darwin" and source.suffix.lower() in (".jpg", ".jpeg", ".png") and shrink(source, small, run):
            source = small
        strip_metadata(source, dst)


def thumbnail(src: Path, dst: Path, run=subprocess.run) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    return _sips(["sips", "-s", "format", "jpeg", "-Z", "320", str(src), "--out", str(dst)], dst, run)


def thumbnail_url(folder: Path, name: str, *, run=subprocess.run, platform: str = sys.platform) -> str | None:
    """畫面用的縮圖，以 data URL 給頁面（app.page 的頁面顯示不了 file:// 的圖，Task 0 Step 4）。
    macOS：sips -Z 320 做到 .縮圖/<檔名>.jpg，原圖比較新才重做；其他系統：小的 JPEG／PNG／GIF 原圖直接用，否則 None。"""
    src = Path(folder) / name
    if platform == "darwin":
        thumb = Path(folder) / THUMBS / f"{name}.jpg"
        try:
            fresh = thumb.exists() and thumb.stat().st_mtime >= src.stat().st_mtime
        except OSError:
            return None
        if not fresh and not thumbnail(src, thumb, run):
            return None
        return "data:image/jpeg;base64," + base64.b64encode(thumb.read_bytes()).decode("ascii")
    mime = MIME.get(src.suffix.lower())
    try:
        if mime is None or src.stat().st_size > THUMB_SOURCE_MAX:
            return None
        return f"data:{mime};base64," + base64.b64encode(src.read_bytes()).decode("ascii")
    except OSError:
        return None
