#%%
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
import base64
import json
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
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import queue
import threading

# --- Global Configuration ---
# Google Sheets API scope
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
# Global variable to track last API call time for rate limiting (thread-safe)
last_api_call_time = 0
api_call_lock = threading.Lock()


# --- Path Management ---
def get_resource_path(filename):
    """
    Get the absolute path to a resource, works for dev and for PyInstaller.
    This is crucial for ensuring the packaged app can find its files.
    """
    # For PyInstaller-created temporary folder
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    
    # For development (running as a .py script)
    base_path = os.path.abspath(".")
    return os.path.join(base_path, filename)


# --- Google Sheets Integration ---
def get_google_sheets_credentials():
    """Get or refresh Google Sheets API credentials."""
    creds = None
    token_path = get_resource_path('token.pickle')
    credentials_path = get_resource_path('credentials.json')

    if os.path.exists(token_path):
        try:
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)
        except (pickle.UnpicklingError, EOFError, FileNotFoundError) as e:
            print(f"Could not load token.pickle: {e}. It will be regenerated.")
            if os.path.exists(token_path):
                os.remove(token_path)
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing credentials: {e}")
                creds = None
        
        if not creds:
            if not os.path.exists(credentials_path):
                messagebox.showerror("Google Sheets Error", 
                    "credentials.json not found. Please place it in the application directory.")
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                messagebox.showerror("Google Sheets Auth Error", f"Failed to authenticate: {e}")
                return None
        
        try:
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
        except IOError as e:
            print(f"Error saving new token: {e}")
    return creds

def create_or_update_sheet(spreadsheet_id, sheet_name, data):
    """Create or update a Google Sheet with data."""
    if not data:
        print(f"No data provided for sheet: {sheet_name}. Skipping update.")
        return False
    try:
        creds = get_google_sheets_credentials()
        if not creds:
            print("Failed to get Google Sheets credentials")
            return False
            
        service = build('sheets', 'v4', credentials=creds)
        
        headers = list(data[0].keys())
        values = [headers] + [[row.get(header, '') for header in headers] for row in data]
        
        body = {'values': values}
        
        # Check if the sheet exists
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        sheet_exists = any(s['properties']['title'] == sheet_name for s in sheets)

        if not sheet_exists:
            # Create the sheet if it doesn't exist
            add_sheet_request = {'addSheet': {'properties': {'title': sheet_name}}}
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [add_sheet_request]}
            ).execute()

        # Clear existing data before writing new data
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'"
        ).execute()

        # Update the sheet with new data
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A1",
            valueInputOption='RAW',
            body=body
        ).execute()
        
        print(f"Successfully updated Google Sheet: {sheet_name}")
        return True
        
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        return False


