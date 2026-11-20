"""Render the real-size Echo updated card at a selected animation frame.

    venv\\Scripts\\python.exe tools\\update_popup_preview.py out.png [frame]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageColor, ImageDraw  # noqa: E402

import update_card  # noqa: E402


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "update_popup_preview.png"
    frame = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    if frame < 0:
        raise ValueError("Frame must be zero or greater")
    card = update_card.render_card("1.8.37", "1.8.38", "BrightLink Echo")
    conf = update_card.Confetti(card.size, seed=7)
    for _ in range(frame):
        conf.step(1 / 60)
    overlay = Image.new("RGBA", card.size)
    draw = ImageDraw.Draw(overlay)
    for piece in conf.pieces:
        colour = ImageColor.getrgb(piece["colour"])
        fill = (*colour, round(255 * conf.opacity(piece)))
        shape = conf.shape(piece)
        if piece["round"]:
            draw.ellipse(shape, fill=fill)
        else:
            draw.polygon(list(zip(shape[::2], shape[1::2])), fill=fill)
    card.alpha_composite(overlay)
    card.save(out)
    print(out)


if __name__ == "__main__":
    main()
