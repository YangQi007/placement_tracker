from PIL import Image
import os

def create_ico(png_path):
    """
    Convert a PNG file into a Windows ICO file with multiple sizes
    """
    # Open original image
    img = Image.open(png_path)
    
    # ICO files should have these sizes
    sizes = [16, 32, 48, 64, 128, 256]
    
    # Create temporary images for each size
    imgs = []
    for size in sizes:
        # Create a copy of the image with RGBA mode
        resized_img = img.resize((size, size), Image.Resampling.LANCZOS)
        if resized_img.mode != 'RGBA':
            resized_img = resized_img.convert('RGBA')
        imgs.append(resized_img)
    
    # Remove existing icon if it exists
    if os.path.exists('icon.ico'):
        os.remove('icon.ico')
    
    # Save as ICO
    try:
        # Use the first image as base and append others
        imgs[0].save('icon.ico', format='ICO', sizes=[(img.size) for img in imgs])
        print("Successfully created icon.ico")
    except Exception as e:
        print(f"Error creating ICO file: {str(e)}")

if __name__ == "__main__":
    # Check if app.png exists
    if not os.path.exists('app.png'):
        print("Error: app.png not found in current directory")
        exit(1)
    
    create_ico('app.png') 