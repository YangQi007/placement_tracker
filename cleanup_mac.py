import psutil
import os
import signal
import time
import subprocess

def cleanup_placement_tracker_mac():
    """Aggressively clean up all Placement Tracker processes on macOS"""
    
    # Get the current process ID to avoid killing ourselves
    current_pid = os.getpid()
    
    # First try using pkill
    try:
        subprocess.run(['pkill', '-f', 'Placement_Tr'], check=False)
        subprocess.run(['pkill', '-f', 'placement_tracker'], check=False)
    except:
        pass
    
    time.sleep(1)
    
    # Then use psutil for more detailed cleanup
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.pid == current_pid:
                continue
                
            name = proc.name().lower()
            cmdline = ' '.join(proc.cmdline()).lower() if proc.cmdline() else ''
            
            if 'placement' in name or 'placement' in cmdline:
                print(f"Killing process: {proc.name()} (PID: {proc.pid})")
                
                # Try different kill signals
                try:
                    os.kill(proc.pid, signal.SIGTERM)
                except:
                    pass
                    
                time.sleep(0.1)
                
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except:
                    pass
                    
                # If process still exists, try force kill
                if psutil.pid_exists(proc.pid):
                    subprocess.run(['kill', '-9', str(proc.pid)], check=False)
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Final force kill using terminal commands
    commands = [
        "killall -9 Placement_Tracker",
        "killall -9 Python",
        "killall -9 python3",
        "killall -9 pythonw",
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd.split(), check=False)
        except:
            pass

if __name__ == "__main__":
    print("Starting aggressive macOS cleanup...")
    cleanup_placement_tracker_mac()
    print("Cleanup completed") 