#%%
import tkinter as tk
from tkinter import filedialog, messagebox
import csv
import requests
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import undetected_chromedriver as uc
from multiprocessing import Pool, cpu_count
import multiprocessing
import base64
import json
from tkinter import ttk
import gc
import psutil
import signal
import sys
import platform
import subprocess
import tomli
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import datetime

# CRITICAL: Multiprocessing protection - must be at module level
if __name__ == '__main__':
    multiprocessing.freeze_support()

# For packaged apps, set spawn method immediately but only if we're the main module
if __name__ == '__main__' and getattr(sys, 'frozen', False):
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass  # Already set

# Global flag to prevent multiprocessing during import
_ALLOW_MULTIPROCESSING = False
_IS_MAIN_PROCESS = __name__ == '__main__'

# Google Sheets API setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_credentials():
    """Get or refresh Google Sheets API credentials"""
    creds = None
    
    # Use the same path resolution logic as load_credentials
    def get_possible_paths(filename):
        possible_paths = []
        
        if getattr(sys, 'frozen', False):
            if platform.system() == "Darwin":  # macOS
                # 1. Next to the .app bundle
                app_path = os.path.dirname(sys.executable)
                bundle_path = os.path.abspath(os.path.join(app_path, '..', '..', '..'))
                possible_paths.append(os.path.join(bundle_path, filename))
                
                # 2. Inside the .app bundle's Resources
                resources_path = os.path.abspath(os.path.join(app_path, '..', 'Resources'))
                possible_paths.append(os.path.join(resources_path, filename))
                
                # 3. Inside the .app bundle's MacOS directory
                possible_paths.append(os.path.join(app_path, filename))
            else:
                # For Windows/Linux frozen executables
                exe_path = os.path.dirname(sys.executable)
                possible_paths.append(os.path.join(exe_path, filename))
        else:
            # If running from Python interpreter
            script_path = os.path.dirname(os.path.abspath(__file__))
            possible_paths.append(os.path.join(script_path, filename))
        
        return possible_paths
    
    # Find token.pickle
    token_path = None
    for path in get_possible_paths('token.pickle'):
        if os.path.exists(path):
            token_path = path
            break
    
    # If no existing token found, use the first possible path for saving
    if not token_path:
        token_path = get_possible_paths('token.pickle')[0]
    
    # Check if we have stored credentials
    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"Error loading token.pickle: {str(e)}")
            creds = None
    
    # If credentials don't exist or are invalid, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing credentials: {str(e)}")
                creds = None
        
        if not creds:
            # Find credentials.json
            credentials_path = None
            for path in get_possible_paths('credentials.json'):
                print(f"Checking for credentials.json at: {path}")
                if os.path.exists(path):
                    credentials_path = path
                    print(f"Found credentials.json at: {path}")
                    break
            
            if not credentials_path:
                print("No credentials.json found in any of these locations:")
                for path in get_possible_paths('credentials.json'):
                    print(f"- {path}")
                messagebox.showerror("Google Sheets Setup", 
                    "Please place your Google Sheets API credentials.json file in the application directory.\n"
                    "You can get this from the Google Cloud Console.\n\n"
                    f"Expected locations:\n" + "\n".join([f"• {path}" for path in get_possible_paths('credentials.json')]))
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"Error creating OAuth flow: {str(e)}")
                messagebox.showerror("Google Sheets Setup", 
                    f"Error setting up Google Sheets authentication: {str(e)}")
                return None
        
        # Save the credentials for future use
        if creds:
            try:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, 'wb') as token:
                    pickle.dump(creds, token)
                print(f"Saved credentials to: {token_path}")
            except Exception as e:
                print(f"Error saving token.pickle: {str(e)}")
    
    return creds

def create_or_update_sheet(spreadsheet_id, sheet_name, data):
    """Create or update a Google Sheet with the provided data"""
    try:
        creds = get_google_sheets_credentials()
        if not creds:
            return None
            
        service = build('sheets', 'v4', credentials=creds)
        sheet = service.spreadsheets()
        
        # Prepare the data
        values = []
        # Add headers
        headers = list(data[0].keys())
        values.append(headers)
        # Add data rows
        for row in data:
            values.append([row.get(header, '') for header in headers])
        
        # Prepare the request body
        body = {
            'values': values
        }
        
        # Try to update existing sheet
        try:
            result = sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A1',
                valueInputOption='RAW',
                body=body
            ).execute()
        except:
            # If sheet doesn't exist, create it
            requests = [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }]
            sheet.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
            
            # Now update the new sheet
            result = sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A1',
                valueInputOption='RAW',
                body=body
            ).execute()
        
        return result
    except Exception as e:
        print(f"Error updating Google Sheet: {str(e)}")
        return None

# Move these to the top, after imports but before other code
class ProcessManager:
    """Manage all processes and ensure proper cleanup"""
    def __init__(self):
        self.processes = set()
        self.drivers = set()
        self.pools = set()
        self.semaphores = []
        self.chrome_pids = set()  # Track Chrome process IDs
        self.is_packaged = getattr(sys, 'frozen', False)
        self.cleanup_attempted = False
    
    def register_process(self, process):
        self.processes.add(process)
    
    def register_driver(self, driver):
        self.drivers.add(driver)
        # Try to get Chrome process PID for tracking
        try:
            if hasattr(driver, 'service') and hasattr(driver.service, 'process'):
                self.chrome_pids.add(driver.service.process.pid)
        except:
            pass
    
    def register_pool(self, pool):
        self.pools.add(pool)
        
    def register_semaphore(self, sem):
        self.semaphores.append(sem)
    
    def cleanup(self):
        if self.cleanup_attempted:
            return
        self.cleanup_attempted = True
        
        print("Starting ProcessManager cleanup...")
        
        # For packaged apps, be more aggressive
        if self.is_packaged:
            self._aggressive_cleanup()
        else:
            self._standard_cleanup()
        
        print("ProcessManager cleanup completed")
    
    def _standard_cleanup(self):
        """Standard cleanup for development mode"""
        # Clean up multiprocessing pools first
        for pool in list(self.pools):
            try:
                print(f"Cleaning up pool: {pool}")
                pool.terminate()
                pool.join(timeout=3)
                pool.close()
            except Exception as e:
                print(f"Error cleaning pool: {str(e)}")
        
        # Clean up webdrivers
        for driver in list(self.drivers):
            try:
                print(f"Cleaning up driver: {driver}")
                driver.quit()
            except Exception as e:
                print(f"Error cleaning driver: {str(e)}")
        
        # Clean up processes
        for process in list(self.processes):
            try:
                print(f"Cleaning up process: {process}")
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
            except Exception as e:
                print(f"Error cleaning process: {str(e)}")
        
        self._cleanup_common()
    
    def _aggressive_cleanup(self):
        """Aggressive cleanup for packaged applications"""
        print("Using aggressive cleanup for packaged app...")
        
        # First, try to close pools gracefully but with shorter timeouts
        for pool in list(self.pools):
            try:
                pool.terminate()
                pool.join(timeout=1)  # Shorter timeout
                pool.close()
            except:
                pass
        
        # Force quit all drivers immediately
        for driver in list(self.drivers):
            try:
                driver.quit()
            except:
                pass
        
        # Kill all tracked Chrome processes
        for pid in list(self.chrome_pids):
            try:
                if psutil.pid_exists(pid):
                    proc = psutil.Process(pid)
                    proc.kill()  # Use kill instead of terminate for packaged apps
            except:
                pass
        
        # Kill all processes immediately
        for process in list(self.processes):
            try:
                if process.is_alive():
                    process.kill()  # Use kill instead of terminate
            except:
                pass
        
        # System-level cleanup for macOS
        if platform.system() == "Darwin":
            try:
                # Kill Chrome processes
                subprocess.run(['pkill', '-9', '-f', 'chrome'], check=False)
                subprocess.run(['pkill', '-9', '-f', 'chromedriver'], check=False)
                
                # Kill any Python processes that might be related to our app
                current_pid = os.getpid()
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.pid == current_pid:
                            continue
                        cmdline = ' '.join(proc.cmdline()).lower() if proc.cmdline() else ''
                        if any(keyword in cmdline for keyword in ['placement', 'genius', 'spotify']):
                            proc.kill()
                    except:
                        continue
            except Exception as e:
                print(f"Error in system cleanup: {str(e)}")
        
        self._cleanup_common()
    
    def _cleanup_common(self):
        """Common cleanup tasks"""
        # Clean up semaphores
        for sem in self.semaphores:
            try:
                sem.unlink()
            except:
                pass
        
        # Clear all sets
        self.processes.clear()
        self.drivers.clear()
        self.pools.clear()
        self.semaphores.clear()
        self.chrome_pids.clear()
        
        # Force garbage collection
        gc.collect()

