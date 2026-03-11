import sys
import os
from PIL import Image, ImageDraw, ImageFont, BdfFontFile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")

def load_bdf_font(bdf_path: str):
    pil_path = os.path.splitext(bdf_path)[0] + ".pil"
    if not os.path.exists(pil_path):
        with open(bdf_path, "rb") as fp:
            bdf = BdfFontFile.BdfFontFile(fp)
            bdf.save(pil_path)
    return ImageFont.load(pil_path)

FONT_6X10   = load_bdf_font(os.path.join(FONTS_DIR, "6x10.bdf"))
FONT_5X8    = load_bdf_font(os.path.join(FONTS_DIR, "5x8.bdf"))
FONT_THUMB  = load_bdf_font(os.path.join(FONTS_DIR, "tom-thumb.bdf"))

def mock_design_2(page):
    image = Image.new("RGB", (64, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Left zone: logo
    draw.line([(17, 0), (17, 31)], fill=(40, 40, 40))
    draw.rectangle([1, 8, 16, 23], fill=(200, 200, 200))
    
    TEXT_X = 19
    TEXT_W = 64 - TEXT_X
    
    # 3-line layout:
    # 1. Callsign (large)
    draw.text((TEXT_X, 0), "AAL1695", font=FONT_6X10, fill=(255, 220, 0))
    
    # 2. Route (smaller)
    draw.text((TEXT_X, 12), "PHL - BOS", font=FONT_5X8, fill=(0, 220, 255))
    
    # 3. Paged info (smaller)
    if page == 0:
        draw.text((TEXT_X, 22), "27k 503kt", font=FONT_5X8, fill=(0, 220, 0))
    else:
        draw.text((TEXT_X, 22), "B38M", font=FONT_5X8, fill=(255, 140, 0))
        
    return image

img1 = mock_design_2(0)
img1.save("mock_3line_1.png")
img2 = mock_design_2(1)
img2.save("mock_3line_2.png")
print("Saved 3line mockups")
