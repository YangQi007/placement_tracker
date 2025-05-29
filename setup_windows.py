import os
import shutil
import sys
import subprocess

def setup_windows_app():
    """Set up the Placement Tracker app for Windows"""
    print("Setting up Placement Tracker for Windows...")
    
    try:
        # 1. Create installation directory
        install_dir = os.path.expanduser("~\\Documents\\Placement Tracker")
        if not os.path.exists(install_dir):
            os.makedirs(install_dir)
            print(f"Created installation directory: {install_dir}")
            
        # 2. Copy app files from dist folder
        dist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist', 'Placement Tracker')
        if not os.path.exists(dist_dir):
            print("Error: Please run build.py first to create the application.")
            return
            
        # Copy all files from dist to installation directory
        for item in os.listdir(dist_dir):
            src = os.path.join(dist_dir, item)
            dst = os.path.join(install_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            else:
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        print("Copied application files")
        
        # 3. Create example secret.toml if it doesn't exist
        secret_path = os.path.join(install_dir, 'secret.toml')
        if not os.path.exists(secret_path):
            with open(secret_path, 'w') as f:
                f.write("""spotify_client_id = "your_spotify_client_id"
spotify_client_secret = "your_spotify_client_secret"
genius_token = "your_genius_token"
youtube_api_key = "your_youtube_api_key"
""")
            print("Created example secret.toml")
            
        # 4. Create desktop shortcut
        desktop = os.path.expanduser("~\\Desktop")
        shortcut_path = os.path.join(desktop, "Placement Tracker.lnk")
        
        exe_path = os.path.join(install_dir, "Placement_Tracker_Win.exe")
        
        # Create shortcut using PowerShell
        ps_script = f"""
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{exe_path}"
$Shortcut.WorkingDirectory = "{install_dir}"
$Shortcut.Save()
"""
        with open("create_shortcut.ps1", "w") as f:
            f.write(ps_script)
            
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "create_shortcut.ps1"], 
                      capture_output=True)
        os.remove("create_shortcut.ps1")
        
        print(f"""
Setup completed successfully!

Installation directory: {install_dir}
Desktop shortcut created: {shortcut_path}

Please:
1. Edit secret.toml in the installation directory with your API credentials
2. Run the app using the desktop shortcut or the exe in the installation directory

Enjoy using Placement Tracker!
""")
        
    except Exception as e:
        print(f"Error during setup: {str(e)}")
        
if __name__ == "__main__":
    setup_windows_app() 