# Create global process manager - but only if we're the main process
process_manager = None
if _IS_MAIN_PROCESS:
    process_manager = ProcessManager()

# Then the rest of your code...
last_api_call_time = 0  # Global variable to track last API call time
update_progress = None  # Global variable for progress updates

# --- Helper Functions ---
def log_message(root,log_text,message, error=False):
    """Add message to log with optional error formatting"""
    try:
        if error:
            log_text.insert(tk.END, "ERROR: " + message + "\n", 'error')
            log_text.tag_configure('error', foreground='red')
        else:
            log_text.insert(tk.END, message + "\n")
        log_text.see(tk.END)
        root.update()
    except:
        pass  # In case of any exception, do nothing

def get_list_of_song_artist_name_track_id_from_spotify_playlist(playlist_url, access_token, mode="all", limit=None):
    """
    Get a list of song, artist name, and track ID from a Spotify playlist.
    """
    try:
        # Extract playlist ID from URL
        playlist_id = playlist_url.split('/playlist/')[1].split('?')[0]
        update_progress(None, f"Accessing Spotify playlist: {playlist_id}")
        
        # Make API request
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            tracks = response.json().get('tracks', {}).get('items', [])
            results = []
            for track in tracks:
                track_info = track.get('track', {})
                song_name = track_info.get('name')
                artist_name = track_info.get('artists', [{}])[0].get('name')
                
                if not song_name or not artist_name:
                    update_progress(None, f"Warning: Incomplete track info found", error=True)
                    continue
                    
                results.append({
                    'song_name': song_name,
                    'artist_name': artist_name,
                    'track_id': track_info.get('id'),
                })
                update_progress(None, f"Found track: {artist_name} - {song_name}")
            
            if mode == "limit" and limit is not None:
                if len(results) > limit:
                    update_progress(20, f"Limiting results to {limit} tracks")
                    return results[:limit]
            
            update_progress(20, f"Total tracks found: {len(results)}")
            return results
        else:
            update_progress(None, f"Error accessing Spotify playlist: Status code {response.status_code}", error=True)
            return []
            
    except Exception as e:
        update_progress(None, f"Error processing Spotify playlist: {str(e)}", error=True)
        return []

# def get_genius_song_url_from_artist_n_song_name(artist_name, song_name):
#     """
#     Get the Genius song URL from an artist name and song name.
#     """
#     return f"https://genius.com/{artist_name}-{song_name}-lyrics"


def get_genius_song_id_w_search_api(song_name, artist_name, access_token):
    """
    Get the Genius song ID from a song name and artist name using the search API.
    """
    url = f"https://api.genius.com/search?q={requests.utils.quote(f'{song_name} {artist_name}')}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    songs=response.json().get('response', {}).get('hits', [])
    song_id=None
    for song in songs:
        if song.get('result', {}).get('primary_artist', {}).get('name').lower() == artist_name.lower() \
            and song.get('result', {}).get('title').lower() == song_name.lower():
            song_id=song.get('result', {}).get('id')
            # update_progress(None, f"Found song ID: {song_id} for {song_name} by {artist_name}")
            return song_id
    print(f"No song ID found for {song_name} by {artist_name}")
    return song_id



