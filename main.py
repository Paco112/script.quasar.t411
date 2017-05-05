# coding: utf-8

import unicodedata
import urllib
import json
import xbmc
import xbmcaddon
from quasar import provider
import hashlib
import bencode
import re
from time import strptime
from math import ceil


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
_FILTER_LIMIT_ = int(provider.ADDON.getSetting("filter_limit"))
_TORRENT_DETAILS_ = provider.ADDON.getSetting("torrent_details")

USER_CREDENTIALS = {}
USER_CREDENTIALS_FILE = xbmc.translatePath("special://profile/addon_data/%s/token.txt" % _ID_)
USER_CREDENTIALS_RETRY = 1

TMDB_URL = 'http://api.themoviedb.org/3'
TMDB_KEY = '8d0e4dca86c779f4157fc2c469c372ca'  # mancuniancol's API Key.

# Categories ID /categories/tree
CAT_VIDEO = '210'
CAT_MOVIE = '631'
CAT_MOVIE_ANIM = '455'
CAT_SERIES = '433'
CAT_SERIES_ANIMATED = '637'
CAT_SERIES_EMISSION = '639'

# Quasar RESOLUTION
RESOLUTION_UNKNOWN = 0
RESOLUTION_480P = 1
RESOLUTION_720P = 2
RESOLUTION_1080P = 3
RESOLUTION_1440P = 4
RESOLUTION_4K2K = 5

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:54.0) Gecko/20100101 Firefox/54.0"

if not _API_ or _API_ == 'https://api.t411.ch' or _API_ == 'https://api.t411.li':
    new_url = 'https://api.t411.al'
    provider.ADDON.setSetting("base_url", new_url)
    _API_ = new_url


def _init():
    global USER_CREDENTIALS, USER_CREDENTIALS_RETRY
    USER_CREDENTIALS_RETRY = 1
    provider.log.info("Get user credentials and authenticate it, "
                      "if any credentials defined use token stored in user file")
    try:
        with open(USER_CREDENTIALS_FILE) as user_cred_file:
            USER_CREDENTIALS = json.loads(user_cred_file.read())
            provider.log.info("Get local credentials")
        if 'uid' not in USER_CREDENTIALS or 'token' not in USER_CREDENTIALS:
            raise Exception('Wrong data found in user file')
    except IOError:
        # Try to auth user from credentials in parameters
        _auth(_USERNAME_, _PASSWORD_)


def _auth(username, password):
    global USER_CREDENTIALS
    provider.log.info("Authenticate user and store token")
    USER_CREDENTIALS = call('/auth', {'username': username, 'password': password})
    if 'error' in USER_CREDENTIALS:
        raise Exception('Error while fetching authentication token: %s' % USER_CREDENTIALS['error'])
    # Create or update user file
    provider.log.info('file %s' % USER_CREDENTIALS_FILE)
    user_data = json.dumps({'uid': '%s' % USER_CREDENTIALS['uid'], 'token': '%s' % USER_CREDENTIALS['token']})
    with open(USER_CREDENTIALS_FILE, 'w') as user_cred_file:
        user_cred_file.write(user_data)
    return True


def call(method='', params=None):
    global USER_CREDENTIALS, USER_CREDENTIALS_RETRY
    provider.log.info("Call T411 API: %s%s" % (_API_, method))
    if method != '/auth':
        req = provider.GET('%s%s' % (_API_, method), headers={'Authorization': USER_CREDENTIALS['token']})
    else:
        req = provider.POST('%s%s' % (_API_, method), data=provider.urlencode(params))
    try:
        if req.getcode() == 200:
            resp = req.json()
            # provider.log.debug('Resp T411 API %s' % resp)
            if 'error' in resp:
                provider.notify(message=resp['error'].encode('utf-8', 'ignore'),
                                header="Quasar [COLOR FF18F6F3]t411[/COLOR] Provider", time=3000, image=_ICON_)
                if (resp['code'] == 202 or resp['code'] == 201) and method != '/auth' and USER_CREDENTIALS_RETRY > 0:
                    # Force re auth
                    USER_CREDENTIALS_RETRY -= 1
                    provider.log.info('Force re auth T411 API')
                    if _auth(_USERNAME_, _PASSWORD_):
                        return call(method, params)
            if 'torrents' in resp:
                return resp['torrents']
            return resp
        else:
            provider.log.error(req)
    except Exception as e:
        provider.log.error('Resp ERROR API %s' % e)
    return []


