import os
import psutil
import glob

def kill_python_processes():
    """Kill all running Python processes except the current one"""
    current_pid = os.getpid()
    print(f"Current process ID: {current_pid}")
    
    killed = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # Check if it's a Python process
            if 'python' in proc.info['name'].lower() and proc.info['pid'] != current_pid:
                print(f"Killing Python process: {proc.info['pid']}")
                try:
                    proc.kill()
                    killed += 1
                except Exception as e:
                    print(f"Failed to kill process {proc.info['pid']}: {e}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    print(f"Killed {killed} Python processes")

def remove_session_files():
    """Remove all Telethon session files"""
    # Find and remove .session files
    session_files = glob.glob("*.session") + glob.glob("*.session-journal")
    session_files += glob.glob("sessions/*.session") + glob.glob("sessions/*.session-journal")
    session_files += glob.glob("clean_sessions/*.session") + glob.glob("clean_sessions/*.session-journal")
    
    removed = 0
    for file in session_files:
        try:
            os.remove(file)
            print(f"Removed session file: {file}")
            removed += 1
        except Exception as e:
            print(f"Failed to remove {file}: {e}")
    
    print(f"Removed {removed} session files")

if __name__ == "__main__":
    print("Cleaning up all Python processes and session files...")
    try:
        kill_python_processes()
    except Exception as e:
        print(f"Error killing processes: {e}")
    
    try:
        remove_session_files()
    except Exception as e:
        print(f"Error removing session files: {e}")
    
    print("Cleanup complete. Now you can run auth_simple.py to create a clean session.") 