from PIL import Image, ImageDraw, ImageFont

img_path = "/Users/sritejpalika/.gemini/antigravity/brain/60427dfa-b0f2-4a87-982a-ca198fd233ae/media__1782293590316.png"
out_path = "/Users/sritejpalika/.gemini/antigravity/brain/60427dfa-b0f2-4a87-982a-ca198fd233ae/annotated_chart.png"

try:
    img = Image.open(img_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    
    # Coordinates (rough estimates based on visual structure)
    # Trade 1: x~180, y~260
    # Trade 2: x~400, y~180
    # Trade 3: x~600, y~110
    
    # Try to load a font, otherwise use default
    try:
        font = ImageFont.truetype("Arial", 16)
    except:
        font = ImageFont.load_default()
        
    def draw_pointer(draw, text, target_x, target_y, text_x, text_y):
        # Draw line pointing to target
        draw.line([(text_x + 20, text_y + 20), (target_x, target_y)], fill="blue", width=3)
        # Draw circle at target
        draw.ellipse([(target_x-10, target_y-10), (target_x+10, target_y+10)], outline="blue", width=3)
        # Draw text background
        draw.rectangle([(text_x-5, text_y-5), (text_x+120, text_y+40)], fill=(255, 255, 255, 200), outline="black")
        # Draw text
        draw.text((text_x, text_y), text, fill="black", font=font)

    draw_pointer(draw, "Trade #1\nFirst Pullback\nBuy on Green", 195, 245, 100, 320)
    draw_pointer(draw, "Trade #2\nSideways Chop\nBuy on Reclaim", 410, 180, 350, 260)
    draw_pointer(draw, "Trade #3\nLaunchpad\nBuy on Bounce", 580, 100, 500, 180)
    
    # Add title
    draw.rectangle([(10, 10), (350, 40)], fill=(255, 255, 255, 220), outline="blue")
    draw.text((20, 15), "9-EMA Scalper Strategy (Blue Line = 9 EMA)", fill="black", font=font)

    # Convert to RGB to save as PNG (removes alpha channel issues)
    img = img.convert("RGB")
    img.save(out_path)
    print(f"Saved annotated image to {out_path}")
except Exception as e:
    print(f"Error: {e}")

