"""Hasilkan fontdata.py: glyph ASCII 32..126 dari DejaVu Sans Mono (lisensi bebas, boleh disematkan)."""
import base64, zlib
from PIL import Image, ImageDraw, ImageFont
SIZE = 23
def build(path):
    f = ImageFont.truetype(path, SIZE)
    W = round(f.getlength("M")); asc, desc = f.getmetrics(); H = asc + desc
    out = bytearray()
    for code in range(32, 127):
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((0, 0), chr(code), font=f, fill=255)
        out += bytes(v >> 4 for v in im.tobytes())       # 16 tingkat keabuan (0..15)
    return W, H, base64.b64encode(zlib.compress(bytes(out), 9)).decode()
D = "/usr/share/fonts/truetype/dejavu/"
W, H, reg = build(D + "DejaVuSansMono.ttf")
W2, H2, bold = build(D + "DejaVuSansMono-Bold.ttf")
assert (W, H) == (W2, H2), ((W, H), (W2, H2))
def wrap(s, n=96): return "\n".join('    "%s"' % s[i:i + n] for i in range(0, len(s), n))
open("fontdata.py", "w").write('''"""Font bitmap untuk gambar laporan (dihasilkan otomatis oleh gen_font.py).

Glyph ASCII 32..126 dirender dari DejaVu Sans Mono (Bitstream Vera/DejaVu license:
bebas disalin, diubah, dan didistribusikan, termasuk karya turunan seperti bitmap ini).
Format: 95 glyph berurutan, tiap glyph W x H piksel, 1 byte per piksel bernilai 0..15
(tingkat keabuan), dikompres zlib lalu base64.
"""
W, H = %d, %d

REGULAR = (
%s
)

BOLD = (
%s
)
''' % (W, H, wrap(reg), wrap(bold)))
print("W,H =", W, H, "| reguler b64:", len(reg), "| tebal b64:", len(bold))
