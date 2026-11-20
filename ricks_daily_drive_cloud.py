"""Ricky's Daily Drive: seven-day Spotify runner with persistent episode history."""
import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import ricks_daily_drive_v2 as base
import ricks_daily_drive_v5_weetjes as drive

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'daily_drive_shows.json'
HISTORY = ROOT / 'daily_drive_podcast_historie.json'
TRIVIA_HISTORY = ROOT / 'daily_drive_weetjes_historie.json'
ROTATION = ('Dutch Dragons', 'Lotgenoten', 'Doorzetters')
MAIN = ('Vik en Gert', 'ADHAZES', 'De Beste Sales Podcast', 'Cyberhelden',
        'Borrelpraat', 'Geuze & Gorgels', 'KJEG')
# Stable rotation: continues across Sunday/Monday, without repeating the show.
ROTATION_START = datetime(2026, 11, 16, tzinfo=ZoneInfo('Europe/Amsterdam')).date()


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def token_from_refresh():
    refresh = os.environ.get('SPOTIFY_REFRESH_TOKEN', '').strip()
    if not refresh:
        raise RuntimeError('GitHub Secret SPOTIFY_REFRESH_TOKEN ontbreekt.')
    response = requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'refresh_token', 'refresh_token': refresh,
        'client_id': base.CLIENT_ID,
    }, timeout=30)
    if not response.ok:
        raise RuntimeError(f'Spotify tokenfout HTTP {response.status_code}')
    data = response.json()
    if data.get('refresh_token') and data['refresh_token'] != refresh:
        raise RuntimeError('Spotify heeft refresh token geroteerd; GitHub Secret moet worden bijgewerkt.')
    return data['access_token']


def all_episodes(show_id, token, max_pages=10):
    """Fetch up to 500 recent episodes, newest first; never invent popularity metrics."""
    found = []
    url = f'/shows/{show_id}/episodes'
    for page in range(max_pages):
        data = drive.api('GET', url, token, params={'limit': 50, 'offset': page * 50, 'market': 'NL'})
        batch = [e for e in data.get('items', []) if e and e.get('id')]
        found.extend(batch)
        if not data.get('next') or not batch:
            break
    return sorted(found, key=lambda e: (e.get('release_date', ''), e.get('id', '')), reverse=True)


def unused_episode(name, config, token, seen, reserved):
    sid = config.get(name)
    if not sid:
        raise RuntimeError(f'Podcast-ID ontbreekt voor {name} in daily_drive_shows.json')
    choices = all_episodes(sid, token)
    fresh = [e for e in choices if e['id'] not in seen and e['id'] not in reserved]
    if not fresh:
        print(f'Geen ongebruikte aflevering voor {name}; onderdeel overgeslagen.')
        return None
    # Latest unused episode is the only reliable automatic preference;
    # Spotify does not expose per-episode popularity or complete listening history.
    episode = fresh[0]
    reserved.add(episode['id'])
    print(f'{name}: {episode.get("name")} ({episode.get("release_date")})')
    return episode


def regular_episode(name, config, token):
    sid = config.get(name)
    if not sid:
        raise RuntimeError(f'Podcast-ID ontbreekt voor {name} in daily_drive_shows.json')
    return drive.latest_episode(sid, token, name)


def add(items, episode, name):
    if episode:
        drive.add_episode(items, episode, name)


def update_playlist(token, me, items):
    if not items:
        raise RuntimeError('Geen playlist-items; Spotify niet aangepast.')
    existing = None
    offset = 0
    while True:
        page = drive.api('GET', '/me/playlists', token, params={'limit': 50, 'offset': offset})
        for playlist in page.get('items', []):
            if playlist and playlist.get('name') == drive.PLAYLIST_NAME and playlist.get('owner', {}).get('id') == me['id']:
                existing = playlist
                break
        if existing or not page.get('next'):
            break
        offset += len(page.get('items', []))
    if existing:
        pid = existing['id']
    else:
        created = drive.api('POST', '/me/playlists', token, json={
            'name': drive.PLAYLIST_NAME, 'description': "Rick's persoonlijke Daily Drive", 'public': False})
        pid = created['id']
    uris = [item['uri'] for item in items]
    for start in range(0, len(uris), 100):
        drive.api('PUT' if start == 0 else 'POST', f'/playlists/{pid}/items', token,
                  json={'uris': uris[start:start + 100]})
    print('Playlist bijgewerkt:', f'https://open.spotify.com/playlist/{pid}', '| items:', len(uris))


