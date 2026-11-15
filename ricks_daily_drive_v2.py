"""Rick's Daily Drive v2: maak een leesbare 20-minuten muziekmix.

Alleen lezen: dit script verandert GEEN Spotify-playlists.
Installeer: python -m pip install requests
Spotify redirect URI: http://127.0.0.1:8888/callback
"""
import base64
import hashlib
import json
import random
import secrets
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

CLIENT_ID = "0d9c64268fba43deb2586c7b70805031"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
API = "https://api.spotify.com/v1"
TARGET_SECONDS = 20 * 60
# Exact de 14 gekozen bronnen. ID's zijn afkomstig uit Ricks eerdere test.
SOURCE_PLAYLISTS = {
    "El Gato's Playlist": "4WCthEObxUgGWfUeh1KJax",
    "Playlistje wel💯": "7yt0MQIwetbqbr1MguOyrO",
    "Mijn Shazam-nummers": "3taNBnkM4ebN16flhH1Llc",
    "Lekker hiphop": "7gzjsAS1GD3p5IctGytRWB",
    "Country blues": "1wwJxJiQ9SHqOyD27hFtqb",
    "Kleine": "3tncdvcyVlV6Y7cUoWECbF",
    "PASS DE AUX": "4QZ4F2Yxc6RLx7ybP0Ozn4",
    "Fissa🎉": "2YuuRsPXKbLq8vNmYzCosx",
    "Feestje": "4Uzdn0indRQ3mFf7oIaUM0",
    "LekkerMannnn": "5LAh0h0vFRSmbQiVSP4CTA",
    "Gwn goeie": "7Dh7ddCRIB3Xq1G2N6PbOq",
    "Español claro que si🇪🇦": "7t1O5c82LoIBkh4l0nShkm",
    "Vrimibo": "2dTobFZotx4AmxFLRi54Rk",
    "Cafe de Monico Rembrandtplein": "0tfqULA1fry3Y6AE74hrQl",
}


def spotify_login():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(24)
    result = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            result["code"] = params.get("code", [None])[0]
            result["state"] = params.get("state", [None])[0]
            result["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Spotify-login ontvangen. Dit tabblad mag dicht.".encode("utf-8"))

        def log_message(self, format, *args):
            pass

    params = {
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "state": state, "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    try:
        server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    except OSError as exc:
        raise RuntimeError("Poort 8888 is bezet. Sluit andere Spotify-scripts.") from exc
    server.timeout = 180
    print("Spotify-login openen in je browser...")
    webbrowser.open("https://accounts.spotify.com/authorize?" + urlencode(params))
    try:
        server.handle_request()
    finally:
        server.server_close()
    if result.get("error"):
        raise RuntimeError("Spotify-toestemming geweigerd: " + result["error"])
    if result.get("state") != state or not result.get("code"):
        raise RuntimeError("Spotify-login niet afgerond binnen 3 minuten.")
    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"client_id": CLIENT_ID, "grant_type": "authorization_code",
              "code": result["code"], "redirect_uri": REDIRECT_URI,
              "code_verifier": verifier}, timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Tokenaanvraag mislukt (HTTP {response.status_code}): {response.text}")
    return response.json()["access_token"]


def spotify_get(url, token, params=None):
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                            params=params, timeout=30)
    if not response.ok:
        raise RuntimeError(f"Spotify HTTP {response.status_code} bij {url}: {response.text}")
    return response.json()


def get_tracks(playlist_id, token):
    # Spotify's huidige playlist-items endpoint (niet het oude /tracks).
    url = f"{API}/playlists/{playlist_id}/items"
    params = {"limit": 50, "offset": 0}
    tracks = []
    while url:
        data = spotify_get(url, token, params)
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            track = item.get("item") or item.get("track")
            if not isinstance(track, dict) or track.get("type") != "track":
                continue
            if track.get("is_local") or not track.get("id"):
                continue
            duration = track.get("duration_ms")
            artists = track.get("artists") or []
            if not isinstance(duration, int) or duration <= 0 or not artists:
                continue
            tracks.append({
                "id": track["id"], "uri": track.get("uri") or f"spotify:track:{track['id']}",
                "title": track.get("name") or "Onbekend",
                "artist": ", ".join(a.get("name", "?") for a in artists if isinstance(a, dict)),
                "artist_id": artists[0].get("id") or artists[0].get("name", "") if isinstance(artists[0], dict) else "",
                "seconds": round(duration / 1000),
            })
        url = data.get("next")
        params = None
    return tracks


def make_mix(all_tracks, target=TARGET_SECONDS):
    # Iedere track slechts eenmaal; kleine playlists krijgen geen kunstmatig groter gewicht.
    unique = {t["id"]: t for t in all_tracks}
    pool = list(unique.values())
    random.shuffle(pool)
    chosen = []
    used_artists = set()
    remaining = target
    # Eerst proberen dichtbij 20 minuten te komen zonder artiesten te herhalen.
    while pool:
        candidates = [t for t in pool if t["artist_id"] not in used_artists]
        if not candidates:
            candidates = pool
        fits = [t for t in candidates if t["seconds"] <= remaining + 35]
        if not fits:
            break
        # Kies een willekeurig nummer uit een aantal goede duurmatches.
        fits.sort(key=lambda t: abs(remaining - t["seconds"]))
        pick = random.choice(fits[:min(30, len(fits))])
        chosen.append(pick)
        used_artists.add(pick["artist_id"])
        pool.remove(pick)
        remaining -= pick["seconds"]
        if remaining <= 0:
            break
    return chosen


def main():
    token = spotify_login()
    me = spotify_get(f"{API}/me", token)
    print("\nVerbonden met:", me.get("display_name") or me.get("id"))
    print("\nMuziek ophalen uit 14 geselecteerde playlists...")
    all_tracks = []
    for name, playlist_id in SOURCE_PLAYLISTS.items():
        try:
            tracks = get_tracks(playlist_id, token)
            all_tracks.extend(tracks)
            print(f"  {name}: {len(tracks)} nummers")
        except (RuntimeError, requests.RequestException) as exc:
            print(f"  WAARSCHUWING - {name}: {exc}")
    if not all_tracks:
        print("\nGeen nummers opgehaald. Stuur de waarschuwingen hierboven door.")
        return
    mix = make_mix(all_tracks)
    if not mix:
        print("Geen geschikte nummers voor de mix gevonden.")
        return
    total = sum(t["seconds"] for t in mix)
    print(f"\nRICK'S DAILY DRIVE - TESTMIX ({total // 60}:{total % 60:02d})")
    for i, track in enumerate(mix, 1):
        print(f"{i:2}. {track['artist']} - {track['title']} ({track['seconds']//60}:{track['seconds']%60:02d})")
    output = Path(__file__).resolve().parent / "daily_drive_testmix.json"
    output.write_text(json.dumps({
        "gemaakt_op": datetime.now().isoformat(timespec="seconds"),
        "duur_seconden": total, "spotify_uris": [t["uri"] for t in mix],
        "nummers": mix,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTestmix opgeslagen: {output.name}")
    print("Er is niets gewijzigd in Spotify. Nog geen podcasts of nieuwe ontdekkingen.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, requests.RequestException, ValueError, OSError) as exc:
        print("\nFOUT:", exc)
