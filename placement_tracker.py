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
import tomli  # Add this to imports

# Move these to the top, after imports but before other code
class ProcessManager:
    """Manage all processes and ensure proper cleanup"""
    def __init__(self):
        self.processes = set()
        self.drivers = set()
        self.pools = set()
        self.semaphores = []
    
    def register_process(self, process):
        self.processes.add(process)
    
    def register_driver(self, driver):
        self.drivers.add(driver)
    
    def register_pool(self, pool):
        self.pools.add(pool)
        
    def register_semaphore(self, sem):
        self.semaphores.append(sem)
    
    def cleanup(self):
        # Clean up multiprocessing pools
        for pool in self.pools:
            try:
                pool.terminate()  # Terminate first
                pool.join()      # Then join
                pool.close()     # Finally close
            except:
                pass
        
        # Clean up webdrivers
        for driver in self.drivers:
            try:
                driver.quit()
            except:
                pass
        
        # Clean up processes
        for process in self.processes:
            try:
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
            except:
                pass
                
        # Clean up semaphores
        for sem in self.semaphores:
            try:
                sem.unlink()  # Remove the semaphore file
            except:
                pass
        
        # Clear all sets
        self.processes.clear()
        self.drivers.clear()
        self.pools.clear()
        self.semaphores.clear()

# Create global process manager
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
        pass  # In ca

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
        # Initialize Chrome WebDriver
        options = webdriver.ChromeOptions()
        options.add_argument('--log-level=3')
        options.add_argument('--headless')  # Add headless mode
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        process_manager.register_driver(driver)  # Register the driver
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
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
            
            while True:
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
                time.sleep(3)
                
                new_height = driver.execute_script("return document.documentElement.scrollHeight")
                
                # If height hasn't changed and no new items loaded, we've reached the end
                if new_height == last_height:
                    # Try waiting one more time for content
                    time.sleep(3)
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
        
        except Exception as e:
            print(f"Error scraping producer page: {str(e)}")
            return []
    
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
    

def get_everything_from_spotify_producer_page(producer_url, batch_size=9, test=True, mode="all", limit=None, genius_token=None, spotify_access_token=None):
    """
    Version with rate limiting and proper resource cleanup
    """
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
    
    try:
        ctx = multiprocessing.get_context('spawn')
        with ctx.Pool(processes=num_processes) as pool:
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


def export_to_csv(data, filepath):
    """
    Write the collected data to a CSV file with formatted numbers.
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
    
    # Write simplified CSV
    try:
        with open(filepath.replace(".csv", " - Placement Tracker - Simplified.csv"), "w+", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=simp_fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(formatted_data)
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
def run_gui():
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
            # Clean up all processes
            process_manager.cleanup()
            
            # Destroy all child windows
            for child in root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            
            # Destroy main window
            root.destroy()
            
            # Force garbage collection
            gc.collect()
            
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")
            
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
    frame_output.pack(fill='x', anchor='w', pady=5)
    
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
        export_to_csv(results, csv_path)
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
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination request
    
    try:
        multiprocessing.freeze_support()
        run_gui()
    except Exception as e:
        print(f"Error in main execution: {str(e)}")
    finally:
        try:
            # Clean up all processes
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