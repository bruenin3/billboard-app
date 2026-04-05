from flask import Flask, request, redirect, session
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
from bs4 import BeautifulSoup
import os
import time

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT_URI = os.environ["REDIRECT_URI"]

SCOPE = "playlist-modify-private playlist-modify-public user-read-private"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, ".spotifycache")


def get_spotify_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=CACHE_PATH,
        show_dialog=True
    )


def get_billboard_titles(date: str):
    url = f"https://www.billboard.com/charts/hot-100/{date}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    songs = []

    selectors = [
        "li ul li h3",
        "h3#title-of-a-story",
        "li.o-chart-results-list__item h3",
    ]

    for selector in selectors:
        found = []
        for tag in soup.select(selector):
            text = tag.get_text(strip=True)
            if text:
                found.append(text)

        found = [x for x in found if len(x) > 1]

        if len(found) >= 50:
            songs = found[:100]
            break

    if not songs:
        raise ValueError("Could not parse Billboard chart page.")

    return songs


@app.route("/")
def home():
    return """
        <h2>Create Billboard Playlist</h2>
        <form action="/login">
            Enter date (YYYY-MM-DD): <input type="text" 
    name="date" 
    placeholder="e.g. 2001-09-11"
    required
>
            <button type="submit">Create Playlist</button>
        </form>
    """


@app.route("/login")
def login():
    date = request.args.get("date", "").strip()

    if not date:
        return "Please enter a date in YYYY-MM-DD format.", 400

    session["date"] = date
    auth_url = get_spotify_oauth().get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"Spotify authorization failed: {error}", 400

    if not code:
        return "Missing Spotify authorization code.", 400

    date = session.get("date")
    if not date:
        return "No date found in session. Go back and start again.", 400

    sp_oauth = get_spotify_oauth()

    try:
        token_info = sp_oauth.get_access_token(code, as_dict=True)
        print("TOKEN INFO:", token_info)
        print("TOKEN SCOPE:", token_info.get("scope"))
        access_token = token_info["access_token"]
    except Exception as e:
        return f"Failed to get Spotify access token: {e}", 500

sp = spotipy.Spotify(
    auth=access_token,
    requests_timeout=5,
    retries=0
)
    try:
        me = sp.current_user()
        print("CURRENT USER:", me)
        print("USER PRODUCT:", me.get("product"))
        print("USER COUNTRY:", me.get("country"))
    except Exception as e:
        return f"Failed to fetch current Spotify user: {e}", 500

    try:
        song_titles = get_billboard_titles(date)
    except requests.HTTPError as e:
        return f"Billboard request failed: {e}", 500
    except Exception as e:
        return f"Could not parse Billboard chart: {e}", 500

    uris = []
    missed = []

    for title in song_titles[:10]:
    try:
        result = sp.search(q=title, type="track", limit=1)
        items = result["tracks"]["items"]

        if items:
            uris.append(items[0]["uri"])
        else:
            missed.append(title)

    except Exception as e:
        print(f"Search failed for {title}: {e}")
        break  # 🔥 STOP if rate limited

    print("USER ID:", me.get("id"))
    print("DATE:", date)
    print("URI COUNT:", len(uris))
    print("MISSED COUNT:", len(missed))

    try:
        playlist = sp.current_user_playlist_create(
            name=f"Billboard Hot 100 - {date}",
            public=False,
            description=f"Billboard Hot 100 for {date}"
        )
        print("PLAYLIST RESPONSE:", playlist)
    except Exception as e:
        return f"Playlist creation failed: {e}", 500

    try:
        if uris:
            sp.playlist_add_items(playlist["id"], uris)
    except Exception as e:
        return f"Playlist was created, but adding songs failed: {e}", 500

    missed_html = ""
    if missed:
        missed_list = "".join(f"<li>{song}</li>" for song in missed[:20])
        extra = ""
        if len(missed) > 20:
            extra = f"<p>...and {len(missed) - 20} more missed songs.</p>"

        missed_html = f"""
            <h4>Some songs were not matched:</h4>
            <ul>{missed_list}</ul>
            {extra}
        """

    return f"""
        <h3>Playlist created!</h3>
        <p>Added {len(uris)} songs.</p>
        <p>Missed {len(missed)} songs.</p>
        <p><a href="{playlist['external_urls']['spotify']}" target="_blank">Open playlist</a></p>
        {missed_html}
    """


if __name__ == "__main__":
    app.run(debug=True)