def get_terms(movie=False):
    terms = [[]] * 18
    pref_terms = ''
    # 7 : Video - Quality
    terms[7] = [8, 10, 11, 12, 15, 16, 17, 18, 19, 1162, 1174, 1175, 1182, 1208, 1218, 1233]
    # 9 : Video - Type
    terms[9] = [22, 23, 24, 1045]
    # 17 : Video - Language
    if movie is False:
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


def get_uri_torrent(torrent_id):
    if not id:
        return ""
    global USER_CREDENTIALS
    torrent_url = '/torrents/download/%s' % torrent_id
    torrent_url = '%s%s' % (_API_, torrent_url)
    return provider.append_headers(torrent_url, {'Authorization': USER_CREDENTIALS['token']})


def in_category(torrents, torrent_id):
    if len(torrents):
        for t in torrents:
            if 'id' in t and t['id'] == torrent_id:
                return True
    return False


# Default Search
def search(query, cat_id=CAT_VIDEO, terms=None, episode=False, season=False):
    global USER_CREDENTIALS
    provider.notify(message=str(query).title(),
                    header="Quasar [COLOR FF18F6F3]t411[/COLOR] Provider", time=3000, image=_ICON_)
    result = []
    search_url = '/torrents/search/%s?limit=%s&cid=%s%s'
    provider.log.debug("QUERY : %s" % query)
    query = query.replace(' ', '%20')
    torrents_anim = []
    torrents_saison = []
    torrents_serie_tv = []
    torrents_serie_anim = []
    torrents_saison_tv = []
    torrents_saison_anim = []
    torrents = call(search_url % (query, _FILTER_LIMIT_, cat_id, terms))
    if len(torrents) < (_FILTER_LIMIT_ - 1):
        if not episode and not season:
            # add animated movie
            torrents_anim = call(search_url % (query, _FILTER_LIMIT_, CAT_MOVIE_ANIM, terms))
            torrents = sum([torrents, torrents_anim], [])
        else:
            if episode and _FILTER_SERIES_FULL_ == 'true':
                terms2 = terms[:-3] + '936'
                torrents_saison = call(search_url % (query, _FILTER_LIMIT_, cat_id, terms2))
                if not len(torrents_saison):
                    torrents_saison_tv = call(search_url % (query, _FILTER_LIMIT_, CAT_SERIES_EMISSION, terms2))
                    if not len(torrents_saison_tv):
                        torrents_saison_anim = call(search_url % (query, _FILTER_LIMIT_, CAT_SERIES_ANIMATED, terms2))
                        torrents = sum([torrents, torrents_saison_anim], [])
                    else:
                        torrents = sum([torrents, torrents_saison_tv], [])
                else:
                    torrents = sum([torrents, torrents_saison], [])
            if (episode or season) and len(torrents) < int(ceil(_FILTER_LIMIT_/2)):  # search for animation and emission series too
                torrents_serie_tv = call(search_url % (query, _FILTER_LIMIT_, CAT_SERIES_EMISSION, terms))
                if not len(torrents_serie_tv):
                    torrents_serie_anim = call(search_url % (query, _FILTER_LIMIT_, CAT_SERIES_ANIMATED, terms))
                    torrents = sum([torrents, torrents_serie_anim], [])
                else:
                    torrents = sum([torrents, torrents_serie_tv], [])

    for torrent in torrents:
        if 'id' in torrent:
            torrent = torrent2magnet(torrent, USER_CREDENTIALS['token'])
            if 'id' in torrent:
                category = ""
                if (episode or season) and _FILTER_SERIES_FULL_ == 'true':
                    if in_category(torrents_saison, torrent['id']):
                        category = "[FULL]"
                    elif (episode or season) and in_category(torrents_saison_tv, torrent['id']):
                        category = "[FULL][TV]"
                    elif (episode or season) and in_category(torrents_saison_anim, torrent['id']):
                        category = "[FULL][ANIM]"
                elif episode or season:
                    if in_category(torrents_serie_tv, torrent['id']):
                        category = "[TV]"
                    elif in_category(torrents_serie_anim, torrent['id']):
                        category = "[ANIM]"
                elif (not episode and not season) and in_category(torrents_anim, torrent['id']):
                        category = "[ANIM]"
                if 'uri' in torrent:
                    result.append({
                        "name": "[COLOR FFF05129]%s[/COLOR] [COLOR FF18F6F3]%s[/COLOR][COLOR FFe19623]%s[/COLOR] [COLOR FFa39e9d]%s[/COLOR]"
                                % (torrent["added"], torrent["languages"], category, torrent["name"]),
                        "provider": "t411",
                        "icon": _ICON_,
                        "uri": torrent["uri"],
                        "size": sizeof_fmt(int(torrent["size"])),
                        "seeds": torrent["seeds"],
                        "peers": torrent["peers"],
                        "trackers": torrent["trackers"],
                        "info_hash": torrent["info_hash"],
                        "resolution": torrent["resolution"],
                        "languages": "",
                        "is_private": True
                    })
    # provider.log.debug("==> RESULT <==")
    # provider.log.debug(result)
    return result