def get_list_of_genius_song_urls_from_genius_producer(producer_url, mode="eye_icon", limit=None, min_eye_songs=None):
    """
    Scrapes song URLs from a producer's Genius page.
    mode: "eye_icon" (songs with producer label + additional songs if needed), "all" (all songs), or "limit" (up to N songs)
    """
    driver = None
    try:
        # Initialize Chrome WebDriver with better options for packaged apps
        options = webdriver.ChromeOptions()
        options.add_argument('--log-level=3')
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')
        options.add_argument('--disable-javascript')
        
        # For packaged apps, be more restrictive
        if getattr(sys, 'frozen', False):
            options.add_argument('--single-process')
            options.add_argument('--no-zygote')
            options.add_argument('--disable-background-timer-throttling')
            options.add_argument('--disable-backgrounding-occluded-windows')
            options.add_argument('--disable-renderer-backgrounding')
            options.add_argument('--disable-features=TranslateUI')
            options.add_argument('--disable-ipc-flooding-protection')
            # Set a specific user data directory to avoid conflicts
            import tempfile
            temp_dir = tempfile.mkdtemp()
            options.add_argument(f'--user-data-dir={temp_dir}')
        
        # Try to create driver with timeout
        driver_created = False
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                if getattr(sys, 'frozen', False):
                    # For packaged apps, use regular Chrome driver with explicit service
                    service = Service(ChromeDriverManager().install())
                    service.start()  # Start service explicitly
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    # For development, try undetected chrome first
                    try:
                        driver = uc.Chrome(options=options, version_main=None)
                    except:
                        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
                
                driver_created = True
                break
                
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(2)
        
        if not driver_created:
            raise Exception("Failed to create Chrome driver after multiple attempts")
            
        if process_manager:
            process_manager.register_driver(driver)
        
        # Set shorter timeouts for packaged apps
        if getattr(sys, 'frozen', False):
            driver.set_page_load_timeout(30)  # 30 seconds max
            driver.implicitly_wait(10)  # 10 seconds max
        
        # Set user agent
        try:
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
        except:
            pass  # CDP commands might not work in all configurations
        
        wait = WebDriverWait(driver, 20)
        
        try:
            # Load the producer page
            driver.get(producer_url)
            
            # Wait for content to load
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="ListItem-"]')))
            
            song_urls = []  # All collected songs
            eye_icon_urls = []  # Songs with eye icon
            
            last_height = driver.execute_script("return document.documentElement.scrollHeight")
            previous_items_count = 0
            max_scrolls = 50 if not getattr(sys, 'frozen', False) else 20  # Limit scrolls for packaged apps
            scroll_count = 0
            
            while scroll_count < max_scrolls:
                # Get current page content and process items
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                song_items = soup.find_all('li', class_=lambda x: x and 'ListItem-' in x)
                current_items_count = len(song_items)
                
                # Only process new items (items after previous_items_count)
                for item in song_items[previous_items_count:]:
                    song_link = item.find('a', href=True)
                    if not song_link or not song_link['href'].startswith('https://genius.com/'):
                        continue
                    
                    title_element = item.find('h3')
                    song_title = title_element.text if title_element else "Unknown Title"
                    producer_label = item.find('span', class_=lambda x: x and 'LabelWithIcon-' in x)
                    
                    if mode == "eye_icon":
                        if producer_label and song_link['href'] not in eye_icon_urls:
                            eye_icon_urls.append(song_link['href'])
                            update_progress(None, f"Found song #{len(eye_icon_urls)} with eye icon: {song_title}")
                        elif not producer_label and song_link['href'] not in song_urls and len(eye_icon_urls) + len(song_urls) < min_eye_songs:
                            song_urls.append(song_link['href'])
                            update_progress(None, f"Found additional song #{len(song_urls)}: {song_title}")
                        elif len(eye_icon_urls) + len(song_urls) >= min_eye_songs:
                            update_progress(20, f"Found {len(eye_icon_urls)} songs with eye icon and {len(song_urls)} additional songs")
                            return eye_icon_urls + song_urls[:min_eye_songs - len(eye_icon_urls)]
                    else:
                        if song_link['href'] not in song_urls:
                            song_urls.append(song_link['href'])
                            update_progress(None, f"Found song #{len(song_urls)}: {song_title}")
                            if mode == "limit" and len(song_urls) >= limit:
                                update_progress(20, f"Found limit songs")
                                return song_urls
                
                # Update previous count before scrolling
                previous_items_count = current_items_count
                
                # Scroll and check for end of page
                driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
                time.sleep(2 if getattr(sys, 'frozen', False) else 3)  # Shorter sleep for packaged apps
                
                new_height = driver.execute_script("return document.documentElement.scrollHeight")
                
                # If height hasn't changed and no new items loaded, we've reached the end
                if new_height == last_height:
                    # Try waiting one more time for content
                    time.sleep(2)
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    final_count = len(soup.find_all('li', class_=lambda x: x and 'ListItem-' in x))
                    
                    if final_count == current_items_count:
                        print("\nReached end of page.")
                        if mode == "eye_icon":
                            total_songs = eye_icon_urls + song_urls[:min_eye_songs - len(eye_icon_urls)]
                            print(f"Found {len(eye_icon_urls)} songs with eye icon and {len(song_urls)} additional songs")
                            update_progress(20, f"Found {len(eye_icon_urls)} songs with eye icon and {len(song_urls)} additional songs")
                            return total_songs
                        else:
                            update_progress(20, f"Found {len(song_urls)} songs")
                            return song_urls
                
                last_height = new_height
                scroll_count += 1
        
        except Exception as e:
            print(f"Error scraping producer page: {str(e)}")
            return []
    
    finally:
        if driver:
            try:
                # More aggressive cleanup for packaged apps
                driver.quit()
                
                # For packaged apps, ensure Chrome processes are killed
                if getattr(sys, 'frozen', False) and platform.system() == "Darwin":
                    time.sleep(1)
                    subprocess.run(['pkill', '-9', '-f', 'chrome'], check=False)
                    subprocess.run(['pkill', '-9', '-f', 'chromedriver'], check=False)
                    
            except Exception as e:
                print(f"Error closing driver: {str(e)}")
                # Force kill if normal quit fails
                if platform.system() == "Darwin":
                    subprocess.run(['pkill', '-9', '-f', 'chrome'], check=False)

def get_everything_from_spotify_producer_page(producer_url, batch_size=9, test=True, mode="all", limit=None, genius_token=None, spotify_access_token=None):
    """
    Version with rate limiting and proper resource cleanup
    """
    # Prevent multiprocessing during import
    if not _ALLOW_MULTIPROCESSING:
        print("Multiprocessing not allowed during import - using sequential processing")
        # Fallback to sequential processing
        results = []
        song_dict = get_list_of_song_artist_name_track_id_from_spotify_playlist(producer_url, mode=mode, limit=5 if test else limit, access_token=spotify_access_token)
        for i, song_data in enumerate(song_dict):
            try:
                result = get_genius_song_credits_from_api(
                    None, None, song_data.get("song_name"), 
                    song_data.get("artist_name"), song_data.get("track_id"), genius_token
                )
                if result.get("song_name") is not None:
                    results.append(result)
            except Exception as e:
                print(f"Error processing song: {str(e)}")
                continue
        return results
    
    update_progress(0, "Getting the producer song list...")
    
    if test:
        song_dict = get_list_of_song_artist_name_track_id_from_spotify_playlist(producer_url, mode=mode, limit=5, access_token=spotify_access_token)
    else:
        song_dict = get_list_of_song_artist_name_track_id_from_spotify_playlist(producer_url, mode=mode, limit=limit, access_token=spotify_access_token)
    
    mode_desc = {
        "eye_icon": f"producer songs with an eye icon requested)",
        "all": "all songs",
        "limit": f"songs (limited to {limit})"
    }
    update_progress(20, f"Found {len(song_dict)} {mode_desc[mode]}")

    num_processes = min(cpu_count(), batch_size)
    results = []
    
    # Use different multiprocessing approach for packaged vs development
    if getattr(sys, 'frozen', False):
        # For packaged application, use reduced parallelism with better process management
        num_processes = min(2, num_processes)  # Limit to 2 processes max for stability
        pool = None
        try:
            # Use spawn context with explicit process management
            ctx = multiprocessing.get_context('spawn')
            pool = ctx.Pool(processes=num_processes, maxtasksperchild=5)  # Limit tasks per child
            if process_manager:
                process_manager.register_pool(pool)
            
            # Process in smaller batches for better control
            small_batch_size = min(3, batch_size)
            
            for i in range(0, len(song_dict), small_batch_size):
                batch_idx = i // small_batch_size + 1
                try:
                    batch_results = pool.starmap(get_genius_song_credits_from_api, 
                        [(None, None, song_dict[j].get("song_name"), 
                          song_dict[j].get("artist_name"), song_dict[j].get("track_id"), genius_token) 
                         for j in range(i, min(i + small_batch_size, len(song_dict)))])
                    results.extend([r for r in batch_results if r.get("song_name") is not None])
                except Exception as e:
                    print(f"Error in batch processing: {str(e)}")
                    continue
                    
                current_progress = 20 + (batch_idx * 30.0 / len(song_dict) * small_batch_size)
                update_progress(current_progress, f"Obtained detailed information for {min(i + small_batch_size, len(song_dict))} songs")
                
                # Longer sleep between batches for packaged apps
                if i + small_batch_size < len(song_dict):
                    time.sleep(1.0)
                    
        except Exception as e:
            print(f"Error in packaged multiprocessing: {str(e)}")
            # Fallback to sequential processing if multiprocessing fails
            print("Falling back to sequential processing...")
            for i, song_data in enumerate(song_dict):
                try:
                    result = get_genius_song_credits_from_api(
                        None, None, song_data.get("song_name"), 
                        song_data.get("artist_name"), song_data.get("track_id"), genius_token
                    )
                    if result.get("song_name") is not None:
                        results.append(result)
                    
                    current_progress = 20 + ((i + 1) * 30.0 / len(song_dict))
                    update_progress(current_progress, f"Obtained detailed information for {i + 1} songs")
                    
                except Exception as e:
                    print(f"Error processing song: {str(e)}")
                    continue
        finally:
            if pool:
                try:
                    pool.close()
                    pool.join(timeout=10)  # Longer timeout for packaged apps
                    pool.terminate()
                except Exception as e:
                    print(f"Error closing pool: {str(e)}")
            gc.collect()
    else:
        # For development, use multiprocessing with better cleanup
        pool = None
        try:
            # Use fork context on Unix systems when available, spawn for Windows
            if platform.system() == "Darwin" and hasattr(multiprocessing, 'get_context'):
                ctx = multiprocessing.get_context('fork')
            else:
                ctx = multiprocessing.get_context('spawn')
                
            pool = ctx.Pool(processes=num_processes)
            if process_manager:
                process_manager.register_pool(pool)
            
            for i in range(0, len(song_dict), batch_size):
                batch_idx = i // batch_size + 1
                try:
                    batch_results = pool.starmap(get_genius_song_credits_from_api, 
                        [(None, None, song_dict[j].get("song_name"), 
                          song_dict[j].get("artist_name"), song_dict[j].get("track_id"), genius_token) 
                         for j in range(i, min(i + batch_size, len(song_dict)))])
                    results.extend([r for r in batch_results if r.get("song_name") is not None])
                except Exception as e:
                    print(f"Error in batch processing: {str(e)}")
                    continue
                current_progress = 20 + (batch_idx * 30.0 / len(song_dict))
                update_progress(current_progress, f"Obtained detailed information for {min(i + batch_size, len(song_dict))} songs")
                if i + batch_size < len(song_dict):
                    time.sleep(0.5)
        finally:
            if pool:
                try:
                    pool.close()
                    pool.join(timeout=5)  # Add timeout
                    pool.terminate()
                except:
                    pass
            gc.collect()
    
    return results


    



