#!/usr/bin/env python3
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

W, H = 220, 300
OUTLINE = (48, 42, 38, 255)
SKIN = (244, 177, 126, 255)
SKIN_HI = (255, 204, 158, 255)
SKIN_SH = (215, 135, 94, 255)


def drawing_hand(path: Path):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # forearm / palm
    d.polygon([(118, 298), (64, 298), (70, 204), (78, 151), (98, 111), (129, 100), (153, 123), (158, 165), (145, 205)], fill=SKIN, outline=OUTLINE)
    d.ellipse((80, 105, 155, 190), fill=SKIN, outline=OUTLINE, width=4)
    # curled fingers around marker
    d.rounded_rectangle((55, 98, 91, 171), radius=16, fill=SKIN, outline=OUTLINE, width=4)
    d.rounded_rectangle((73, 81, 108, 151), radius=16, fill=SKIN_HI, outline=OUTLINE, width=4)
    d.rounded_rectangle((93, 75, 126, 142), radius=15, fill=SKIN, outline=OUTLINE, width=4)
    # thumb
    d.polygon([(111, 122), (142, 101), (158, 111), (152, 136), (126, 151)], fill=SKIN_HI, outline=OUTLINE)
    # marker angled toward upper-left; tip is reveal anchor
    d.polygon([(26, 36), (44, 27), (117, 133), (100, 144)], fill=(30, 35, 39, 255), outline=OUTLINE)
    d.polygon([(18, 25), (31, 17), (44, 28), (27, 37)], fill=(18, 18, 18, 255), outline=OUTLINE)
    d.line([(81, 211), (126, 225)], fill=SKIN_SH, width=3)
    d.line([(88, 228), (124, 240)], fill=SKIN_SH, width=2)
    im.save(path, optimize=True)


def eraser_hand(path: Path):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # forearm / palm
    d.polygon([(126, 299), (72, 299), (76, 205), (84, 153), (107, 116), (140, 112), (163, 138), (162, 184), (148, 218)], fill=SKIN, outline=OUTLINE)
    d.ellipse((87, 111, 166, 196), fill=SKIN, outline=OUTLINE, width=4)
    # eraser
    d.rounded_rectangle((29, 48, 123, 105), radius=12, fill=(27, 126, 130, 255), outline=OUTLINE, width=5)
    d.rectangle((29, 81, 123, 105), fill=(231, 236, 230, 255), outline=OUTLINE, width=4)
    d.rectangle((29, 48, 123, 63), fill=(52, 154, 157, 255))
    # fingers gripping eraser
    d.rounded_rectangle((78, 91, 111, 158), radius=14, fill=SKIN_HI, outline=OUTLINE, width=4)
    d.rounded_rectangle((102, 92, 134, 162), radius=14, fill=SKIN, outline=OUTLINE, width=4)
    d.polygon([(103, 126), (128, 107), (150, 121), (146, 145), (120, 157)], fill=SKIN_HI, outline=OUTLINE)
    d.line([(91, 220), (132, 232)], fill=SKIN_SH, width=3)
    im.save(path, optimize=True)


drawing_hand(ASSETS / "drawing-hand.png")
eraser_hand(ASSETS / "eraser-hand.png")
print("Prepared V3.4 overlay assets:", ASSETS / "drawing-hand.png", ASSETS / "eraser-hand.png")