def search_episode(episode):
    terms = ''
    if _FILTER_SERIES_ == 'true':
        terms = get_terms()

    provider.log.info("Search episode : name %(title)s, season %(season)02d, episode %(episode)02d" % episode)
    if _TITLE_VF_ == 'true':
        # Get the FRENCH title from TMDB
        provider.log.debug('Get FRENCH title from TMDB for %s' % episode['imdb_id'])
        response = provider.GET("%s/find/%s?api_key=%s&language=fr&external_source=imdb_id"
                                % (TMDB_URL, episode['imdb_id'], TMDB_KEY))
        if response != (None, None):
            title = response.json()['tv_results'][0]['name']
            episode['title'] = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore')
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
        if episode['episode'] == 16:
            real_ep = 954
        elif episode['episode'] == 17:
            real_ep = 953
        elif episode['episode'] < 9:
            real_ep = int(episode['episode']) + 936
        elif 8 < episode['episode'] < 31:
            real_ep = int(episode['episode']) + 937
        elif 30 < episode['episode'] < 61:
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
        if response != (None, None):
            title = response.json()['tv_results'][0]['name']
            series['title'] = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore')
            provider.log.info('FRENCH title :  %s' % series['title'])
        else:
            provider.log.error('Error when calling TMDB. Use Quasar movie data.')

    real_s = ''

    if series['season'] < 25 or 27 < series['season'] < 31:
        real_s = int(series['season']) + 967
    elif series['season'] == 25:
        real_s = 994
    elif 25 < series['season'] < 28:
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
            movie['title'] = unicodedata.normalize('NFKD', response['title']).encode('ascii', 'ignore')
            if movie['title'].find(' : ') != -1:
                movie['title'] = movie['title'].split(' : ')[0]  # SPLIT LONG TITLE
                movie['title'] = movie['title'] + ' ' + response['release_date'].split('-')[0]  # ADD YEAR
            provider.log.info('FRENCH title :  %s' % movie['title'])
        else:
            provider.log.error('Error when calling TMDB. Use quasar movie data.')
    return search(movie['title'], CAT_MOVIE, terms)