def get_everything_from_genius_producer_page(producer_url, batch_size=None, test=False, mode="all", limit=None, min_eye_songs=None, genius_token=None):
    """
    Get everything from a Genius producer page
    """
    try:
        update_progress(None, "Getting the producer song list...")
        
        # Validate URL format and transform if needed
        if not producer_url.startswith('https://'):
            producer_url = 'https://genius.com/' + producer_url.lstrip('/')
            
        # Handle different URL formats
        if 'artists' not in producer_url:
            producer_url = producer_url.replace('genius.com/', 'genius.com/artists/')
            
        # Remove /songs from the end if present
        if producer_url.endswith('/songs'):
            producer_url = producer_url[:-6]  # Remove '/songs'
        update_progress(None, f"Using URL: {producer_url}")
        
        # Try alternative URL format if needed
        try:
            song_ids = get_list_of_genius_song_producer_api(producer_url, mode=mode, limit=limit, access_token=genius_token)
            
                
            update_progress(20, f"Found {len(song_ids)} songs" + 
                          (f" (limited to {limit})" if limit else ""))
            
            # Process songs in batches
            results = []
            total_songs = len(song_ids)
            batch_size = batch_size or total_songs
            
            for i in range(0, total_songs, batch_size):
                batch = song_ids[i:i + batch_size]
                update_progress(None, f"Processing batch {i//batch_size + 1} of {(total_songs + batch_size - 1)//batch_size}")
                
                for j,song_id in enumerate(batch):
                    try:
                        song_info = get_genius_song_credits_from_api(song_url=None,song_id=song_id, access_token=genius_token)
                        if song_info:
                            results.append(song_info)
                            update_progress(20+(j+i)*30/total_songs, f"Processed: {song_info['artist_name']} - {song_info['song_name']}")
                        else:
                            update_progress(None, f"Failed to get info for {song_id}", error=True)
                    except Exception as e:
                        update_progress(None, f"Error processing song {song_id}: {str(e)}", error=True)
                        continue
            
            update_progress(50, f"Successfully processed {len(results)} out of {total_songs} songs")
            return results
            
        except Exception as e:
            update_progress(None, f"Error getting song URLs: {str(e)}", error=True)
            return []
            
    except Exception as e:
        update_progress(None, f"Error in producer page processing: {str(e)}", error=True)
        return []

def parse_manual_input(manual_list_text):
    """
    Parse a manual input (e.g., from a multi-line text box) that contains song_name and artist_name pairs.
    Return a list of dictionaries with song_name and artist_name keys.
    """
    # Example: each line "Song Name - Artist Name"
    pairs = []
    for line in manual_list_text.strip().splitlines():
        if "-" in line:
            song, artist = line.split("-", 1)
            pairs.append({
                "song_name": song.strip(),
                "artist_name": artist.strip()
            })
    return pairs

def get_spotify_track_id_from_song_name_and_artist_name(song_name, artist_name, access_token):
    query = f"track:{song_name} artist:{artist_name}"
    encoded_query = requests.utils.quote(query)
    url = f"https://api.spotify.com/v1/search?q={encoded_query}&type=track"
    # print(url)
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)

    track_tuples=decode_spotify_response(response)
    track_id,name=find_best_match(track_tuples,song_name,artist_name)
    return track_id,name

def get_rapidapi_stream_data(track_id):
    """
    Call the RapidAPI endpoint with rate limiting (max 1 call per second)
    """
    global last_api_call_time
    
    # Calculate time since last API call
    current_time = time.time()
    time_since_last_call = current_time - last_api_call_time
    
    # Increase wait time to 2 seconds between calls
    if time_since_last_call < 1.5:
        time.sleep(1.5 - time_since_last_call)
    
    # Make the API call
    url = f"https://spotify-stream-count.p.rapidapi.com/v1/spotify/tracks/{track_id}/streams?trackId={track_id}"
    headers = {
        "x-rapidapi-host": "spotify-stream-count.p.rapidapi.com",
        "x-rapidapi-key": "4a0d96c505mshc3679ecd5e49a02p15d4e6jsnd41db0ce24c8"
    }
    
    response = requests.get(url, headers=headers)
    # Update the last call time
    last_api_call_time = time.time()
    
    if response.status_code == 200:
        return response.json()
    else:
        return None

def calculate_stream_stats(history_json):
    """
    Process the historical stream data to calculate:
      - Overall stream count.
      - Incremental stream count.
    """
    stream_count=int(history_json[-1].get("streams"))
    if len(history_json) > 2:
        change_in_streams=int(history_json[-2].get("streams"))-int(history_json[-3].get("streams"))
    else:
        change_in_streams=None

    return {"stream_count": stream_count, "change_in_streams": change_in_streams}


