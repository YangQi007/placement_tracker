import psutil
import os
import signal
import time
import sys

def cleanup_placement_tracker():
    """Aggressively clean up all Placement Tracker and related processes"""
    
    # Get the current process ID to avoid killing ourselves
    current_pid = os.getpid()
    current_process = psutil.Process(current_pid)
    
    # Get all processes
    killed_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
        try:
            # Skip our own cleanup process and its parent
            if proc.pid == current_pid or proc.pid == current_process.ppid():
                continue
                
            # Check process name and command line
            cmdline = ' '.join(proc.cmdline()).lower() if proc.cmdline() else ''
            name = proc.name().lower()
            
            # More comprehensive check for related processes
            if any(x in cmdline for x in ['placement_tracker', 'chrome', 'chromedriver', 'python']) or \
               any(x in name for x in ['python', 'chrome', 'chromedriver', 'python3', 'pythonw']):
                
                print(f"Found process: {proc.name()} (PID: {proc.pid})")
                
                try:
                    # Try to terminate the process group
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except:
                    pass
                
                # Try SIGTERM
                try:
                    proc.terminate()
                except:
                    pass
                
                killed_processes.append(proc)
                
                # Kill child processes
                try:
                    children = proc.children(recursive=True)
                    for child in children:
                        print(f"Terminating child process: {child.name()} (PID: {child.pid})")
                        try:
                            child.terminate()
                            killed_processes.append(child)
                        except:
                            pass
                except:
                    pass
                
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    # Wait a moment for processes to terminate
    time.sleep(2)
    
    # Force kill any remaining processes
    for proc in killed_processes:
        try:
            if proc.is_running():
                print(f"Force killing process: {proc.name()} (PID: {proc.pid})")
                try:
                    # Try SIGKILL on process group
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except:
                    pass
                
                try:
                    proc.kill()
                except:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Final check for any zombie processes
    time.sleep(1)
    for proc in psutil.process_iter(['pid', 'name', 'status']):
        try:
            if proc.status() == psutil.STATUS_ZOMBIE:
                try:
                    os.kill(proc.pid, signal.SIGKILL)
                except:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

if __name__ == "__main__":
    print("Starting aggressive cleanup...")
    cleanup_placement_tracker()
    print("Cleanup completed")
    # Force exit to ensure we don't leave any processes behind
    sys.exit(0) 