def torrent2magnet(t, token):
    try:
        torrent_details = {}
        if _TORRENT_DETAILS_ == 'true':
            details_url = '/torrents/details/%s' % t["id"]
            torrent_details = call(details_url)
        torrent_url = '/torrents/download/%s' % t["id"]
        provider.log.info('%s%s' % (_API_, torrent_url))
        resp_torrent = provider.GET('%s%s' % (_API_, torrent_url), headers={'Authorization': token})
        if resp_torrent.data:
            torrent = resp_torrent.data
            metadata = bencode.bdecode(torrent)
            hash_contents = bencode.bencode(metadata['info'])
            hashsha1 = hashlib.sha1(hash_contents)
            digest = hashsha1.hexdigest()
            # b32hash = base64.b32encode(hashsha1.digest())
            trackers = [metadata['announce']]
            params = {'xt': 'urn:btih:%s' % digest,
                      'dn': urllib.quote_plus(metadata['info']['name']),
                      'tr': urllib.quote_plus(metadata['announce'])}

            name = t['name'].encode('utf-8', 'ignore')
            date = strptime(t['added'], '%Y-%m-%d %H:%M:%S')
            languages = get_languages(name)
            resolution = get_resolution(name)

            if _TORRENT_DETAILS_ == 'true' and 'terms' in torrent_details:
                if u'Vid\xe9o - Qualit\xe9' in torrent_details['terms']:
                    resolution = get_resolution(
                        torrent_details['terms'][u'Vid\xe9o - Qualit\xe9'].encode('utf-8', 'ignore')
                    )
                if u'Vid\xe9o - Langue' in torrent_details['terms']:
                    languages = torrent_details['terms'][u'Vid\xe9o - Langue'].encode('utf-8', 'ignore')

            return {
                "id": t["id"],
                "uri": "magnet:?xt=%s&dn=%s&tr=%s" % (params['xt'], params['dn'], params['tr']),
                "size": int(t['size']),
                "seeds": int(t['seeders']),
                "peers": int(t['leechers']),
                "name": name,
                "trackers": trackers,
                "info_hash": digest,
                "resolution": resolution,
                "languages": languages,
                "added": '%s' % date.tm_year
                # "added": '[%s-%s]' % (date.tm_year, str(date.tm_mon).zfill(2))
            }
    except Exception as e:
        provider.log.error('Error torrent2magnet : %s' % e)
    provider.log.warn('No Result !')
    return {}


def get_languages(txt):
    lang = ""
    if re.findall('[^a-z]+(multi|multilangue[s]?)([^a-z]+|$)', txt, flags=re.IGNORECASE):
        lang = "MULTI"
    elif re.findall('[^a-z]+(true)?(french|fran[c|ç]ais|[v|o]*st[^a-z]*fr|fr[^a-z]|vff)', txt, flags=re.IGNORECASE):
        lang = "FR"
    elif re.findall('[^a-z]+(true)?(english|anglais|[v|o]*st[^a-z]*en|en[^a-z])', txt, flags=re.IGNORECASE):
        lang = "EN"
    if lang != "MULTI" and re.findall('([^a-z][vo|\s|\-|_|\||\[|\]|\+|\.]*st|sous[\s|\-|_|\||\[|\]|\+|\.]+titre)(fr|en|[^a-z])', txt, flags=re.IGNORECASE):
        lang = "ST%s" % lang
    if re.findall('[^a-z]+vo([^a-z]+|[^a-z]*st)', txt, flags=re.IGNORECASE):
        lang = "VO%s" % lang
    if lang:
        if re.findall('[^a-z]+vfq[^a-z]+', txt, flags=re.IGNORECASE):
            return "[%s] [VFQ]" % lang.strip()
        return "[%s]" % lang.strip()
    return lang


def get_resolution(txt):
    txt = txt.upper()
    if txt.find('4k') != -1:
        return RESOLUTION_4K2K
    if txt.find('1440') != -1:
        return RESOLUTION_1440P
    if txt.find('1080') != -1:
        return RESOLUTION_1080P
    if txt.find('480P') != -1:
        return RESOLUTION_UNKNOWN
    if txt.find('720') != -1 or txt.find('HDTV') != -1 or txt.find('DVD') != -1:
        return RESOLUTION_720P
    return RESOLUTION_UNKNOWN


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