def export_to_csv(data, filepath, export_to_sheets=False, spreadsheet_id=None, sheet_name=None):
    """
    Write the collected data to a CSV file and optionally to Google Sheets.
    """
    if not data:
        return
    
    fieldnames = [
        "Artist & Title", "Co-Producers", "Actual Track Name", "Label", 
        "Phonographic_copyright", "Copyright", "Total Spotify Streams",
        "Daily Spotify Streams", "YouTube URL", "YouTube Views"
    ]
    simp_fieldnames = [
        "Artist & Title", "Co-Producers", "Label", "Total Spotify Streams", 
        "Daily Spotify Streams", "YouTube Views"
    ]
    
    # Format numbers and handle None values
    formatted_data = []
    for item in data:
        formatted_item = item.copy()
        # Format numbers if they exist and aren't None
        for field in ['Total Spotify Streams', 'Daily Spotify Streams']:
            if formatted_item.get(field) and formatted_item[field] != "None":
                formatted_item[field] = f"{formatted_item[field]:,}"
            else:
                formatted_item[field] = ""  
        
        # Special handling for YouTube Views - empty string instead of "None"
        if formatted_item.get('YouTube Views') and formatted_item['YouTube Views'] != "None":
            formatted_item['YouTube Views'] = f"{formatted_item['YouTube Views']:,}"
        else:
            formatted_item['YouTube Views'] = ""
            
        formatted_data.append(formatted_item)
    
    # Create simplified data
    simplified_data = []
    for item in formatted_data:
        simplified_item = {field: item.get(field, '') for field in simp_fieldnames}
        simplified_data.append(simplified_item)
    
    # Write simplified CSV
    try:
        with open(filepath.replace(".csv", " - Placement Tracker - Simplified.csv"), "w+", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=simp_fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(simplified_data)
    except Exception as e:
        print(f"Error writing simplified CSV: {str(e)}")
        
    # Write raw CSV
    try:
        with open(filepath.replace(".csv", " - Placement Tracker - Raw.csv"), "w+", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(formatted_data)
    except Exception as e:
        print(f"Error writing raw CSV: {str(e)}")
    
    # Export to Google Sheets if requested
    if export_to_sheets and spreadsheet_id and sheet_name:
        try:
            # Export simplified data
            simplified_sheet_name = f"{sheet_name} - Simplified"
            result = create_or_update_sheet(spreadsheet_id, simplified_sheet_name, simplified_data)
            if result:
                print(f"Successfully exported simplified data to Google Sheets: {simplified_sheet_name}")
            else:
                print("Failed to export simplified data to Google Sheets")
            
            # Export raw data
            raw_sheet_name = f"{sheet_name} - Raw"
            result = create_or_update_sheet(spreadsheet_id, raw_sheet_name, formatted_data)
            if result:
                print(f"Successfully exported raw data to Google Sheets: {raw_sheet_name}")
            else:
                print("Failed to export raw data to Google Sheets")
                
        except Exception as e:
            print(f"Error exporting to Google Sheets: {str(e)}")

def run_gui():
    print("run_gui() called")
    # Enable multiprocessing now that we're in the main application
    global _ALLOW_MULTIPROCESSING
    _ALLOW_MULTIPROCESSING = True
    
    # Load credentials at startup
    credentials = load_credentials()
    if not credentials:
        messagebox.showerror("Credentials Error", 
            "Please create a secret.toml file with your credentials.\n"
            "See console output for example format.")
        return
    
    root = tk.Tk()
    
    def on_closing():
        """Handle cleanup when window is closed"""
        try:
            print("Application closing - starting cleanup...")
            
            # Clean up all processes
            if process_manager:
                process_manager.cleanup()
            
            # Destroy all child windows
            for child in root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            
            # Destroy main window
            root.destroy()
            
            # Force garbage collection
            gc.collect()
            
            # For packaged applications, be more aggressive
            if getattr(sys, 'frozen', False):
                print("Packaged app detected - using aggressive cleanup...")
                
                if platform.system() == "Darwin":  # macOS
                    # Wait a moment for normal cleanup to complete
                    time.sleep(1)
                    
                    # Kill any remaining processes related to our app
                    try:
                        current_pid = os.getpid()
                        parent_pid = os.getppid()
                        
                        # Kill Chrome and chromedriver processes
                        subprocess.run(['pkill', '-9', '-f', 'chrome'], check=False)
                        subprocess.run(['pkill', '-9', '-f', 'chromedriver'], check=False)
                        
                        # Kill any Python processes that might be related to our app
                        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
                            try:
                                # Skip our own process and parent
                                if proc.pid in [current_pid, parent_pid]:
                                    continue
                                    
                                cmdline = ' '.join(proc.cmdline()).lower() if proc.cmdline() else ''
                                name = proc.name().lower()
                                
                                # Kill processes that might be related to our app
                                if any(keyword in cmdline for keyword in ['placement', 'genius', 'spotify', 'multiprocessing']):
                                    print(f"Killing related process: {proc.name()} (PID: {proc.pid})")
                                    proc.kill()
                                elif 'python' in name and proc.ppid() == current_pid:
                                    # Kill child Python processes
                                    print(f"Killing child Python process: {proc.name()} (PID: {proc.pid})")
                                    proc.kill()
                                    
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                                
                    except Exception as e:
                        print(f"Error in aggressive cleanup: {str(e)}")
                
                # Force exit for packaged apps
                print("Forcing application exit...")
                os._exit(0)
            else:
                # For development, use normal exit
                print("Development mode - using normal exit...")
                sys.exit(0)
            
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")
            # Force exit even if there's an error
            os._exit(1)
            
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    root.title("Placement Tracker Generator")
    root.geometry("1000x800")

    # Create main container frame with left padding
    main_frame = tk.Frame(root, padx=20)
    main_frame.pack(fill='x', anchor='w')

    # --- Processing Options Frame ---
    frame_processing = tk.Frame(main_frame)
    frame_processing.pack(fill='x', anchor='w', pady=5)
    
    max_processes = cpu_count()
    process_frame = tk.Frame(frame_processing)
    process_frame.pack(fill='x', anchor='w')
    
    tk.Label(process_frame, text="Number of Parallel Processes:").pack(side='left')
    batch_size_var = tk.IntVar(value=min(5, max_processes))
    batch_size_spinbox = ttk.Spinbox(process_frame, 
                                    from_=1, 
                                    to=max_processes, 
                                    width=5, 
                                    textvariable=batch_size_var)
    batch_size_spinbox.pack(side='left', padx=5)

    # --- Song Selection Frame ---
    frame_song_selection = tk.Frame(main_frame)
    frame_song_selection.pack(fill='x', anchor='w', pady=5)
    
    tk.Label(frame_song_selection, text="Song Selection Mode:").pack(anchor='w')
    
    mode_var = tk.StringVar(value="all")
    modes = [
        ("All songs", "all"),
        ("Limited number of songs", "limit")
        # ("Songs with eye icon on Genius.com", "eye_icon")
    ]
    
    mode_frame = tk.Frame(frame_song_selection)
    mode_frame.pack(fill='x', anchor='w')
    
    for text, value in modes:
        radio_frame = tk.Frame(mode_frame)
        radio_frame.pack(fill='x', anchor='w')
        rb = tk.Radiobutton(radio_frame, text=text, value=value, variable=mode_var)
        rb.pack(side='left')
        
        if value == "limit":
            tk.Label(radio_frame, text="Limit:").pack(side='left', padx=20)
            limit_var = tk.IntVar(value=20)
            limit_entry = ttk.Spinbox(radio_frame, from_=1, to=1000, width=5, textvariable=limit_var)
            limit_entry.pack(side='left')
        # elif value == "eye_icon":
        #     tk.Label(radio_frame, text="Include more songs to meet minimum:").pack(side='left', padx=20)
        #     min_eye_var = tk.IntVar(value=20)
        #     min_eye_entry = ttk.Spinbox(radio_frame, from_=1, to=1000, width=5, textvariable=min_eye_var)
        #     min_eye_entry.pack(side='left')

    # --- Input Options Frame ---
    frame_inputs = tk.Frame(main_frame)
    frame_inputs.pack(fill='x', anchor='w', pady=5)

    url_frame = tk.Frame(frame_inputs)
    url_frame.pack(fill='x', anchor='w')
    tk.Label(url_frame, text="Genius/Spotify Producer URL:").pack(side='left')
    producer_url_entry = tk.Entry(url_frame, width=60)
    producer_url_entry.pack(side='left', padx=5)

    manual_frame = tk.Frame(frame_inputs)
    manual_frame.pack(fill='x', anchor='w', pady=5)
    tk.Label(manual_frame, text="Or Enter Song - Artist (one per line):").pack(anchor='w')
    manual_input_text = tk.Text(manual_frame, height=5, width=45)
    manual_input_text.pack(anchor='w')

    # --- Output Options Frame ---
    frame_output = tk.Frame(main_frame)
    frame_output.pack(fill='x', anchor='w')
    
    default_dir = os.path.expanduser("~/Documents")
    
    dir_frame = tk.Frame(frame_output)
    dir_frame.pack(fill='x', anchor='w')
    tk.Label(dir_frame, text="Save Directory:").pack(side='left')
    directory_var = tk.StringVar(value=default_dir)
    tk.Entry(dir_frame, textvariable=directory_var, width=50).pack(side='left', padx=5)
    tk.Button(dir_frame, text="Browse", command=lambda: directory_var.set(
        filedialog.askdirectory(initialdir=default_dir))).pack(side='left')

    filename_frame = tk.Frame(frame_output)
    filename_frame.pack(fill='x', anchor='w', pady=5)
    tk.Label(filename_frame, text="Base Filename (suggest using producer name):").pack(side='left')
    filename_entry = tk.Entry(filename_frame, width=40)
    filename_entry.pack(side='left', padx=5)

    # Add Google Sheets options
    sheets_frame = tk.Frame(frame_output)
    sheets_frame.pack(fill='x', anchor='w', pady=5)
    
    # Google Sheets section header
    sheets_header = tk.Frame(sheets_frame)
    sheets_header.pack(fill='x', anchor='w', pady=(0, 5))
    tk.Label(sheets_header, text="Google Sheets Export", font=('TkDefaultFont', 10, 'bold')).pack(side='left')
    
    # Help button for Google Sheets
    def show_sheets_help():
        help_text = """To export to Google Sheets:
1. Create a Google Sheet and share it with your team
2. Copy the Spreadsheet ID from the URL:
   - It's the long string between /d/ and /edit
   - Example: docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit
   - The ID would be: 1AbCdEfGhIjKlMnOpQrStUvWxYz
3. Enter the Sheet name (defaults to today's date)
4. Check 'Export to Google Sheets'"""
        messagebox.showinfo("Google Sheets Help", help_text)
    
    tk.Button(sheets_header, text="?", command=show_sheets_help, width=2).pack(side='left', padx=5)
    
    # Google Sheets export checkbox
    export_to_sheets_var = tk.BooleanVar(value=False)
    tk.Checkbutton(sheets_frame, text="Export to Google Sheets", variable=export_to_sheets_var).pack(anchor='w', pady=(0, 5))
    
    # Spreadsheet ID entry with better label
    spreadsheet_frame = tk.Frame(sheets_frame)
    spreadsheet_frame.pack(fill='x', anchor='w', pady=2)
    tk.Label(spreadsheet_frame, text="Spreadsheet ID (from Google Sheets URL):").pack(side='left')
    spreadsheet_id_var = tk.StringVar()
    tk.Entry(spreadsheet_frame, textvariable=spreadsheet_id_var, width=50).pack(side='left', padx=5)
    
    # Sheet name entry with better label
    sheet_name_frame = tk.Frame(sheets_frame)
    sheet_name_frame.pack(fill='x', anchor='w', pady=2)
    tk.Label(sheet_name_frame, text="Sheet Name (will create -Simplified and -Raw versions):").pack(side='left')
    sheet_name_var = tk.StringVar(value=datetime.datetime.now().strftime("%Y-%m-%d"))
    tk.Entry(sheet_name_frame, textvariable=sheet_name_var, width=20).pack(side='left', padx=5)

    # --- Progress Frame ---
    frame_progress = tk.Frame(main_frame)
    frame_progress.pack(fill='x', anchor='w', pady=5)
    
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(frame_progress, variable=progress_var, maximum=100)
    progress_bar.pack(fill='x')
    
    log_text = tk.Text(frame_progress, height=5, width=70)
    log_text.pack(pady=5)

    def update_progress_local(value, message):
        progress_var.set(value)
        log_text.insert(tk.END, message + "\n")
        log_text.see(tk.END)
        root.update()
    
    global update_progress
    update_progress = update_progress_local

    def process_data():
        # Get credentials
        credentials = load_credentials()
        if not credentials:
            messagebox.showerror("Credentials Error", 
                "Please create a secret.toml file with your credentials.")
            return
        
        # Use credentials
        client_id = credentials['spotify_client_id']
        client_secret = credentials['spotify_client_secret']
        genius_token = credentials['genius_token']
        youtube_token = credentials['youtube_api_key']
        
        # Get Spotify access token
        access_token = get_spotify_access_token(client_id, client_secret)
        
        # Get input values and format producer URL
        producer_url = producer_url_entry.get().strip()
        if producer_url:
            # Remove @ if present
            if producer_url.startswith('@'):
                producer_url = producer_url[1:]
            # Add /songs if not present
            if not producer_url.endswith('/songs'):
                producer_url = producer_url.rstrip('/') + '/songs'
            
        manual_input = manual_input_text.get("1.0", tk.END).strip()
        save_dir = directory_var.get().strip()
        file_name = filename_entry.get().strip()

        if not save_dir or not file_name:
            messagebox.showerror("Input Error", "Please select a save directory and provide a file name.")
            return
        
        # Add directory validation
        if not os.path.exists(save_dir):
            messagebox.showerror("Directory Error", "Selected directory does not exist.")
            return
        
        if not os.access(save_dir, os.W_OK):
            messagebox.showerror("Permission Error", "Cannot write to selected directory. Please choose another location.")
            return

        # Create full path and validate
        csv_path = os.path.join(save_dir, f"{file_name}.csv")
        try:
            # Test if we can write to this location
            with open(csv_path, 'w') as test_file:
                pass
            os.remove(csv_path)  # Clean up test file
        except OSError as e:
            messagebox.showerror("File Error", f"Cannot write to {csv_path}. Please choose another location.\nError: {str(e)}")
            return

        # Get batch size
        batch_size = batch_size_var.get()
        
        # Get song selection mode and limits
        mode = mode_var.get()
        limit = limit_var.get() if mode == "limit" else None
        min_eye_songs = min_eye_var.get() if mode == "eye_icon" else None
        
        # Step 1: Obtain list of (song, artist) pairs
        if producer_url:
            if 'genius' in producer_url:
                song_list = get_everything_from_genius_producer_page(producer_url, 
                                                  batch_size=batch_size,
                                                  test=False,
                                                  mode=mode,
                                                  limit=limit,
                                                  min_eye_songs=min_eye_songs,
                                                  genius_token=genius_token)
            elif 'spotify' in producer_url:
                song_list = get_everything_from_spotify_producer_page(producer_url, 
                                                  batch_size=batch_size,
                                                  test=False,
                                                  mode=mode,
                                                  limit=limit,
                                                  genius_token=genius_token,
                                                  spotify_access_token=access_token)
        else:
            song_list = []
            initial_song_list = parse_manual_input(manual_input)
            for idx, item in enumerate(initial_song_list, 1):
                song_list.append(get_genius_song_credits_from_api(None, None, item['song_name'], item['artist_name'], None, genius_token))
                update_progress(idx * 50/len(initial_song_list), 
                          f"Getting credit information for {idx}/{len(initial_song_list)} songs: {item['song_name']}")
        if not song_list:
            messagebox.showerror("Input Error", "No song data was found.")
            return

        results = []
        progress_per_song = 50.0 / len(song_list)
        
        for idx, item in enumerate(song_list, 1):
            song_name = item['song_name']
            artist_name = item['artist_name']
            
            

            update_progress(50 + (idx * progress_per_song), 
                          f"Getting stream count for {idx}/{len(song_list)} songs: {song_name}")
            if item.get("track_id"):
                track_id, actual_track_name = item.get("track_id"), item.get("song_name")
            # Get Spotify track ID via API
            else: track_id, actual_track_name = get_spotify_track_id_from_song_name_and_artist_name(song_name, artist_name, access_token)
            if track_id is None:
                print(f"No track ID found for '{song_name}' by '{artist_name}'")
                stream_data = None
            else:
                stream_data = get_rapidapi_stream_data(track_id)

            if stream_data:
                stream_stats = calculate_stream_stats(stream_data)
            else:
                print(f"No stream data found for '{song_name}' by '{artist_name}' with track_id: {track_id}")
                stream_stats = {"stream_count": None, "change_in_streams": None}

            # Get YouTube views if URL exists
            youtube_views = None
            if item.get('youtube_url'):
                youtube_views = get_youtube_view_count(item['youtube_url'], youtube_token)
            
            results.append({
                "Artist & Title": f"{artist_name} - {song_name}",
                "Co-Producers": item.get("co-producers", "None"),
                "Actual Track Name": actual_track_name,
                "Total Spotify Streams": stream_stats["stream_count"],
                "Daily Spotify Streams": stream_stats["change_in_streams"],
                "Label": item.get("label", "None"),
                "Phonographic_copyright": item.get("phonographic_copyright", "None"),
                "Copyright": item.get("copyright", "None"),
                "YouTube URL": item.get("youtube_url", "None"),
                "YouTube Views": youtube_views if youtube_views is not None else "None",
            })

            # Update progress after each song
            current_progress = 50 + (idx * progress_per_song)
            if current_progress > 100:
                current_progress = 100
            update_progress(current_progress, f"Processed {idx}/{len(song_list)} songs")

        # Define the CSV file path and export the data
        csv_path = os.path.join(save_dir, f"{file_name}.csv")
        export_to_csv(results, csv_path, export_to_sheets=export_to_sheets_var.get(), spreadsheet_id=spreadsheet_id_var.get(), sheet_name=sheet_name_var.get())
        messagebox.showinfo("Success", f"CSV file generated at: {csv_path} and {csv_path.replace('.csv', '_raw.csv')}")

    tk.Button(main_frame, text="Start Processing", command=process_data, width=20).pack(anchor='w', pady=10)

    try:
        root.mainloop()
    finally:
        # Ensure cleanup happens even if mainloop crashes
        try:
            root.destroy()
        except:
            pass
def format_spotify_search_query(song_name, artist_name):
    """
    Format search query for Spotify API
    """
    query = f"track:{song_name} artist:{artist_name}"
    # URL encode the query
    encoded_query = requests.utils.quote(query)
    return encoded_query


def get_spotify_access_token(client_id, client_secret):
    """
    Get the access token for the Spotify API.
    """
    url = "https://accounts.spotify.com/api/token"
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_auth}"
    }
    data = {
        "grant_type": "client_credentials"
    }
    
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        raise Exception(f"Failed to get access token: {response.status_code} - {response.text}")


