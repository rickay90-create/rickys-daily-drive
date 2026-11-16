"""Headless runner for Rick's Daily Drive. Requires GitHub Actions secret."""
import builtins
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import ricks_daily_drive_v2 as base
import ricks_daily_drive_v5_weetjes as drive

ROOT = Path(__file__).resolve().parent
CLIENT_ID = base.CLIENT_ID
REQUIRED = ['NU.nl', 'Vik en Gert', 'ADHAZES', 'De Beste Sales Podcast',
            'Cyberhelden', 'Borrelpraat', 'Vandaag Inside', 'Dutch Dragons', 'weetjes podcast']


def refresh_access_token():
    refresh = os.environ.get('SPOTIFY_REFRESH_TOKEN', '').strip()
    if not refresh:
        raise RuntimeError('SPOTIFY_REFRESH_TOKEN ontbreekt in GitHub Actions Secrets.')
    response = requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': CLIENT_ID,
    }, timeout=30)
 if not response.ok:
    try:
        error_data = response.json()
    except ValueError:
        error_data = {}

    error = error_data.get('error', 'onbekend')
    description = error_data.get('error_description', 'geen verdere informatie')

    raise RuntimeError(
        f'Spotify tokenvernieuwing mislukt: HTTP {response.status_code} '
        f'({error}): {description}'
    )
    data = response.json()
    if data.get('refresh_token') and data['refresh_token'] != refresh:
        # Never print token. Rotation requires updating GitHub secret manually.
        print('WAARSCHUWING: Spotify heeft het refresh token geroteerd; werk GitHub Secret bij.')
        raise RuntimeError('Refresh token geroteerd: veilig gestopt; GitHub Secret moet worden bijgewerkt.')
    return data['access_token']


def main():
    config = json.loads((ROOT / 'daily_drive_shows.json').read_text(encoding='utf-8'))
    missing = [name for name in REQUIRED if not config.get(name)]
    if missing:
        raise RuntimeError('Podcast-ID ontbreekt voor: ' + ', '.join(missing) +
                           '. Vul eerst daily_drive_shows.json aan via de lokale test.')
    today = datetime.now(ZoneInfo('Europe/Amsterdam'))
    if today.weekday() > 4 and os.environ.get('ALLOW_WEEKEND_TEST') != 'true':
        print('Weekend: geen playlistwijziging.')
        return
    token = refresh_access_token()
    base.spotify_login = lambda: token

    def configured_show(name, _token, _config):
        return config.get(name)
    drive.select_show = configured_show

    # The original script asks for confirmation only after it has assembled the mix.
    # This runner validates the required episodes first, then confirms non-interactively.
    weekday = today.weekday() if today.weekday() <= 4 else 0
    required_today = ['NU.nl', drive.DAILY_SHOW[weekday], 'Vandaag Inside', 'Dutch Dragons', 'weetjes podcast']
    for name in required_today:
        sid = config[name]
        if name == 'weetjes podcast':
            found = drive.choose_trivia_episode(sid, token)
        else:
            found = drive.latest_episode(sid, token, name)
        if not found:
            raise RuntimeError(f'Geen aflevering beschikbaar voor {name}; playlist niet gewijzigd.')
    original_input = builtins.input
    def automatic_input(prompt=''):
        if 'Playlist aanmaken of bijwerken' in prompt:
            return 'JA'
        if 'Testdag' in prompt:
            return '0'
        raise RuntimeError('Onverwachte handmatige invoer gevraagd: ' + prompt)
    builtins.input = automatic_input
    try:
        drive.main()
    finally:
        builtins.input = original_input


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FOUT:', exc, file=sys.stderr)
        sys.exit(1)
