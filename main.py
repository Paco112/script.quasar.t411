# coding: utf-8

import re
import json
import xbmc
import xbmcaddon
from quasar import provider
import hashlib
import bencode
from threading import Thread
import Queue


# Addon Script information
_ID_ = provider.ADDON.getAddonInfo('id')
_API_ = provider.ADDON.getSetting("base_url")
_USERNAME_ = provider.ADDON.getSetting("username")
_PASSWORD_ = provider.ADDON.getSetting("password")
_TITLE_VF_ = provider.ADDON.getSetting("title_vf")
_ICON_ = xbmcaddon.Addon().getAddonInfo('icon')
_FILTER_MOVIE_ = provider.ADDON.getSetting("filter_movie")
_FILTER_SERIES_ = provider.ADDON.getSetting("filter_series")
_FILTER_SERIES_FULL_ = provider.ADDON.getSetting("filter_series_full")
_FILTER_LIMIT_ = 15

USER_CREDENTIALS = {}
USER_CREDENTIALS_FILE = xbmc.translatePath("special://profile/addon_data/%s/token.txt" % _ID_)

TMDB_URL = 'http://api.themoviedb.org/3'
TMDB_KEY = '8d0e4dca86c779f4157fc2c469c372ca'  # mancuniancol's API Key.

# Categories ID /categories/tree
CAT_VIDEO = '210'
CAT_MOVIE = '631'
CAT_MOVIE_ANIM = '455'
CAT_SERIES = '433'
CAT_SERIES_ANIMATED = '637'
CAT_SERIES_EMISSION = '639'


if _API_ == 'https://api.t411.ch':
    new_url = 'https://api.t411.li'
    provider.ADDON.setSetting("base_url", new_url)
    _API_ = new_url


def _init():
    global USER_CREDENTIALS
    provider.log.info("Get user credentials and authenticate it, "
                      "if any credentials defined use token stored in user file")
    try:
        with open(USER_CREDENTIALS_FILE) as user_cred_file:
            USER_CREDENTIALS = json.loads(user_cred_file.read())
            provider.log.info("Get local credentials")
            provider.log.debug(USER_CREDENTIALS)
        if 'uid' not in USER_CREDENTIALS or 'token' not in USER_CREDENTIALS:
            raise Exception('Wrong data found in user file')
    except IOError:
        # Try to auth user from credentials in parameters
        _auth(_USERNAME_, _PASSWORD_)


def _auth(username, password):
    global USER_CREDENTIALS
    provider.log.info("Authenticate user and store token")
    USER_CREDENTIALS = call('/auth', {'username': username, 'password': password})
    print(USER_CREDENTIALS)
    if 'error' in USER_CREDENTIALS:
        raise Exception('Error while fetching authentication token: %s' % USER_CREDENTIALS['error'])
    # Create or update user file
    provider.log.info('file %s' % USER_CREDENTIALS_FILE)
    user_data = json.dumps({'uid': '%s' % USER_CREDENTIALS['uid'], 'token': '%s' % USER_CREDENTIALS['token']})
    with open(USER_CREDENTIALS_FILE, 'w') as user_cred_file:
        user_cred_file.write(user_data)
    return True


def call(method='', params=None):
    provider.log.info("Call T411 API: %s%s" % (_API_, method))
    if method != '/auth':
        token = USER_CREDENTIALS['token']
        provider.log.info('token %s' % token)
        req = provider.POST('%s%s' % (_API_, method), headers={'Authorization': token})
    else:
        req = provider.POST('%s%s' % (_API_, method), data=provider.urlencode(params))
    if req.getcode() == 200:
        return req.json()
    else:
        raise Exception('Error while sending %s request: HTTP %s' % (method, req.getcode()))


