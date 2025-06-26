import platform
import subprocess
import os
import shutil

def clean_build():
    """Clean previous build artifacts"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"Cleaning {dir_name}...")
            shutil.rmtree(dir_name)

def build():
    system = platform.system()
    
    # Clean previous builds
    clean_build()
    
    if system == "Darwin":  # macOS
        print("Building for macOS...")
        try:
            # Build the app
            result = subprocess.run(["pyinstaller", "--clean", "PlacementTracker.spec"], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print(f"PyInstaller failed: {result.stderr}")
                return False
            
            # Create DMG after building app
            print("Creating DMG...")
            result = subprocess.run(["python", "create_dmg.py"], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print(f"DMG creation failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"Build failed: {str(e)}")
            return False
        
    elif system == "Windows":  # Windows
        print("Building for Windows...")
        try:
            result = subprocess.run(["pyinstaller", "--clean", "Placement_Tracker_Win.spec"], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                print(f"PyInstaller failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"Build failed: {str(e)}")
            return False
    
    print(f"Build completed successfully for {system}")
    return True

if __name__ == "__main__":
    success = build()
    if not success:
        exit(1) 