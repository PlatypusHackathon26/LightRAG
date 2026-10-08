"""Build scanned-looking test uploads (image-only PDF, phone photo, Japanese scan) from real document facts.

Text is drawn, then tilted, blurred and speckled like a scan, so no text layer exists and only OCR
can read it. Facts: SCV guide p.3-4, AC Compressor Leaflet p.2.

Usage:
    python denso/scripts/make_scan_samples.py denso/data/samples
"""

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path("C:/Windows/Fonts")
Image.init()  # registers the JPEG writer the PDF and photo need
random.seed(7)


def page(lines: list[str], font_file: str, size: int = 34, width: int = 1654, height: int = 2339) -> Image.Image:
    """An A4 page at 200 dpi with the lines drawn; a line starting with '|' is a table row."""
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONTS / font_file), size)
    y = 140
    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            col = (width - 240) // len(cells)
            for i, cell in enumerate(cells):
                x = 120 + i * col
                d.rectangle([x, y - 8, x + col, y + size + 16], outline=0, width=2)
                d.text((x + 12, y), cell, font=font, fill=0)
            y += size + 24
        else:
            d.text((120, y), line, font=font, fill=0)
            y += int(size * 1.7)
    return img


def scanned(img: Image.Image, angle: float, blur: float, specks: int) -> Image.Image:
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    px = img.load()
    for _ in range(specks):
        x, y = random.randrange(img.width), random.randrange(img.height)
        px[x, y] = random.randint(0, 120)
    return img


VI_PAGES = [
    ["PHIẾU BẢO TRÌ – THAY VAN SCV BƠM COMMON RAIL", "",
     "Bộ kit: DCRS300260 (294009-2150)", "Xưởng: Dây chuyền B – Máy nén khí số 3", "",
     "Tháo van SCV cũ:",
     "1. Đánh dấu vị trí giắc nối của SCV so với bơm.",
     "2. Nới lỏng và tháo các bu-lông.",
     "3. Tháo gioăng O-ring lớn (vị trí 1).", "",
     "Lắp van SCV mới:",
     "4. Lắp 1 gioăng O-ring mới.",
     "5. Lắp 2 chốt dẫn hướng vào lỗ bắt bu-lông, lắp gioăng mới.",
     "6. Bôi dầu động cơ lên O-ring nhỏ, đẩy SCV vào thân bơm.",
     "7. Rút chốt dẫn hướng, siết bu-lông 6,9 – 10,8 Nm."],
    ["THÔNG SỐ KIỂM TRA SAU LẮP", "",
     "| Hạng mục | Giá trị |",
     "| Mô-men xoắn bu-lông SCV | 6,9 – 10,8 Nm |",
     "| Số chốt dẫn hướng | 2 |",
     "| Máy chẩn đoán | DENSO DST-PC |", "",
     "Lưu ý: không dùng chốt dẫn hướng có thể gây rò rỉ nhiên liệu.",
     "Sau khi lắp: kiểm tra không có mã lỗi DTC."],
]
EN_TABLE = ["DENSO recommends the following compressor oils:", "",
            "| Compressor Type | Refrigerant | Oil Type |",
            "| #PA, #S, #SB, #SE, SC, 6CA | HFC134a (R-134a) | DENSO Oil 8 |",
            "| #PA, #S, #SB, #SE, SC, 6CA | HFO 1234yf | DENSO Oil 12 |",
            "| Vane-type blower (TV) | HFC134a (R-134a) | DENSO Oil 9 |",
            "| Electrical Type (ES) | HFC134a (R-134a) | DENSO Oil 11 |",
            "| Electrical Type (ES) | HFO 1234yf | DENSO Oil 11 |", "",
            "All warranty is void when using the wrong type of oils or oil mixtures."]
JA_LINES = ["SCV取付手順（ディーゼル コモンレール）", "",
            "1. 新しいOリングを1個取り付ける。",
            "2. ガイドピンを2本取付穴に入れる。",
            "3. SCVを慎重に押し込み、ガイドピンを外す。",
            "4. ボルトを6.9～10.8 Nmで締め付ける。", "",
            "注意：ガイドピンなしで取り付けると燃料漏れの恐れがある。"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    out = ap.parse_args().out
    out.mkdir(parents=True, exist_ok=True)

    pages = [scanned(page(p, "arial.ttf"), angle, 1.0, 4000).convert("RGB") for p, angle in zip(VI_PAGES, (0.8, -0.6))]
    pages[0].save(out / "Phieu_bao_tri_SCV_scan.pdf", save_all=True, append_images=pages[1:], resolution=200)

    photo = scanned(page(EN_TABLE, "arial.ttf", size=30, height=1100), 2.0, 1.4, 2500)
    photo = photo.transform(photo.size, Image.PERSPECTIVE, (1.0, 0.03, -20, 0.0, 1.0, -15, 0.00001, 0.00002),
                            Image.BICUBIC, fillcolor=200).convert("RGB")
    photo.save(out / "AC_oil_table_photo.jpg", quality=80)

    scanned(page(JA_LINES, "YuGothM.ttc", size=36, height=1200), -1.0, 0.8, 2000).save(out / "SCV_ghi_chu_JP_scan.png")
    for f in sorted(out.glob("*scan*")) + [out / "AC_oil_table_photo.jpg"]:
        print(f)


if __name__ == "__main__":
    main()