def get_terms(movie=False):
    terms = [[]] * 18
    pref_terms = ''
    # 7 : Video - Quality
    terms[7] = [8, 10, 11, 12, 15, 16, 17, 18, 19, 1162, 1174, 1175, 1182, 1208, 1218, 1233]
    # 9 : Video - Type
    terms[9] = [22, 23, 24, 1045]
    # 17 : Video - Language
    if not movie:
        get_type = 's'
        terms[17] = [1209, 1210, 1211, 1212, 1213, 1214, 1215, 1216]
    else:
        get_type = 'f'
        terms[17] = [540, 541, 542, 719, 720, 721, 1160]

    for idx, term in enumerate(terms):
        for iTerm in term:
            if provider.ADDON.getSetting('%s_%s' % (iTerm, get_type)) == 'true':
                pref_terms += '&term[%s][]=%s' % (idx, iTerm)
    return pref_terms


# Default Search
def search(query, cat_id=CAT_MOVIE, terms=None, episode=False, season=False):
    provider.notify(message=str(query).replace('+', ' ').title(),
                    header="Quasar [COLOR FF18F6F3]t411[/COLOR] Provider", time=3000, image=_ICON_)
    result = []
    threads = []
    search_url = '/torrents/search/%s&?limit=15&cid=%s%s'
    q = Queue.Queue()
    provider.log.debug("QUERY : %s" % query)
    query = query.replace('+', '%20')
    response = call(search_url % (query, cat_id, terms))
    if episode or season:  # search for animation and emission series too
        resp_anim = call(search_url % (query, CAT_SERIES_ANIMATED, terms))
        resp_emission = call(search_url % (query, CAT_SERIES_EMISSION, terms))
        response['torrents'] = response['torrents'] + resp_anim['torrents'] + resp_emission['torrents']
    if episode and _FILTER_SERIES_FULL_ == 'true':
        terms2 = terms[:-3] + '936'
        resp2 = call(search_url % (query, cat_id, terms2))
        resp3 = call(search_url % (query, CAT_SERIES_ANIMATED, terms2))
        resp4 = call(search_url % (query, CAT_SERIES_EMISSION, terms2))
        response['torrents'] = response['torrents'] + resp2['torrents'] + resp3['torrents'] + resp4['torrents']
    provider.log.debug("Search results : %s" % response)
    # quasar send GET requests & t411 api needs POST
    # Must use the bencode tool :(
    
    for t in response['torrents']:
        # Call each individual page in parallel
        thread = Thread(target=torrent2magnet, args=(t, q, USER_CREDENTIALS['token']))
        thread.start()
        threads.append(thread)

    # And get all the results
    for t in threads:
        t.join()
    while not q.empty():
        item = q.get()
        result.append({
                       "size": sizeof_fmt(item["size"]),
                       "seeds": item["seeds"], 
                       "peers": item["peers"], 
                       "name": item["name"],
                       "trackers": item["trackers"],
                       "info_hash": item["info_hash"],
                       "is_private": True,
                       "provider": "[COLOR FF18F6F3]t411[/COLOR]",
                       "icon": _ICON_})
    return result

    
def search_episode(episode):
    terms = ''
    if _FILTER_SERIES_ == 'true':
        terms = get_terms()
               
    provider.log.debug("Search episode : name %(title)s, season %(season)02d, episode %(episode)02d" % episode)
    if _TITLE_VF_ == 'true':
        # Get the FRENCH title from TMDB
        provider.log.debug('Get FRENCH title from TMDB for %s' % episode['imdb_id'])
        response = provider.GET("%s/find/%s?api_key=%s&language=fr&external_source=imdb_id"
                                % (TMDB_URL, episode['imdb_id'], TMDB_KEY))
        provider.log.debug(response)
        if response != (None, None):
            episode['title'] = response.json()['tv_results'][0]['name'].encode('utf-8').replace(' ', '+')
            provider.log.info('FRENCH title :  %s' % episode['title'])
        else:
            provider.log.error('Error when calling TMDB. Use Quasar movie data.')

    if episode['season']:
        real_s = ''
        if episode['season'] < 25 or 27 < episode['season'] < 31:
            real_s = int(episode['season']) + 967
        if episode['season'] == 25:
            real_s = 994
        if 25 < episode['season'] < 28:
            real_s = int(episode['season']) + 966
        terms += '&term[45][]=%s' % real_s

    if episode['episode']:
        real_ep = ''
        if episode['episode'] < 9:
            real_ep = int(episode['episode']) + 936
        if 8 < episode['episode'] < 31:
            real_ep = int(episode['episode']) + 937
        if 30 < episode['episode'] < 61:
            real_ep = int(episode['episode']) + 1057
        terms += '&term[46][]=%s' % real_ep

    return search(episode['title'], CAT_SERIES, terms, episode=True)


