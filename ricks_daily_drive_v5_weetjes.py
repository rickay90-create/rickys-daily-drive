"""Rick's Daily Drive: volledige weekdagtest. Plaats naast ricks_daily_drive_v2.py.
Installatie: python -m pip install requests
Let op: nieuw muziek ontdekken is nog niet geïmplementeerd; Release Radar werkt alleen als uitlezen toegestaan is.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import ricks_daily_drive_v2 as base

base.SCOPES = 'playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public'
API = 'https://api.spotify.com/v1'
BLOCKED = {"El Gato's Playlist", 'PASS DE AUX', 'Feestje'}
SOURCES = {name: pid for name, pid in base.SOURCE_PLAYLISTS.items() if name not in BLOCKED}
DAILY_SHOW = {0:'Vik en Gert', 1:'ADHAZES', 2:'De Beste Sales Podcast', 3:'Cyberhelden', 4:'Borrelpraat'}
SHOWS = ['NU.nl', 'Vik en Gert', 'ADHAZES', 'De Beste Sales Podcast', 'Cyberhelden', 'Borrelpraat', 'Vandaag Inside', 'Dutch Dragons']
CONFIG_FILE = Path(__file__).with_name('daily_drive_shows.json')
PLAYLIST_NAME = 'RICKY"S DAILY DRIVE 🚗'
TRIVIA_SHOW = 'Dagelijks weetje'
TRIVIA_HISTORY = Path(__file__).with_name('daily_drive_weetjes_historie.json')


def api(method, path, token, **kwargs):
    url = path if path.startswith('https://') else API + path
    r = requests.request(method, url, headers={'Authorization': f'Bearer {token}', 'Content-Type':'application/json'}, timeout=35, **kwargs)
    if not r.ok:
        raise RuntimeError(f'{method} {url}: HTTP {r.status_code}: {r.text[:250]}')
    return r.json() if r.content else {}


def select_show(name, token, config):
    if name in config:
        return config[name]
    results = api('GET', '/search', token, params={'q':name, 'type':'show', 'limit':10, 'market':'NL'})
    shows = [s for s in (results.get('shows') or {}).get('items', []) if s and s.get('id')]
    print(f'\nKies de juiste Spotify-podcast voor {name}:')
    for n, show in enumerate(shows, 1):
        print(f' {n}. {show.get("name")} — {show.get("publisher", "onbekend")}')
    choice = input('Nummer (Enter = overslaan): ').strip()
    if choice.isdigit() and 1 <= int(choice) <= len(shows):
        config[name] = shows[int(choice)-1]['id']
        CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
        return config[name]
    return None


def latest_episode(show_id, token, name, previous_workday=False):
    data = api('GET', f'/shows/{show_id}/episodes', token, params={'limit':50, 'market':'NL'})
    episodes = [e for e in data.get('items',[]) if e and e.get('id') and e.get('release_date')]
    episodes.sort(key=lambda e:(e['release_date'],e['id']), reverse=True)
    if not episodes:
        return None
    if previous_workday:
        today = datetime.now(ZoneInfo('Europe/Amsterdam')).date()
        target = today - timedelta(days=3 if today.weekday()==0 else 1)
        match = next((e for e in episodes if e['release_date'][:10] == target.isoformat()), None)
        if match:
            return match
        print(f'  Vandaag Inside: geen aflevering gevonden van {target}; nieuwste beschikbare als fallback.')
    return episodes[0]



def choose_trivia_episode(show_id, token):
    """Kies een niet eerder gebruikte aflevering van 10-25 minuten, zo dicht mogelijk bij 20."""
    data = api('GET', f'/shows/{show_id}/episodes', token,
               params={'limit': 50, 'market': 'NL'})
    episodes = [e for e in data.get('items', [])
                if e and e.get('id') and e.get('duration_ms')]
    suitable = [e for e in episodes if 10*60_000 <= e['duration_ms'] <= 25*60_000]
    if not suitable:
        print('  Geen weetjesaflevering van 10-25 minuten; kies meest recente beschikbare.')
        return episodes[0] if episodes else None
    try:
        history = json.loads(TRIVIA_HISTORY.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    fresh = [e for e in suitable if e['id'] not in history]
    if not fresh:
        print('  Alle geschikte weetjesafleveringen al gebruikt; begin opnieuw.')
        fresh = suitable
    # Variatie met lichte voorkeur voor ongeveer 20 minuten.
    sample = sorted(fresh, key=lambda e: abs(e['duration_ms'] - 20*60_000))[:15]
    return random.choice(sample)


def remember_trivia(episode):
    if not episode:
        return
    try:
        history = json.loads(TRIVIA_HISTORY.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    if episode['id'] not in history:
        history.append(episode['id'])
    TRIVIA_HISTORY.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=2), encoding='utf-8')

def block(tracks, used, minutes, party=False):
    pool = [t for t in tracks if t['id'] not in used and 110 <= t['seconds'] <= 310]
    if party:
        words = ('feest','kroeg','party','dance','hard','remix','bier','holland','gabber','fissa','beuk','vrijdag')
        party_pool = [t for t in pool if any(w in (t['title']+' '+t['artist']).lower() for w in words)]
        if len(party_pool)>=5:
            pool=party_pool
        else:
            print('  Vrijdagmix: te weinig herkenbare feesttracks; algemene mix als fallback.')
    random.shuffle(pool)
    picked=[]; seconds=0; last_artist=None
    while pool and seconds < minutes*60-60:
        remaining=minutes*60-seconds
        eligible=[t for t in pool if t['artist_id']!=last_artist and t['seconds']<=remaining+35]
        if not eligible: break
        t=random.choice(eligible)
        picked.append(t); used.add(t['id']); seconds+=t['seconds']; last_artist=t['artist_id']; pool.remove(t)
    return picked


def add_music(items, tracks, title):
    print(f'{title}: {len(tracks)} nummers / {round(sum(t["seconds"] for t in tracks)/60,1)} min')
    for t in tracks:
        items.append({'type':'track','name':t['artist']+' - '+t['title'],'uri':t['uri']})


def add_episode(items, episode, label):
    if episode:
        items.append({'type':'episode','name':f'{label}: {episode.get("name")}', 'uri':episode.get('uri') or 'spotify:episode:'+episode['id']})
    else:
        print(f'  WAARSCHUWING: {label} ontbreekt; niet stilzwijgend vervangen door een andere podcast.')


def main():
    today=datetime.now(ZoneInfo('Europe/Amsterdam'))
    weekday=today.weekday()
    if weekday>4:
        print('Het is weekend; test standaard maandag. Geef eventueel 0-4 op voor ma-vr.')
        value=input('Testdag (0=ma,1=di,2=wo,3=do,4=vr; Enter=ma): ').strip()
        weekday=int(value) if value in ('0','1','2','3','4') else 0
    print('Testschema:', ['maandag','dinsdag','woensdag','donderdag','vrijdag'][weekday])
    token=base.spotify_login()
    me=api('GET','/me',token)
    print('Verbonden met:',me.get('display_name') or me['id'])
    tracks=[]
    for name,pid in SOURCES.items():
        try:
            found=base.get_tracks(pid,token)
            tracks.extend(found)
            print(f' {name}: {len(found)} nummers')
        except (RuntimeError,requests.RequestException) as e:
            print(f' OVERGESLAGEN {name}: {e}')
    if not tracks:
        print('Geen muziek beschikbaar.');return
    config=json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
    episodes={}
    for name in ('NU.nl',DAILY_SHOW[weekday],'Vandaag Inside','Dutch Dragons'):
        try:
            sid=select_show(name,token,config)
            episodes[name]=latest_episode(sid,token,name,previous_workday=(name=='Vandaag Inside' and weekday!=0)) if sid else None
            if name=='Vandaag Inside' and weekday==0 and sid:
                # Bij weekendtest moet vorige werkdag vrijdag zijn; latest_episode rekent met echte datum.
                episodes[name]=latest_episode(sid,token,name,previous_workday=True)
            if episodes[name]:print(' ',name,':',episodes[name].get('name'),episodes[name].get('release_date'))
        except (RuntimeError,requests.RequestException) as e:
            print(f'  Niet beschikbaar: {name}: {e}');episodes[name]=None
    # Kies bij de eerste test een echte weetjespodcast via Spotify-zoekresultaten.
    # We zoeken op 'weetjes podcast'; kies een show met afleveringen rond 20 minuten.
    trivia_episode = None
    try:
        trivia_id = select_show('weetjes podcast', token, config)
        if trivia_id:
            trivia_episode = choose_trivia_episode(trivia_id, token)
            if trivia_episode:
                print('  Dagelijks weetje:', trivia_episode.get('name'),
                      f"({round(trivia_episode['duration_ms']/60000)} min)")
    except (RuntimeError, requests.RequestException) as e:
        print('  Weetjespodcast niet beschikbaar:', e)
    used=set(); items=[]
    add_episode(items,episodes.get('NU.nl'),'NU.nl nieuwsbulletin')
    if weekday==4:
        print('Release Radar: Spotify-toegang en identificatie zijn nog niet geconfigureerd; tijdelijk normale muziekmix.')
    add_music(items,block(tracks,used,20),'Muziekblok 1')
    add_episode(items,episodes.get(DAILY_SHOW[weekday]),DAILY_SHOW[weekday])
    add_music(items,block(tracks,used,30,party=(weekday==4)),'Muziekblok 2')
    add_episode(items,episodes.get('Vandaag Inside'),'Vandaag Inside')
    add_music(items,block(tracks,used,30),'Muziekblok 3')
    add_episode(items,trivia_episode,'Dagelijks weetje')
    add_episode(items,episodes.get('Dutch Dragons'),'Dutch Dragons')
    add_music(items,block(tracks,used,30),'Muziekblok 4')
    print('\nAFSPEELVOLGORDE:')
    for n,item in enumerate(items,1):print(f' {n:02d}. [{item["type"]}] {item["name"]}')
    Path(__file__).with_name('daily_drive_test_resultaat.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\nDit is een test: ontdekkingen, Release Radar en specifieke NU.nl-bulletincontrole zijn nog niet gegarandeerd.')
    if not items:
        print('Geen items samengesteld; playlist blijft ongewijzigd.'); return
    print('\nDoelplaylist:', PLAYLIST_NAME)
    if input('Playlist aanmaken of bijwerken? Typ JA: ').strip().upper() != 'JA':
        print('Geen wijzigingen in Spotify.'); return
    existing = None
    offset = 0
    while True:
        page = api('GET', '/me/playlists', token, params={'limit': 50, 'offset': offset})
        for p in page.get('items', []):
            if p and p.get('name') == PLAYLIST_NAME and p.get('owner', {}).get('id') == me['id']:
                existing = p
                break
        if existing or not page.get('next'):
            break
        offset += len(page.get('items', []))
    if existing:
        pid = existing['id']
        print('Bestaande playlist gevonden; inhoud wordt vervangen.')
    else:
        playlist = api('POST', '/me/playlists', token, json={
            'name': PLAYLIST_NAME, 'description': 'Rick\'s persoonlijke Daily Drive', 'public': False})
        pid = playlist['id']
        print('Nieuwe playlist aangemaakt.')
    print('Playlist:',f'https://open.spotify.com/playlist/{pid}')
    uris=[i['uri'] for i in items]
    for start in range(0,len(uris),100):
        try:
            method = 'PUT' if start == 0 else 'POST'
            api(method,f'/playlists/{pid}/items',token,json={'uris':uris[start:start+100]})
        except RuntimeError as e:
            print('Toevoegen mislukt; playlist kan gedeeltelijk gevuld zijn:',e)
            return
    remember_trivia(trivia_episode)
    print('GEREED: controleer de afspeelvolgorde in Spotify.')

if __name__=='__main__':
    try:main()
    except (RuntimeError,requests.RequestException,OSError,ValueError,KeyError) as e:print('FOUT:',e)