def decode_spotify_response(response):
    """
    Decode the Spotify response to get the (name, artists, track_id) tuples.
    """
    track_ids = []
    for item in response.json().get("tracks", {}).get("items", []):
        name=item.get("name")
        artist_field=item.get("artists",[])
        artists=[]
        for artist_item in artist_field:
            artists.append(artist_item.get("name"))
        track_id=item.get("id")
        track_ids.append((name,artists,track_id))
    return track_ids

def find_best_match(track_tuples, song_name, artist_name):
    """
    Find the best match for the given song and artist name from the list of track tuples.
    """
    # Normalize strings by removing all non-alphanumeric characters and converting to lowercase
    def normalize_string(s):
        return ''.join(c.lower() for c in s if c.isalnum())
    
    def remove_brackets(string):
        # Remove content inside brackets and the brackets themselves
        while '(' in string and ')' in string:
            start = string.find('(')
            end = string.find(')')
            if start < end:
                string = string[:start].strip() + string[end+1:].strip()
        return string
    
    normalized_song_wo_brackets = normalize_string(remove_brackets(song_name))
    normalized_song_w_brackets = normalize_string(song_name)
    for name, artists, track_id in track_tuples:
        normalized_name_wo_brackets = normalize_string(remove_brackets(name))
        normalized_name_w_brackets = normalize_string(name)
        if normalized_song_w_brackets == normalized_name_w_brackets and any(artist_name.lower() in artist.lower() for artist in artists):
            return track_id,name
        if normalized_song_wo_brackets == normalized_name_wo_brackets and any(artist_name.lower() in artist.lower() for artist in artists):
            return track_id,name
    return None,None