def search_season(series):
    terms = ''
    if _FILTER_SERIES_ == 'true':
        terms = get_terms()

    terms += '&term[46][]=936'  # complete season
    
    if _TITLE_VF_ == 'true':
        # Get the FRENCH title from TMDB
        provider.log.debug('Get FRENCH title from TMDB for %s' % series['imdb_id'])
        response = provider.GET("%s/find/%s?api_key=%s&language=fr&external_source=imdb_id"
                                % (TMDB_URL, series['imdb_id'], TMDB_KEY))
        provider.log.debug(response)
        if response != (None, None):
            series['title'] = response.json()['tv_results'][0]['name'].encode('utf-8').replace(' ', '+')
            provider.log.info('FRENCH title :  %s' % series['title'])
        else:
            provider.log.error('Error when calling TMDB. Use Quasar movie data.')

    real_s = ''

    if series['season'] < 25 or 27 < series['season'] < 31:
        real_s = int(series['season']) + 967
        
    if series['season'] == 25:
        real_s = 994
        
    if 25 < series['season'] < 28:
        real_s = int(series['season']) + 966
    
    terms += '&term[45][]=%s' % real_s
    
    return search(series['title'], CAT_SERIES, terms, season=True)
    

def search_movie(movie):
    terms = ''
    if _FILTER_MOVIE_ == 'true':
        terms = get_terms(False)
               
    if _TITLE_VF_ == 'true':
        provider.log.debug('Get FRENCH title from TMDB for %s' % movie['imdb_id'])
        response = provider.GET(
            "%s/movie/%s?api_key=%s&language=fr&external_source=imdb_id&append_to_response=alternative_titles"
            % (TMDB_URL, movie['imdb_id'], TMDB_KEY)
        )
        if response != (None, None):
            response = response.json()
            movie['title'] = response['title'].encode('utf-8')
            if movie['title'].find(' : ') != -1:
                movie['title'] = movie['title'].split(' : ')[0]  # SPLIT LONG TITLE
                movie['title'] = movie['title'] + ' ' + response['release_date'].split('-')[0]  # ADD YEAR
            provider.log.info('FRENCH title :  %s' % movie['title'])
        else:
            provider.log.error('Error when calling TMDB. Use quasar movie data.')
    return search(movie['title'], CAT_VIDEO, terms)


def torrent2magnet(t, q, token):
    torrent_url = '/torrents/download/%s' % t["id"]
    response = provider.POST('%s%s' % (_API_, torrent_url), headers={'Authorization': token})
    torrent = response.data
    metadata = bencode.bdecode(torrent)
    hash_contents = bencode.bencode(metadata['info'])
    digest = hashlib.sha1(hash_contents).hexdigest()
    trackers = [metadata["announce"]]
    q.put({
        "size": int(t["size"]),
        "seeds": int(t["seeders"]),
        "peers": int(t["leechers"]),
        "name": t["name"].encode('utf-8'),
        "trackers": trackers,
        "info_hash": digest
    })


def sizeof_fmt(num, suffix=''):
    for unit in ['', 'Ko', 'Mo', 'GB', 'To', 'Po', 'Eo', 'Zo']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)

# Initialize account
_init()

# Registers the module in quasar
provider.register(search, search_movie, search_episode, search_season)