# --- Core Application Logic (API Calls & Scraping) ---
def get_spotify_access_token(session, client_id, client_secret):
    """Get the access token for the Spotify API using a session object."""
    try:
        url = "https://accounts.spotify.com/api/token"
        auth_str = f"{client_id}:{client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {"Authorization": f"Basic {b64_auth}"}
        data = {"grant_type": "client_credentials"}
        
        response = session.post(url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.RequestException as e:
        print(f"Failed to get Spotify access token: {e}")
        raise Exception("Could not get Spotify access token.") from e

def get_genius_song_credits_from_api(session, song_id, access_token):
    """Get song credits using Genius's internal API from a song ID."""
    if not song_id:
        return {}
        
    url = f"https://genius.com/api/songs/{song_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        song_data = response.json().get('response', {}).get('song', {})
        
        custom_performances = song_data.get('custom_performances', [])
        label_data = next((item for item in custom_performances if item.get('label') == 'Label'), None)
        copyright_data = next((item for item in custom_performances if item.get('label') == 'Copyright ©'), None)
        phono_copyright_data = next((item for item in custom_performances if item.get('label') == 'Phonographic Copyright ℗'), None)

        youtube_url = next((media.get('url') for media in song_data.get('media', []) if media.get('provider') == 'youtube'), None)
        producer_artists = song_data.get('producer_artists', [])
        
        return {
            "song_name": song_data.get('title'),
            "artist_name": song_data.get('primary_artist', {}).get('name'),
            "co-producers": ", ".join(p.get('name') for p in producer_artists) if producer_artists else None,
            "label": " & ".join(a.get('name') for a in label_data['artists']) if label_data else None,
            "copyright": " & ".join(a.get('name') for a in copyright_data['artists']) if copyright_data else None,
            "phonographic_copyright": " & ".join(a.get('name') for a in phono_copyright_data['artists']) if phono_copyright_data else None,
            "youtube_url": youtube_url
        }
    except requests.RequestException as e:
        print(f"Genius API request failed for song ID {song_id}: {e}")
        return {} # Return empty dict on failure

def get_youtube_view_count(session, video_url, api_key):
    """Get view count for a YouTube video using the YouTube Data API."""
    if not video_url or not api_key:
        return None
    try:
        if 'youtu.be' in video_url:
            video_id = video_url.split('/')[-1].split('?')[0]
        else:
            video_id = video_url.split('v=')[1].split('&')[0]
        
        url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={api_key}"
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        items = response.json().get('items', [])
        if items:
            return int(items[0]['statistics']['viewCount'])
    except (requests.RequestException, IndexError, KeyError, ValueError) as e:
        print(f"Failed to get YouTube views for {video_url}: {e}")
    return None

def get_artist_id_from_url(session, genius_url):
    """Extract Artist ID from a Genius artist page URL."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = session.get(genius_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Use BeautifulSoup to parse the page properly
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
    except requests.RequestException as e:
        print(f"Error getting artist ID from {genius_url}: {e}")
        return None

def get_songs_from_genius_producer_api(session, producer_url, limit, access_token):
    """Get a list of song IDs from a producer's Genius page using the API."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        artist_id = get_artist_id_from_url(session, producer_url)
        if not artist_id:
            raise ValueError("Could not extract Genius Artist ID from URL.")

        song_ids = []
        page = 1
        while True:
            if limit and len(song_ids) >= limit:
                break
            
            url = f"https://api.genius.com/artists/{artist_id}/songs"
            params = {"sort": "popularity", "per_page": 50, "page": page}
            
            response = session.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            songs = data.get('response', {}).get('songs', [])
            
            if not songs:
                break # No more songs
                
            song_ids.extend([song['id'] for song in songs])
            page += 1
            time.sleep(0.1) # Small delay to be nice to the API
        
        return song_ids[:limit] if limit else song_ids

    except (requests.RequestException, ValueError) as e:
        print(f"Error getting songs from Genius API: {e}")
        return []

def get_songs_from_spotify_playlist(session, playlist_url, limit, access_token):
    """Gets a list of songs (name, artist, track_id) from a Spotify playlist."""
    try:
        playlist_id = playlist_url.split('/playlist/')[1].split('?')[0]
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        songs = []
        while url:
            if limit and len(songs) >= limit:
                break
            response = session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('items', []):
                track = item.get('track')
                if track and track.get('name') and track.get('artists'):
                    songs.append({
                        'song_name': track['name'],
                        'artist_name': track['artists'][0]['name'],
                        'track_id': track.get('id')
                    })
            
            url = data.get('next')  # For pagination
        return songs[:limit] if limit else songs
    except (requests.RequestException, IndexError, KeyError) as e:
        print(f"Failed to get Spotify playlist songs: {e}")
        return []

def get_songs_from_spotify_album(session, album_url, limit, access_token):
    """Gets a list of songs (name, artist, track_id) from a Spotify album."""
    try:
        album_id = album_url.split('/album/')[1].split('?')[0]
        url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        songs = []
        while url:
            if limit and len(songs) >= limit:
                break
            response = session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for track in data.get('items', []):
                if track and track.get('name') and track.get('artists'):
                    songs.append({
                        'song_name': track['name'],
                        'artist_name': track['artists'][0]['name'],
                        'track_id': track.get('id')
                    })
            
            url = data.get('next')  # For pagination
        return songs[:limit] if limit else songs
    except (requests.RequestException, IndexError, KeyError) as e:
        print(f"Failed to get Spotify album songs: {e}")
        return []

def parse_manual_input(manual_list_text):
    """Parses manual 'Song - Artist' input into a list of dicts."""
    songs = []
    for line in manual_list_text.strip().splitlines():
        if "-" in line:
            parts = line.split("-", 1)
            songs.append({"song_name": parts[0].strip(), "artist_name": parts[1].strip()})
    return songs

def get_spotify_track_id(session, song_name, artist_name, access_token):
    """Search Spotify for a track and return the best match's ID and name."""
    try:
        query = f"track:{song_name} artist:{artist_name}"
        url = f"https://api.spotify.com/v1/search?q={requests.utils.quote(query)}&type=track&limit=5"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        items = response.json().get("tracks", {}).get("items", [])
        if not items:
            return None, None

        # Prefer exact matches, case-insensitive
        for item in items:
            if item['name'].lower() == song_name.lower():
                return item['id'], item['name']

        # Fallback to the first result
        return items[0]['id'], items[0]['name']
    except requests.RequestException as e:
        print(f"Spotify search failed for '{song_name}': {e}")
        return None, None

def get_rapidapi_stream_data(session, track_id, api_key):
    """Call the RapidAPI endpoint with thread-safe rate limiting."""
    global last_api_call_time
    
    with api_call_lock:
        current_time = time.time()
        time_since_last_call = current_time - last_api_call_time
        
        # Enforce rate limit (e.g., max 1 call per 1.1 seconds)
        wait_time = 1.1
        if time_since_last_call < wait_time:
            time.sleep(wait_time - time_since_last_call)
        
        # Update the last call time *after* the wait
        last_api_call_time = time.time()

    url = f"https://spotify-stream-count.p.rapidapi.com/v1/spotify/tracks/{track_id}/streams"
    headers = {
        "x-rapidapi-host": "spotify-stream-count.p.rapidapi.com",
        "x-rapidapi-key": api_key
    }
    params = {"trackId": track_id}

    try:
        response = session.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 200:
            return response.json()
        print(f"RapidAPI returned status {response.status_code} for track {track_id}")
        return None
    except requests.RequestException as e:
        print(f"RapidAPI request failed for track {track_id}: {e}")
        return None


def calculate_stream_stats(history_json):
    """Process historical stream data to calculate stats."""
    if not history_json or not isinstance(history_json, list) or len(history_json) == 0:
        return {"stream_count": None, "change_in_streams": None}
        
    stream_count = int(history_json[-1].get("streams", 0))
    change_in_streams = None
    if len(history_json) >= 2:
        try:
            # Look at the last two available data points for daily change
            latest_streams = int(history_json[-1].get("streams"))
            previous_streams = int(history_json[-2].get("streams"))
            change_in_streams = latest_streams - previous_streams
        except (ValueError, TypeError):
            change_in_streams = None # Handle case where stream data is not a number

    return {"stream_count": stream_count, "change_in_streams": change_in_streams}


# --- Main Application Class (GUI) ---
class PlacementTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Placement Tracker (Optimized)")
        self.root.geometry("800x650")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.gui_queue = queue.Queue()
        
        self.credentials = self.load_credentials()
        if not self.credentials:
            messagebox.showerror("Credentials Error", "Could not load credentials from secret.toml. Please check the file and console output.")
            self.root.destroy()
            return
            
        self.build_ui()
        self.process_queue() # Start listening for GUI updates

    def load_credentials(self):
        """Loads credentials from secret.toml."""
        config_path = get_resource_path('secret.toml')
        if not os.path.exists(config_path):
            return None
        try:
            with open(config_path, 'rb') as f:
                secrets = tomli.load(f)
                required = {'spotify_client_id', 'spotify_client_secret', 'genius_token', 'youtube_api_key', 'rapidapi_key'}
                if required.issubset(secrets):
                    return secrets
                else:
                    messagebox.showerror("Credentials Error", f"secret.toml is missing one or more required keys: {required - set(secrets)}")
                    return None
        except (tomli.TOMLDecodeError, IOError) as e:
            print(f"Error reading secret.toml: {e}")
        return None

    def build_ui(self):
        """Creates all the GUI widgets."""
        main_frame = tk.Frame(self.root, padx=20, pady=10)
        main_frame.pack(fill='both', expand=True)

        # --- Input Frame ---
        input_labelframe = ttk.LabelFrame(main_frame, text="Input Source", padding=10)
        input_labelframe.pack(fill='x', pady=5)

        tk.Label(input_labelframe, text="Genius/Spotify URL:").grid(row=0, column=0, sticky='w', pady=2)
        self.producer_url_entry = ttk.Entry(input_labelframe, width=60)
        self.producer_url_entry.grid(row=0, column=1, sticky='ew', padx=5)

        tk.Label(input_labelframe, text="Or Manual Input (Song - Artist per line):").grid(row=1, column=0, columnspan=2, sticky='w', pady=(10, 2))
        self.manual_input_text = tk.Text(input_labelframe, height=5, width=60)
        self.manual_input_text.grid(row=2, column=0, columnspan=2, sticky='ew')
        
        input_labelframe.grid_columnconfigure(1, weight=1)

        # --- Options Frame ---
        options_labelframe = ttk.LabelFrame(main_frame, text="Options", padding=10)
        options_labelframe.pack(fill='x', pady=5)

        tk.Label(options_labelframe, text="Concurrent Tasks:").grid(row=0, column=0, sticky='w')
        self.batch_size_var = tk.IntVar(value=10)
        ttk.Spinbox(options_labelframe, from_=1, to=25, width=5, textvariable=self.batch_size_var).grid(row=0, column=1, sticky='w', padx=5)

        tk.Label(options_labelframe, text="Song Limit:").grid(row=0, column=2, sticky='w', padx=(20, 0))
        self.limit_var = tk.IntVar(value=50)
        ttk.Spinbox(options_labelframe, from_=1, to=1000, width=7, textvariable=self.limit_var).grid(row=0, column=3, sticky='w', padx=5)
        self.limit_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_labelframe, text="Enable", variable=self.limit_enabled_var).grid(row=0, column=4, sticky='w')

        # --- Output Frame ---
        output_labelframe = ttk.LabelFrame(main_frame, text="Output", padding=10)
        output_labelframe.pack(fill='x', pady=5)
        
        default_dir = os.path.expanduser("~/Documents")
        self.directory_var = tk.StringVar(value=default_dir)
        tk.Label(output_labelframe, text="Save Directory:").grid(row=0, column=0, sticky='w', pady=2)
        ttk.Entry(output_labelframe, textvariable=self.directory_var, width=50).grid(row=0, column=1, sticky='ew', padx=5)
        ttk.Button(output_labelframe, text="Browse", command=lambda: self.directory_var.set(filedialog.askdirectory(initialdir=default_dir))).grid(row=0, column=2)

        tk.Label(output_labelframe, text="Base Filename:").grid(row=1, column=0, sticky='w', pady=2)
        self.filename_entry = ttk.Entry(output_labelframe, width=40)
        self.filename_entry.grid(row=1, column=1, sticky='w', padx=5)
        self.filename_entry.insert(0, f"placement_data_{datetime.date.today()}")

        self.export_to_sheets_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(output_labelframe, text="Export to Google Sheets", variable=self.export_to_sheets_var).grid(row=2, column=0, columnspan=3, sticky='w', pady=(10,0))
        
        tk.Label(output_labelframe, text="Spreadsheet ID:").grid(row=3, column=0, sticky='w', pady=2)
        self.spreadsheet_id_var = tk.StringVar()
        ttk.Entry(output_labelframe, textvariable=self.spreadsheet_id_var, width=50).grid(row=3, column=1, columnspan=2, sticky='ew', padx=5)
        
        tk.Label(output_labelframe, text="Sheet Name:").grid(row=4, column=0, sticky='w', pady=2)
        self.sheet_name_var = tk.StringVar(value=datetime.date.today().strftime("%Y-%m-%d"))
        ttk.Entry(output_labelframe, textvariable=self.sheet_name_var, width=20).grid(row=4, column=1, sticky='w', padx=5)
        
        output_labelframe.grid_columnconfigure(1, weight=1)

        # --- Control & Progress Frame ---
        progress_labelframe = ttk.LabelFrame(main_frame, text="Progress", padding=10)
        progress_labelframe.pack(fill='both', expand=True, pady=5)

        self.start_button = ttk.Button(progress_labelframe, text="Start Processing", command=self.start_processing)
        self.start_button.pack(pady=5)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_labelframe, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', pady=5)

        self.log_text = tk.Text(progress_labelframe, height=10, width=80, state='disabled')
        self.log_text.pack(fill='both', expand=True, pady=5)
        self.log_text.tag_configure('error', foreground='red')
        self.log_text.tag_configure('success', foreground='green')

    def log_message(self, message, level="info"):
        """Inserts a message into the log text widget."""
        self.log_text.configure(state='normal')
        if level in ('error', 'success'):
            self.log_text.insert(tk.END, message + "\n", level)
        else:
            self.log_text.insert(tk.END, message + "\n")
        self.log_text.configure(state='disabled')
        self.log_text.see(tk.END)

    def process_queue(self):
        """Processes messages from the GUI queue to update the UI safely."""
        try:
            while not self.gui_queue.empty():
                msg_type, value, *extra = self.gui_queue.get_nowait()
                
                if msg_type == "progress":
                    self.progress_var.set(value)
                elif msg_type == "log":
                    level = extra[0] if extra else "info"
                    self.log_message(value, level)
                elif msg_type == "processing_done":
                    self.start_button.config(state='normal')
                    self.log_message(value, "success")
                    messagebox.showinfo("Success", value)
                elif msg_type == "processing_error":
                    self.start_button.config(state='normal')
                    self.log_message(value, "error")
                    messagebox.showerror("Error", value)
        finally:
            self.root.after(100, self.process_queue)

    def start_processing(self):
        """Validates inputs and starts the data processing in a new thread."""
        producer_url = self.producer_url_entry.get().strip()
        manual_input = self.manual_input_text.get("1.0", tk.END).strip()
        
        if not (producer_url or manual_input):
            return messagebox.showerror("Input Error", "Please provide a Producer URL or manual song input.")
        if producer_url and manual_input:
            return messagebox.showerror("Input Error", "Please provide either a URL or Manual Input, not both.")

        params = {
            'producer_url': producer_url,
            'manual_input': manual_input,
            'save_dir': self.directory_var.get().strip(),
            'file_name': self.filename_entry.get().strip(),
            'max_workers': self.batch_size_var.get(),
            'limit': self.limit_var.get() if self.limit_enabled_var.get() else None,
            'credentials': self.credentials,
            'export_to_sheets': self.export_to_sheets_var.get(),
            'spreadsheet_id': self.spreadsheet_id_var.get().strip(),
            'sheet_name': self.sheet_name_var.get().strip(),
            'gui_queue': self.gui_queue
        }
        
        self.start_button.config(state='disabled')
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')
        self.progress_var.set(0)

        threading.Thread(target=self.processing_worker, args=(params,), daemon=True).start()

    def processing_worker(self, params):
        """The main worker function that runs in a separate thread."""
        q = params['gui_queue']
        try:
            with requests.Session() as session:
                q.put(("log", "Authenticating with Spotify..."))
                spotify_token = get_spotify_access_token(session, params['credentials']['spotify_client_id'], params['credentials']['spotify_client_secret'])
                genius_token = params['credentials']['genius_token']
                youtube_key = params['credentials']['youtube_api_key']
                rapidapi_key = params['credentials']['rapidapi_key']
                q.put(("log", "Authentication successful.", "success"))

                # Step 1: Obtain initial list of songs/song IDs
                q.put(("log", "Fetching initial song list..."))
                initial_song_list = self._get_initial_song_list(session, params, spotify_token, genius_token, rapidapi_key)
                if not initial_song_list:
                    raise ValueError("No songs found from the provided input.")
                q.put(("log", f"Found {len(initial_song_list)} songs to process.", "success"))
                q.put(("progress", 10))
                
                # Step 2: Process all songs concurrently
                results = []
                total = len(initial_song_list)
                
                with ThreadPoolExecutor(max_workers=params['max_workers']) as executor:
                    # Create a future for each song to be processed
                    future_to_song = {
                        executor.submit(
                            self._process_single_song, 
                            session, song_data, spotify_token, genius_token, youtube_key, rapidapi_key
                        ): song_data for song_data in initial_song_list
                    }

                    for i, future in enumerate(as_completed(future_to_song)):
                        try:
                            result = future.result()
                            if result:
                                results.append(result)
                        except Exception as exc:
                            song_info = future_to_song[future]
                            q.put(("log", f"Error processing '{song_info.get('song_name')}': {exc}", "error"))
                        
                        # Update progress
                        progress = 10 + (i + 1) * 80.0 / total
                        q.put(("progress", progress))
                        q.put(("log", f"Processed {i+1}/{total} songs..."))

                q.put(("progress", 90))
                q.put(("log", f"Finished processing. Found details for {len(results)} songs."))

                # Step 3: Export results
                if results:
                    self.export_results(results, params)
                    q.put(("progress", 100))
                    q.put(("processing_done", f"Success! Exported {len(results)} songs."))
                else:
                    q.put(("processing_error", "Processing finished, but no data could be exported."))

        except Exception as e:
            print(f"Error in processing worker: {e}")
            q.put(("processing_error", f"An unexpected error occurred: {e}"))

    def _get_initial_song_list(self, session, params, spotify_token, genius_token, rapidapi_key):
        """Helper to determine input source and fetch the initial song list."""
        if params['producer_url']:
            if 'genius.com' in params['producer_url']:
                song_ids = get_songs_from_genius_producer_api(session, params['producer_url'], params['limit'], genius_token)
                # Return list of dicts with just the ID to be processed later
                return [{'song_id': sid} for sid in song_ids]
            elif 'spotify.com/playlist/' in params['producer_url']:
                return get_songs_from_spotify_playlist(session, params['producer_url'], params['limit'], spotify_token)
            elif 'spotify.com/album/' in params['producer_url']:
                return get_songs_from_spotify_album(session, params['producer_url'], params['limit'], spotify_token)
        elif params['manual_input']:
            return parse_manual_input(params['manual_input'])
        return []

    def _process_single_song(self, session, song_data, spotify_token, genius_token, youtube_key, rapidapi_key):
        """
        Processes a single song: fetches all its data from various APIs.
        This function is designed to be run in a thread.
        `song_data` is a dictionary that must contain either 'song_id' (from Genius)
        or both 'song_name' and 'artist_name'.
        """
        # --- Get base song info (credits, artist, title) ---
        credits = {}
        if 'song_id' in song_data:
            credits = get_genius_song_credits_from_api(session, song_data['song_id'], genius_token)
        elif 'song_name' in song_data and 'artist_name' in song_data:
            # For manual input, we need to search for the song ID first
            song_name = song_data['song_name']
            artist_name = song_data['artist_name']
            
            # Search for the song ID using Genius search API
            search_url = f"https://api.genius.com/search?q={requests.utils.quote(f'{song_name} {artist_name}')}"
            headers = {"Authorization": f"Bearer {genius_token}"}
            try:
                response = session.get(search_url, headers=headers, timeout=10)
                response.raise_for_status()
                songs = response.json().get('response', {}).get('hits', [])
                song_id = None
                for song in songs:
                    if song.get('result', {}).get('primary_artist', {}).get('name').lower() == artist_name.lower() \
                        and song.get('result', {}).get('title').lower() == song_name.lower():
                        song_id = song.get('result', {}).get('id')
                        break
                
                if song_id:
                    credits = get_genius_song_credits_from_api(session, song_id, genius_token)
                else:
                    # Fallback: use the provided names
                    credits = {'song_name': song_name, 'artist_name': artist_name}
            except:
                # Fallback: use the provided names
                credits = {'song_name': song_name, 'artist_name': artist_name}
        
        if not credits.get('song_name'):
             # If we couldn't get credits, we can't proceed with this song
            return None

        song_name = credits['song_name']
        artist_name = credits['artist_name']

        # --- Get Spotify Track ID and Actual Name ---
        track_id, actual_track_name = song_data.get('track_id'), song_name
        if not track_id:
            track_id, actual_track_name = get_spotify_track_id(session, song_name, artist_name, spotify_token)
        
        # --- Get Stream Data ---
        stream_stats = {"stream_count": None, "change_in_streams": None}
        if track_id:
            stream_data = get_rapidapi_stream_data(session, track_id, rapidapi_key)
            if stream_data:
                stream_stats = calculate_stream_stats(stream_data)
        
        # --- Get YouTube Views ---
        youtube_views = None
        if credits.get('youtube_url'):
            youtube_views = get_youtube_view_count(session, credits['youtube_url'], youtube_key)

        # --- Assemble final result ---
        return {
            "Artist & Title": f"{artist_name} - {song_name}",
            "Co-Producers": credits.get("co-producers"),
            "Actual Track Name": actual_track_name,
            "Total Spotify Streams": stream_stats["stream_count"],
            "Daily Spotify Streams": stream_stats["change_in_streams"],
            "Label": credits.get("label"),
            "Phonographic_copyright": credits.get("phonographic_copyright"),
            "Copyright": credits.get("copyright"),
            "YouTube URL": credits.get("youtube_url"),
            "YouTube Views": youtube_views,
        }

    def export_results(self, data, params):
        """Writes data to CSV and optionally Google Sheets."""
        q = params['gui_queue']
        filepath = os.path.join(params['save_dir'], f"{params['file_name']}.csv")

        # Format data for output
        fieldnames_raw = ["Artist & Title", "Co-Producers", "Actual Track Name", "Label", "Phonographic_copyright", "Copyright", "Total Spotify Streams", "Daily Spotify Streams", "YouTube URL", "YouTube Views"]
        fieldnames_simple = ["Artist & Title", "Co-Producers", "Label", "Total Spotify Streams", "Daily Spotify Streams", "YouTube Views"]
        
        formatted_data = []
        for item in data:
            formatted_item = {k: item.get(k) for k in fieldnames_raw}
            for field in ['Total Spotify Streams', 'Daily Spotify Streams', 'YouTube Views']:
                if isinstance(item.get(field), int):
                    formatted_item[field] = f"{item[field]:,}" # Add commas
                elif item.get(field) is None:
                     formatted_item[field] = "" # Use empty string for None
            formatted_data.append(formatted_item)
            
        simplified_data = [{k: item.get(k, '') for k in fieldnames_simple} for item in formatted_data]

        # Write CSV files
        try:
            # Simplified CSV
            simplified_path = filepath.replace(".csv", " - Simplified.csv")
            with open(simplified_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames_simple)
                writer.writeheader()
                writer.writerows(simplified_data)
            q.put(("log", f"Saved simplified CSV to {simplified_path}", "success"))
            
            # Raw CSV
            raw_path = filepath.replace(".csv", " - Raw.csv")
            with open(raw_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames_raw)
                writer.writeheader()
                writer.writerows(formatted_data)
            q.put(("log", f"Saved raw CSV to {raw_path}", "success"))
        except IOError as e:
            q.put(("log", f"Error writing CSV file: {e}", "error"))

        # Export to Google Sheets
        if params['export_to_sheets'] and params['spreadsheet_id'] and params['sheet_name']:
            q.put(("log", "Exporting to Google Sheets..."))
            # Simplified Sheet
            if create_or_update_sheet(params['spreadsheet_id'], f"{params['sheet_name']} - Simplified", simplified_data):
                q.put(("log", "Successfully exported simplified data to Google Sheets.", "success"))
            else:
                q.put(("log", "Failed to export simplified data to Google Sheets.", "error"))
            
            # Raw Sheet
            if create_or_update_sheet(params['spreadsheet_id'], f"{params['sheet_name']} - Raw", formatted_data):
                q.put(("log", "Successfully exported raw data to Google Sheets.", "success"))
            else:
                q.put(("log", "Failed to export raw data to Google Sheets.", "error"))

    def on_closing(self):
        """Handles application shutdown."""
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.root.destroy()

# --- Main Execution ---
def main():
    """Main function to set up and run the application."""
    # This allows Ctrl+C to close the app from the terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    root = tk.Tk()
    app = PlacementTrackerApp(root)
    # The app will only run if credentials load successfully
    if hasattr(app, 'credentials') and app.credentials:
        root.mainloop()

if __name__ == "__main__":
    main()