def get_genius_song_credits_from_api(song_url=None,song_id=None, song_name=None, artist_name=None, track_id=None, access_token=None):
    """
    Get song credits using Genius's internal API
    """
    if song_id:
        url = f"https://genius.com/api/songs/{song_id}"
    elif song_url:
        song_id=get_genius_song_id_from_url(song_url)
        url = f"https://genius.com/api/songs/{song_id}"
    elif song_name and artist_name:
        song_id=get_genius_song_id_w_search_api(song_name, artist_name, access_token)
        url = f"https://genius.com/api/songs/{song_id}"
    else:
        return {
            "song_name": song_name,
            "artist_name": artist_name,
            "co-producers": None,
            "label": None,
            "copyright": None,
            "phonographic_copyright": None,
            "track_id": track_id,
            "youtube_url": None
        }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json", 
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        song_data = response.json().get('response', {}).get('song', {})
        
        # Extract credits from custom_performances for label and copyright info
        custom_performances = song_data.get('custom_performances', [])
        label_data = next((item for item in custom_performances if item.get('label') == 'Label'), None)
        copyright_data = next((item for item in custom_performances if item.get('label') == 'Copyright ©'), None)
        phono_copyright_data = next((item for item in custom_performances if item.get('label') == 'Phonographic Copyright ℗'), None)

        youtube_url=None
        for media in song_data.get('media', []):
            if media.get('provider') == 'youtube':
                youtube_url = media.get('url')
                break
        # Get producers directly from producer_artists field
        producer_artists = song_data.get('producer_artists', [])
        
        return {
            "song_name": song_data.get('title'),
            "artist_name": song_data.get('primary_artist', {}).get('name'),
            "co-producers": ", ".join([p.get('name') for p in producer_artists]) if producer_artists else None,
            "label": " & ".join([a.get('name') for a in label_data.get('artists', [])]) if label_data else None,
            "copyright": " & ".join([a.get('name') for a in copyright_data.get('artists', [])]) if copyright_data else None,
            "phonographic_copyright": " & ".join([a.get('name') for a in phono_copyright_data.get('artists', [])]) if phono_copyright_data else None,
            "track_id": track_id,
            "youtube_url": youtube_url
        }
    else:
        return {
            "song_name": song_name,
            "artist_name": artist_name,
            "co-producers": None,
            "label": None,
            "copyright": None,
            "phonographic_copyright": None,
            "track_id": track_id,
            "youtube_url": None
        }

            # result = {
            #     "song_name": song_name,
            #     "artist_name": artist_name,
            #     "co-producers": ", ".join(producers) if producers else None,
            #     "label": " & ".join(labels) if labels else None,
            #     "phonographic_copyright": " & ".join(phono_copyright) if phono_copyright else None,
            #     "copyright": " & ".join(copyright_info) if copyright_info else None,
            #     "track_id": track_id
            # }

def get_genius_song_id_from_url(url):
    """
    Get song ID from a Genius song URL by extracting it from the meta tag
    """

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        # Look for meta tag with genius://songs/ in content
        meta_tag = soup.find('meta', attrs={'property': 'twitter:app:url:iphone'})
        if meta_tag and 'content' in meta_tag.attrs:
            # Extract song ID from genius://songs/7325192
            song_id = meta_tag['content'].split('/')[-1]
            return song_id
    return None

