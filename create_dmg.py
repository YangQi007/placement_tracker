import os
import subprocess

def create_dmg():
    """Create a DMG file for distribution"""
    try:
        # Get the directory where the script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Define paths
        app_path = os.path.join(script_dir, 'dist', 'Placement Tracker.app')
        dmg_path = os.path.join(script_dir, 'dist', 'Placement_Tracker.dmg')
        
        # Remove existing DMG if it exists
        if os.path.exists(dmg_path):
            os.remove(dmg_path)
        
        print("Creating DMG file...")
        
        # Create DMG
        subprocess.run([
            'hdiutil', 'create',
            '-volname', 'Placement Tracker',
            '-srcfolder', app_path,
            '-ov', dmg_path,
            '-format', 'UDZO'
        ], check=True)
        
        print(f"DMG created successfully at: {dmg_path}")
        
    except Exception as e:
        print(f"Error creating DMG: {str(e)}")

if __name__ == "__main__":
    create_dmg() 