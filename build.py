import platform
import subprocess
import os

def build():
    system = platform.system()
    
    if system == "Darwin":  # macOS
        print("Building for macOS...")
        subprocess.run(["pyinstaller", "Placement_Tracker_Mac.spec"])
        
        # Create DMG after building app
        print("Creating DMG...")
        subprocess.run(["python", "create_dmg.py"])
        
    elif system == "Windows":  # Windows
        print("Building for Windows...")
        subprocess.run(["pyinstaller", "Placement_Tracker_Win.spec"])
        
    print(f"Build completed for {system}")

if __name__ == "__main__":
    build() 