def get_youtube_view_count(video_url, youtube_api_key):
    """
    Get view count for a YouTube video using the YouTube Data API
    """
    if not video_url or not youtube_api_key:
        return None
        
    # Extract video ID from URL
    try:
        # Handle different URL formats
        if 'youtu.be' in video_url:
            video_id = video_url.split('/')[-1]
        else:
            video_id = video_url.split('v=')[1].split('&')[0]
            
        # Make API request
        url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={youtube_api_key}"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('items'):
                return int(data['items'][0]['statistics']['viewCount'])
    except Exception as e:
        print(f"Error getting YouTube views: {str(e)}")
    return None

def cleanup_resources():
    """Clean up any remaining resources"""
    try:
        # Clean up processes
        if process_manager:
            process_manager.cleanup()
        
        # Force garbage collection
        gc.collect()
        
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")

def signal_handler(signum, frame):
    """Handle Ctrl+C and other termination signals"""
    print("\nReceived termination signal. Cleaning up...")
    try:
        # Clean up all processes
        if process_manager:
            process_manager.cleanup()
        
        # Force garbage collection
        gc.collect()
        
        # Kill any remaining Chrome processes
        if platform.system() == "Darwin":  # macOS
            subprocess.run(['pkill', '-f', 'chrome'], check=False)
            
        print("Cleanup completed. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"Error during signal cleanup: {str(e)}")
        sys.exit(1)

def load_credentials():
    """
    Load credentials from secret.toml file in the same directory as the application
    Returns a dictionary with credentials or None if file not found/invalid
    """
    try:
        # Get possible paths for secret.toml
        possible_paths = []
        
        if getattr(sys, 'frozen', False):
            if platform.system() == "Darwin":  # macOS
                # 1. Next to the .app bundle
                app_path = os.path.dirname(sys.executable)
                bundle_path = os.path.abspath(os.path.join(app_path, '..', '..', '..'))
                possible_paths.append(os.path.join(bundle_path, 'secret.toml'))
                
                # 2. Inside the .app bundle's Resources
                resources_path = os.path.abspath(os.path.join(app_path, '..', 'Resources'))
                possible_paths.append(os.path.join(resources_path, 'secret.toml'))
                
                # 3. Inside the .app bundle's MacOS directory
                possible_paths.append(os.path.join(app_path, 'secret.toml'))
            else:
                # For Windows/Linux frozen executables
                exe_path = os.path.dirname(sys.executable)
                possible_paths.append(os.path.join(exe_path, 'secret.toml'))
        else:
            # If running from Python interpreter
            script_path = os.path.dirname(os.path.abspath(__file__))
            possible_paths.append(os.path.join(script_path, 'secret.toml'))
        
        # Try each possible path
        for config_path in possible_paths:
            print(f"Checking for secret.toml at: {config_path}")
            if os.path.exists(config_path):
                print(f"Found secret.toml at: {config_path}")
                with open(config_path, 'rb') as f:
                    secrets = tomli.load(f)
                    required_keys = {
                        'spotify_client_id',
                        'spotify_client_secret',
                        'genius_token',
                        'youtube_api_key'
                    }
                    
                    if all(key in secrets for key in required_keys):
                        return secrets
                    else:
                        print("Warning: secret.toml is missing required credentials")
                        
        # If we get here, no valid config file was found
        print("No valid secret.toml found in any of these locations:")
        for path in possible_paths:
            print(f"- {path}")
        print("\nPlease create secret.toml with your credentials in one of these locations.")
        print("Example secret.toml format:")
        print("""
spotify_client_id = "your_spotify_client_id"
spotify_client_secret = "your_spotify_client_secret"
genius_token = "your_genius_token"
youtube_api_key = "your_youtube_api_key"
        """)
        return None
        
    except Exception as e:
        print(f"Error reading secret.toml: {str(e)}")
        return None

def get_artist_id(genius_url):
    """
    Extract Artist ID from a Genius artist page URL.
    Args:
        genius_url (str): URL of the Genius artist page
    Returns:
        str: Artist ID if found, None otherwise
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(genius_url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find meta tag containing artist data
            meta_tag = soup.find('meta', attrs={'itemprop': 'page_data'})
            if meta_tag and 'content' in meta_tag.attrs:
                content = json.loads(meta_tag['content'])
                
                # Extract Artist ID from tracking_data
                tracking_data = content.get('tracking_data', [])
                for item in tracking_data:
                    if item.get('key') == 'Artist ID':
                        return str(item.get('value'))
                        
                # Alternative method - try getting from artist object
                artist = content.get('artist', {})
                if artist and 'id' in artist:
                    return str(artist['id'])
                    
        return None
        
    except Exception as e:
        print(f"Error getting artist ID: {str(e)}")
        return None

def get_list_of_genius_song_producer_api(producer_url, mode="all", limit=None, access_token=None):
    """
    Get list of song IDs from a producer's Genius page using the API.
    
    Args:
        producer_url (str): URL of the producer's Genius page
        mode (str): 'all' to get all songs, 'limit' to get limited number
        limit (int): Number of songs to get if mode is 'limit'
        access_token (str): Genius API access token
        
    Returns:
        list: List of song IDs
    """
    if not access_token:
        credentials = load_credentials()
        if not credentials or 'genius_token' not in credentials:
            print("Error: Genius API token not found")
            return []
        access_token = credentials['genius_token']

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # First get the artist ID from the URL
        artist_id = get_artist_id(producer_url)
        if not artist_id:
            print("Error: Could not get artist ID")
            return []

        song_ids = []
        page = 1
        per_page = 50  # Maximum allowed by API
        
        while True:
            # Make API request
            url = f"https://api.genius.com/artists/{artist_id}/songs"
            params = {
                "sort": "popularity",
                "per_page": per_page,
                "page": page
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"Error: API request failed with status {response.status_code}")
                break
                
            data = response.json()
            songs = data.get('response', {}).get('songs', [])
            
            if not songs:
                break
                
            # Extract song IDs
            for song in songs:
                song_ids.append(song['id'])
                
                # Check if we've reached the limit
                if mode == "limit" and limit and len(song_ids) >= limit:
                    return song_ids[:limit]
            
            # Check if there are more pages
            # if len(songs) < per_page:
            #     break
                
            page += 1
            # Add a small delay to avoid hitting rate limits
            time.sleep(0.5)
        
        # update_progress(None, f"Found {len(song_ids)} songs via API")
        return song_ids

    except Exception as e:
        print(f"Error getting songs from API: {str(e)}")
        return []

#%%
if __name__ == "__main__":
    print(f"IMPORT: __name__={__name__}, sys.argv={sys.argv}, frozen={getattr(sys, 'frozen', False)}")
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination request
    
    try:
        # Ensure multiprocessing is properly initialized for packaged apps
        if getattr(sys, 'frozen', False):
            multiprocessing.freeze_support()
        
        # Start the GUI application
        run_gui()
    except Exception as e:
        print(f"Error in main execution: {str(e)}")
    finally:
        try:
            # Clean up all processes
            if process_manager:
                process_manager.cleanup()
            
            # Force garbage collection
            gc.collect()
            
            # Kill any remaining Chrome processes
            if platform.system() == "Darwin":  # macOS
                subprocess.run(['pkill', '-f', 'chrome'], check=False)
            
            sys.exit(0)
        except Exception as e:
            print(f"Error during final cleanup: {str(e)}")
            sys.exit(1)