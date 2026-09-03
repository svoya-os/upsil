from PIL import Image

def remove_white_bg(input_path, output_path):
    # Open the image
    img = Image.open(input_path)
    
    # Convert to RGBA
    img = img.convert("RGBA")
    
    # Get data
    datas = img.getdata()
    
    new_data = []
    for item in datas:
        # If the pixel is close to white, make it transparent
        # 220 is a good threshold for "white"
        if item[0] > 220 and item[1] > 220 and item[2] > 220:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)
            
    # Update image data
    img.putdata(new_data)
    
    # Save as PNG
    img.save(output_path, "PNG")
    print(f"Saved transparent PNG to {output_path}")

input_jpg = r"C:\Users\makse\.gemini\antigravity-ide\brain\8c53e53e-7ca7-4a87-8ed7-a9e79bf918b6\upsil_2d_brain_1786620928232.jpg"
output_png = r"C:\Users\makse\OneDrive\Desktop\НОВЫЙ ЯЗЫК\vscode-upsil\upsil-logo.png"

remove_white_bg(input_jpg, output_png)