def main():
    now = datetime.now(ZoneInfo('Europe/Amsterdam'))
    day = now.weekday()
    config = load_json(CONFIG, {})
    rotation_name = ROTATION[(now.date() - ROTATION_START).days % len(ROTATION)]
    # These are the exact Spotify show names/IDs that must be configured.
    required = {'NU.nl', MAIN[day], rotation_name, 'weetjes podcast'}
    if day < 5:
        required.add('Vandaag Inside')
    if day == 1:
        required.add('KJEG')
    if day == 6:
        required.add('Ajax Life Podcast')
    missing = sorted(name for name in required if not config.get(name))
    if missing:
        raise RuntimeError('Voeg eerst deze podcast-ID(s) toe aan daily_drive_shows.json: ' + ', '.join(missing))

    token = token_from_refresh()
    me = drive.api('GET', '/me', token)
    print('Dag:', now.date(), '| Hoofdpodcast:', MAIN[day], '| Rotatie:', rotation_name)
    tracks = []
    for name, pid in drive.SOURCES.items():
        try:
            tracks.extend(base.get_tracks(pid, token))
        except (RuntimeError, requests.RequestException) as exc:
            print('Muziekbron overgeslagen:', name, str(exc)[:120])
    if not tracks:
        raise RuntimeError('Geen muzieknummers gevonden; Spotify niet aangepast.')

    history = load_json(HISTORY, {'used_episode_ids': []})
    seen = set(history.get('used_episode_ids', []))
    reserved = set()
    # We track podcast episodes selected by this automation, not Spotify listening status.
    main_episode = unused_episode(MAIN[day], config, token, seen, reserved)
    rotating_episode = unused_episode(rotation_name, config, token, seen, reserved)
    extra = []
    if day == 1:
        extra.append(('KJEG', unused_episode('KJEG', config, token, seen, reserved)))
    if day == 6:
        extra.append(('Ajax Life Podcast', unused_episode('Ajax Life Podcast', config, token, seen, reserved)))
    news = regular_episode('NU.nl', config, token)
    if not news:
        raise RuntimeError('Geen NU.nl-aflevering; Spotify niet aangepast.')
    vi = regular_episode('Vandaag Inside', config, token) if day < 5 else None
    if day < 5 and not vi:
        raise RuntimeError('Geen Vandaag Inside-aflevering; Spotify niet aangepast.')
    trivia = drive.choose_trivia_episode(config['weetjes podcast'], token)
    if trivia:
        trivia_seen = set(load_json(TRIVIA_HISTORY, []))
        if trivia['id'] in trivia_seen:
            # The legacy chooser can recycle episodes; never do so here.
            fresh = [e for e in all_episodes(config['weetjes podcast'], token)
                     if e['id'] not in trivia_seen and 10*60_000 <= e.get('duration_ms', 0) <= 25*60_000]
            trivia = fresh[0] if fresh else None
            if trivia is None:
                print('Alle geschikte weetjesafleveringen gebruikt; overslaan.')

    used_tracks = set()
    items = []
    add(items, news, 'NU.nl nieuwsbulletin')
    drive.add_music(items, drive.block(tracks, used_tracks, 20), 'Muziekblok 1')
    add(items, main_episode, MAIN[day])
    drive.add_music(items, drive.block(tracks, used_tracks, 30, party=(day == 4)), 'Muziekblok 2')
    if vi:
        add(items, vi, 'Vandaag Inside')
    drive.add_music(items, drive.block(tracks, used_tracks, 30), 'Muziekblok 3')
    add(items, trivia, 'Dagelijks weetje')
    add(items, rotating_episode, rotation_name)
    drive.add_music(items, drive.block(tracks, used_tracks, 30), 'Muziekblok 4')
    for name, episode in extra:
        add(items, episode, name)
    update_playlist(token, me, items)

    # Commit history only after Spotify confirms successful update.
    history['used_episode_ids'] = sorted(seen | reserved)
    save_json(HISTORY, history)
    if trivia:
        old = load_json(TRIVIA_HISTORY, [])
        if trivia['id'] not in old:
            old.append(trivia['id'])
        save_json(TRIVIA_HISTORY, old)
    print('KLAAR: podcastgeschiedenis opgeslagen.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FOUT:', exc, file=sys.stderr)
        sys.exit(1)
