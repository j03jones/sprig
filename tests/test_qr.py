"""The phone app's QR codes (web/js/qr.js) must scan back to the exact text.

Uses OpenCV's ZXing-based WeChat reader (the same family of decoder phone cameras use). OpenCV's basic
QRCodeDetector is not used: it misses some valid codes.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None


@unittest.skipUnless(cv2 is not None and hasattr(cv2, "wechat_qrcode_WeChatQRCode") and shutil.which("node"),
                     "needs OpenCV (with contrib) and node")
class QrScans(unittest.TestCase):
    TEXTS = [
        "A",
        "https://recipes.jonesridgekitchen.com/#/join/ABCD2345",
        "https://recipes.jonesridgekitchen.com/#/join/ABCD2345?n=" + "x" * 60,
        "Café crème brûlée ½ cup 👩‍🍳",
        "https://example.com/" + "long-path/" * 18,          # version 7+ (version info blocks)
        "https://example.com/" + "y" * 400,                   # version 10+ (16-bit length)
    ] + ["https://example.com/" + "z" * k for k in range(0, 900, 37)]   # many sizes, versions 2 to 25

    def test_every_code_scans_back(self):
        out = subprocess.run(["node", str(ROOT / "tools" / "qr_js.mjs")], input=json.dumps(self.TEXTS),
                             capture_output=True, text=True, check=True)
        detector = cv2.wechat_qrcode_WeChatQRCode()
        for text, rows in zip(self.TEXTS, json.loads(out.stdout)):
            n = len(rows)
            m = np.array([[0 if c == "1" else 255 for c in r] for r in rows], dtype=np.uint8)
            img = np.full((n + 8, n + 8), 255, dtype=np.uint8)
            img[4:4 + n, 4:4 + n] = m
            img = cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
            found, _ = detector.detectAndDecode(img)
            got = found[0] if found else ""
            self.assertEqual(got, text, f"version {(n - 17) // 4} did not scan back")


if __name__ == "__main__":
    unittest.main()
