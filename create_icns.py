import os
from PIL import Image
import subprocess

def create_iconset(png_path):
    """
    Convert a PNG file into a Mac OS X iconset
    """
    # Create iconset directory
    iconset_path = "icon.iconset"
    if not os.path.exists(iconset_path):
        os.makedirs(iconset_path)
    
    # Define required icon sizes
    icon_sizes = [
        (16, '16x16'),
        (32, '16x16@2x'),
        (32, '32x32'),
        (64, '32x32@2x'),
        (128, '128x128'),
        (256, '128x128@2x'),
        (256, '256x256'),
        (512, '256x256@2x'),
        (512, '512x512'),
        (1024, '512x512@2x')
    ]
    
    # Open original image
    img = Image.open(png_path)
    
    # Create each icon size
    for size, name in icon_sizes:
        scaled_img = img.resize((size, size), Image.Resampling.LANCZOS)
        scaled_img.save(f'{iconset_path}/icon_{name}.png')
    
    print("Created iconset folder with all required sizes")
    
    # Convert iconset to icns
    if os.path.exists('icon.icns'):
        os.remove('icon.icns')
    
    subprocess.run(['iconutil', '-c', 'icns', iconset_path])
    print("Created icon.icns file")
    
    # Clean up iconset directory
    subprocess.run(['rm', '-rf', iconset_path])
    print("Cleaned up temporary files")

if __name__ == "__main__":
    # Check if app.png exists
    if not os.path.exists('app.png'):
        print("Error: app.png not found in current directory")
        exit(1)
        
    create_iconset('app.png') 