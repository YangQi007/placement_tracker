# Placement Tracker

A Python application that helps track music placements and their performance metrics across various platforms.

## Features

- Track music placements from Spotify and Genius
- Get detailed information about songs including:
  - Producer credits
  - Label information
  - Copyright details
  - Spotify stream counts
  - YouTube view counts
- Export data to CSV format
- Support for both manual input and URL-based processing
- Multi-platform support (macOS and Windows)

## Requirements

- Python 3.7+
- Required Python packages (install via pip):
  ```
  selenium
  webdriver_manager
  undetected_chromedriver
  tomli
  beautifulsoup4
  requests
  ```

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/placement_tracker.git
   cd placement_tracker
   ```

2. Create a `secret.toml` file with your API credentials:
   ```toml
   spotify_client_id = "your_spotify_client_id"
   spotify_client_secret = "your_spotify_client_secret"
   genius_token = "your_genius_token"
   youtube_api_key = "your_youtube_api_key"
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Run the application:
   ```bash
   python placement_tracker.py
   ```

2. Enter either:
   - A Genius/Spotify producer URL
   - Or manually enter song-artist pairs

3. Select output options and click "Start Processing"

4. The results will be saved as CSV files in your chosen directory

## Building

### macOS
```bash
pyinstaller --clean PlacementTracker.spec
```

### Windows
```bash
python build.py
```

## License

[Your chosen license]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 