#!/usr/bin/env python3
"""Beyond Horizons 后台：访问统计 + 日记 + 吃饭地图的店 + 扫街照片 + 背景音乐。

- 只听 127.0.0.1（默认 8788 端口），由 nginx 把 /api/stat、/api/diary、/api/admin、/api/u/ 转过来。
- 访问统计：网页匿名发来「打开了网站 / 换了板块 / 点开了哪张照片、哪家店 / 还在看」这些事件。
  不存 IP（只用它当场查出省市，查完就丢），访客编号也只存加盐后的哈希；后台登录的人自己的访问不计。
- 日记：后台写好、点发布，网页打开时从 /api/diary 读，马上就能看到；照片存在服务器上，由 /api/u/ 发出去。
- 吃饭地图的店、扫街照片：后台新加的、或改过的网站自带条目（同一个 id 替换），也从 /api/diary?all=1 一起读；
  藏起来的条目（hidden）网站上就不显示。删掉后台记录 = 恢复成网站自带的样子。
- 背景音乐：后台上传 mp3 / m4a 和歌名、歌手，同样从 /api/diary?all=1 读；歌曲文件由 /api/u/ 发出去（支持断点 Range，iPhone 才能播）。
- 后台密码只以 PBKDF2 哈希存在 /etc/beyond-horizons/admin.env（deploy/admin-setup.sh 在服务器上输入），
  登录后发一张 30 天有效的凭证；连续输错 8 次要等 15 分钟。
- 只用 Python 标准库；省市用 ip2region 离线库（deploy/ip2region/，Apache-2.0）。

环境变量（admin.env）：ADMIN_PASS、ADMIN_SECRET 必填；ADMIN_PORT（8788）、ADMIN_DATA（/var/lib/bh-admin）、ADMIN_XDB
"""
import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PASS = os.environ.get('ADMIN_PASS', '').strip()
SECRET = os.environ.get('ADMIN_SECRET', '').strip().encode()
PORT = int(os.environ.get('ADMIN_PORT', '8788'))
DATA = os.environ.get('ADMIN_DATA') or os.environ.get('STATE_DIRECTORY') or '/var/lib/bh-admin'
XDB = os.environ.get('ADMIN_XDB', os.path.join(HERE, 'ip2region_v4.xdb'))
CST = timezone(timedelta(hours=8))
UPLOADS = os.path.join(DATA, 'u')
if not PASS or not SECRET: sys.exit('ADMIN_PASS / ADMIN_SECRET 没有设置：先运行 deploy/admin-setup.sh')
os.makedirs(UPLOADS, exist_ok=True)

# ------------------------------------------------------------------ 省市（ip2region 离线库）
REGION = None
try:
    sys.path.insert(0, HERE)
    import ip2region.searcher as _xs
    import ip2region.util as _xu
    REGION = _xs.new_with_buffer(_xu.IPv4, _xu.load_content_from_file(XDB))
except Exception as e:   # 没有离线库也能用，只是没有省市
    print('ip2region 没有加载：', e, flush=True)


def region_of(ip):
    if not REGION or not ip or ':' in ip: return ''
    try: r = REGION.search(ip).split('|')
    except Exception: return ''
    r = [x for x in r if x and x != '0']
    if not r: return ''
    if r[0] == '中国':
        prov = r[1] if len(r) > 1 else ''
        city = r[2] if len(r) > 2 and not re.search(r'电信|联通|移动|铁通|阿里|腾讯|华为|百度|教育网|鹏博士|长城', r[2]) else ''
        if prov in ('内网IP',) or r[-1] == '内网IP': return '内网'
        short = lambda x: re.sub(r'(省|市|壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区)$', '', x)
        prov, city = short(prov), short(city)
        return (prov if not city or city == prov else prov + ' ' + city) or '中国'
    return r[0] + (' ' + r[1] if len(r) > 1 and r[1] not in r[0] and not re.search(r'LLC|Inc|Ltd', r[1]) else '')


# ------------------------------------------------------------------ 设备 / 系统 / 浏览器
BOT = re.compile(r'bot|spider|crawl|slurp|curl|wget|python|headless|monitor|preview|scan', re.I)


def ua_of(ua):
    ua = ua or ''
    dev = '平板' if re.search(r'iPad|Tablet|Pad\b|SM-T|MatePad', ua) else '手机' if re.search(r'Mobi|iPhone|Android', ua) else '电脑'
    os_ = ('鸿蒙' if re.search(r'HarmonyOS|OpenHarmony', ua) else 'iOS' if re.search(r'iPhone|iPad|iPod', ua) else 'Android' if 'Android' in ua
           else 'Windows' if 'Windows' in ua else 'macOS' if 'Mac OS X' in ua or 'Macintosh' in ua else 'Linux' if 'Linux' in ua else '其他')
    br = ('微信' if 'MicroMessenger' in ua else 'QQ' if re.search(r'\bQQ/', ua) else '小红书' if re.search(r'xhsdiscover|XiaoHongShu', ua, re.I) else
          '抖音' if re.search(r'aweme|BytedanceWebview', ua) else '微博' if 'Weibo' in ua else '夸克' if 'Quark' in ua else 'UC' if 'UCBrowser' in ua else
          '百度' if re.search(r'baiduboxapp|BIDUBrowser', ua) else '华为浏览器' if 'HuaweiBrowser' in ua else '小米浏览器' if 'MiuiBrowser' in ua else
          'QQ浏览器' if 'MQQBrowser' in ua or 'QQBrowser' in ua else '360' if re.search(r'QihooBrowser|360SE|360EE', ua) else
          'Edge' if 'Edg/' in ua else 'Firefox' if 'Firefox' in ua else 'Chrome' if 'Chrome' in ua or 'CriOS' in ua else 'Safari' if 'Safari' in ua else '其他')
    return dev, os_, br


# ------------------------------------------------------------------ 数据库
DB = os.path.join(DATA, 'admin.db')
LOCK = threading.Lock()


@contextlib.contextmanager
def db():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    try:
        yield c; c.commit()
    finally:
        c.close()


with db() as c:
    c.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER, day TEXT, hour INTEGER, vid TEXT, sid TEXT, ev TEXT,
        mod TEXT, city TEXT, item TEXT, title TEXT, ref TEXT, dev TEXT, os TEXT, br TEXT, region TEXT, scr TEXT);
    CREATE INDEX IF NOT EXISTS ev_ts ON events(ts);
    CREATE INDEX IF NOT EXISTS ev_sid ON events(sid);
    CREATE TABLE IF NOT EXISTS diary (id TEXT PRIMARY KEY, date TEXT, tag TEXT, title TEXT, place TEXT, lng REAL, lat REAL,
        text TEXT, photos TEXT, published INTEGER, created INTEGER, updated INTEGER);
    CREATE TABLE IF NOT EXISTS items (kind TEXT, id TEXT, data TEXT, hidden INTEGER DEFAULT 0, builtin INTEGER DEFAULT 0,
        created INTEGER, updated INTEGER, PRIMARY KEY (kind, id));
    ''')

EVENTS = {'view', 'mod', 'city', 'open', 'ping', 'leave'}
RATE, FAILS = {}, {}


def clip(v, n): return str(v or '')[:n]


def ref_host(r):
    m = re.match(r'https?://([^/:?#]+)', r or '')
    h = (m.group(1).lower() if m else '')
    if h.startswith('www.'): h = h[4:]
    return h


def add_event(o, ip, ua):
    ev = o.get('e')
    if ev not in EVENTS or BOT.search(ua or ''): return
    now = time.time(); t = datetime.fromtimestamp(now, CST)
    vid = hmac.new(SECRET, clip(o.get('v'), 40).encode(), hashlib.sha256).hexdigest()[:16]
    sid = hmac.new(SECRET, clip(o.get('s'), 40).encode(), hashlib.sha256).hexdigest()[:16]
    dev, os_, br = ua_of(ua)
    ref = ref_host(o.get('r')) if ev == 'view' else ''
    with LOCK, db() as c:
        c.execute('INSERT INTO events (ts,day,hour,vid,sid,ev,mod,city,item,title,ref,dev,os,br,region,scr) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (int(now), t.strftime('%Y-%m-%d'), t.hour, vid, sid, ev, clip(o.get('m'), 20), clip(o.get('c'), 20), clip(o.get('i'), 40),
                   clip(o.get('t'), 60), ref, dev, os_, br, region_of(ip) if ev == 'view' else '', clip(o.get('w'), 20)))


def stats(days):
    now = time.time(); today = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    t0 = 0 if days <= 0 else int((today - timedelta(days=days - 1)).timestamp())
    with db() as c:
        q = lambda sql, *a: c.execute(sql, (t0, *a)).fetchall()
        one = lambda sql, *a: c.execute(sql, (t0, *a)).fetchone()
        tot = one("SELECT SUM(ev='view') pv, COUNT(DISTINCT CASE WHEN ev='view' THEN vid END) uv, COUNT(DISTINCT sid) ss FROM events WHERE ts>=?")
        dur = one("SELECT AVG(d) d FROM (SELECT MIN(MAX(ts)-MIN(ts), 7200) d FROM events WHERE ts>=? GROUP BY sid)")
        online = c.execute("SELECT COUNT(DISTINCT sid) n FROM events WHERE ts>=?", (int(now) - 150,)).fetchone()['n']
        new_vis = one("SELECT COUNT(*) n FROM (SELECT vid, MIN(ts) f FROM events WHERE ev='view' GROUP BY vid) WHERE f>=?")
        by_day = q("SELECT day, SUM(ev='view') pv, COUNT(DISTINCT CASE WHEN ev='view' THEN vid END) uv FROM events WHERE ts>=? GROUP BY day ORDER BY day")
        by_hour = q("SELECT hour, SUM(ev='view') pv FROM events WHERE ts>=? GROUP BY hour")
        mods = q("SELECT mod k, COUNT(*) n FROM events WHERE ts>=? AND ev IN ('mod','view') AND mod<>'' GROUP BY mod ORDER BY n DESC")
        items = q("SELECT mod, item, MAX(title) title, COUNT(*) n, COUNT(DISTINCT vid) u FROM events WHERE ts>=? AND ev='open' GROUP BY mod, item ORDER BY n DESC LIMIT 40")
        cities = q("SELECT city k, COUNT(*) n FROM events WHERE ts>=? AND ev='city' AND city<>'' GROUP BY city ORDER BY n DESC LIMIT 20")
        regions = q("SELECT region k, COUNT(DISTINCT vid) n FROM events WHERE ts>=? AND ev='view' GROUP BY region ORDER BY n DESC LIMIT 30")
        g = lambda col: q(f"SELECT {col} k, COUNT(DISTINCT sid) n FROM events WHERE ts>=? AND ev='view' GROUP BY {col} ORDER BY n DESC LIMIT 12")
        devs, oss, brs = g('dev'), g('os'), g('br')
        refs = q("SELECT ref k, COUNT(*) n FROM events WHERE ts>=? AND ev='view' GROUP BY ref ORDER BY n DESC LIMIT 15")
        recent = q("""SELECT sid, MIN(ts) t0, MAX(ts) t1, MAX(region) region, MAX(dev) dev, MAX(os) os, MAX(br) br, MAX(ref) ref, COUNT(*) n,
                      GROUP_CONCAT(CASE WHEN ev='open' THEN title END, '、') opened, MAX(vid) vid
                      FROM events WHERE ts>=? GROUP BY sid ORDER BY t1 DESC LIMIT 40""")
        first = {r['vid']: r['f'] for r in c.execute("SELECT vid, MIN(ts) f FROM events WHERE ev='view' GROUP BY vid")}
    L = lambda rows: [dict(r) for r in rows]
    rec = []
    for r in recent:
        d = dict(r); d['new'] = first.get(d.pop('vid'), 0) >= d['t0'] - 5; d['opened'] = (d['opened'] or '')[:200]; rec.append(d)
    return {'now': int(now), 'from': t0, 'pv': tot['pv'] or 0, 'uv': tot['uv'] or 0, 'sessions': tot['ss'] or 0, 'avg': round(dur['d'] or 0),
            'online': online, 'newVisitors': new_vis['n'] or 0, 'byDay': L(by_day), 'byHour': L(by_hour), 'modules': L(mods), 'items': L(items),
            'cities': L(cities), 'regions': L(regions), 'devices': L(devs), 'os': L(oss), 'browsers': L(brs), 'refs': L(refs), 'recent': rec}


def diary_rows(published_only):
    with db() as c:
        rows = c.execute('SELECT * FROM diary' + (' WHERE published=1' if published_only else '') + ' ORDER BY date DESC, created DESC').fetchall()
    out = []
    for r in rows:
        d = {'id': r['id'], 'date': r['date'], 'tag': r['tag'], 'title': r['title'], 'place': r['place'], 'text': r['text'],
             'lnglat': [r['lng'], r['lat']] if r['lng'] is not None and r['lat'] is not None else None, 'photos': json.loads(r['photos'] or '[]')}
        if not published_only: d.update(published=bool(r['published']), updated=r['updated'])
        out.append(d)
    return out


PHOTO = re.compile(r'^/api/u/[0-9a-f]{20}(-s)?\.jpg$')
AUDIO = re.compile(r'^/api/u/[0-9a-f]{20}\.(mp3|m4a)$')


def save_diary(o):
    date = clip(o.get('date'), 10)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date): raise ValueError('日期不对')
    title = clip(o.get('title'), 80).strip()
    if not title: raise ValueError('标题不能空着')
    ll = o.get('lnglat')
    lng = lat = None
    if ll:
        lng, lat = float(ll[0]), float(ll[1])
        if not (-180 <= lng <= 180 and -85 <= lat <= 85): raise ValueError('位置不对')
    photos = []
    for p in (o.get('photos') or [])[:12]:
        if PHOTO.match(str(p.get('src', ''))) and PHOTO.match(str(p.get('thumb', p.get('src', '')))):
            photos.append({'src': p['src'], 'thumb': p.get('thumb', p['src']), 'ar': round(float(p.get('ar') or 1.333), 3)})
    now = int(time.time()); did = clip(o.get('id'), 24)
    if not re.match(r'^d[0-9a-z]{4,22}$', did): did = 'd' + format(int(time.time() * 1000), 'x')
    with LOCK, db() as c:
        old = c.execute('SELECT created FROM diary WHERE id=?', (did,)).fetchone()
        c.execute('REPLACE INTO diary (id,date,tag,title,place,lng,lat,text,photos,published,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (did, date, clip(o.get('tag'), 8) or '日常', title, clip(o.get('place'), 60), lng, lat, clip(o.get('text'), 20000),
                   json.dumps(photos, ensure_ascii=False), 1 if o.get('published', True) else 0, old['created'] if old else now, now))
    return did


def files_of(data):
    """一条记录用到的上传文件：照片列表，加上歌曲本身的 src"""
    out = list(data.get('photos') or [])
    if data.get('src'): out.append({'src': data['src']})
    return out


def drop_unused(c, photos):
    """删掉不再被任何日记 / 条目用到的上传照片和歌曲"""
    used = ' '.join(r['photos'] or '' for r in c.execute('SELECT photos FROM diary')) + ' '.join(r['data'] or '' for r in c.execute('SELECT data FROM items'))
    for p in photos:
        for k in ('src', 'thumb'):
            name = os.path.basename(str(p.get(k) or ''))
            if (PHOTO.match('/api/u/' + name) or AUDIO.match('/api/u/' + name)) and name not in used:
                try: os.remove(os.path.join(UPLOADS, name))
                except OSError: pass


def delete_diary(did):
    with LOCK, db() as c:
        row = c.execute('SELECT photos FROM diary WHERE id=?', (did,)).fetchone()
        c.execute('DELETE FROM diary WHERE id=?', (did,))
        drop_unused(c, json.loads(row['photos'] or '[]') if row else [])


# ------------------------------------------------------------------ 吃饭地图的店、扫街照片
SITE_PHOTO = re.compile(r'^photos/[A-Za-z0-9_\-/]+\.(jpg|jpeg|png|webp)$')
CITY = re.compile(r'^[a-z]{2,12}$')
ITEM_ID = {'food': re.compile(r'^f[0-9a-z]{1,15}$'), 'street': re.compile(r'^s[0-9a-z]{1,15}$'),
           'music': re.compile(r'^m[0-9a-z]{1,40}$')}   # 网站自带的歌：m + 文件名（music/yuzai.mp3 → myuzai）
SITE_AUDIO = re.compile(r'^music/[a-z0-9_\-]+\.(mp3|m4a)$')


def photo_ok(s):
    s = str(s or '')
    return bool(PHOTO.match(s) or (SITE_PHOTO.match(s) and '..' not in s))


def lnglat(v):
    lng, lat = float(v[0]), float(v[1])
    if not (-180 <= lng <= 180 and -85 <= lat <= 85): raise ValueError('位置不对')
    return [round(lng, 6), round(lat, 6)]


def text(o, k, n): return clip(o.get(k), n).strip()


def clean_food(o):
    d = {'name': text(o, 'name', 60), 'cat': text(o, 'cat', 20) or '其他', 'score': None, 'area': text(o, 'area', 20), 'review': clip(o.get('review'), 6000).strip()}
    if not d['name']: raise ValueError('店名不能空着')
    if o.get('score') not in (None, ''):
        try: sc = float(o['score'])
        except (TypeError, ValueError): raise ValueError('评分要是数字')
        if not 0 <= sc <= 10: raise ValueError('评分要在 0 到 10 之间')
        d['score'] = round(sc, 1)
    if text(o, 'note', 1000): d['note'] = text(o, 'note', 1000)
    city = str(o.get('city') or '')
    if CITY.match(city) and city != 'gz': d['city'] = city
    if o.get('chain'): d['chain'] = True
    if o.get('unfound'): d['unfound'] = True
    locs = []
    for L in (o.get('locs') or [])[:30]:
        if not isinstance(L, dict): continue
        try: p = lnglat(L.get('p'))
        except (TypeError, ValueError, IndexError): continue
        x = {'b': text(L, 'b', 40), 's': text(L, 's', 40), 'p': p}
        if text(L, 'a', 160): x['a'] = text(L, 'a', 160)
        if text(L, 'm', 40): x['m'] = text(L, 'm', 40)
        if L.get('af'): x['af'] = 1
        if L.get('approx'): x['approx'] = True
        locs.append(x)
    if locs: d['locs'] = locs
    br = []
    for b in (o.get('branches') or [])[:400]:
        try: br.append({**{k: clip(v, 80) for k, v in b.items() if k != 'p' and isinstance(v, str)}, 'p': lnglat(b['p'])})
        except (TypeError, ValueError, KeyError, IndexError, AttributeError): continue
    if br: d['branches'] = br
    return d


def clean_street(o):
    d = {'city': str(o.get('city') or 'gz'), 'title': text(o, 'title', 60), 'place': text(o, 'place', 80), 'date': text(o, 'date', 40), 'note': clip(o.get('note'), 3000).strip()}
    if not CITY.match(d['city']): d['city'] = 'gz'
    if not d['title']: raise ValueError('标题不能空着')
    if o.get('lnglat'): d['lnglat'] = lnglat(o['lnglat'])
    photos = []
    for p in (o.get('photos') or [])[:60]:
        if not isinstance(p, dict) or not photo_ok(p.get('src')): continue
        try: ar = float(p.get('ar') or 1.5)
        except (TypeError, ValueError): ar = 1.5
        x = {'src': p['src'], 'cap': text(p, 'cap', 80), 'ar': round(min(5, max(0.2, ar)), 3)}
        if photo_ok(p.get('thumb')): x['thumb'] = p['thumb']
        if text(p, 'loc', 80): x['loc'] = text(p, 'loc', 80)
        if text(p, 'area', 100): x['area'] = text(p, 'area', 100)
        photos.append(x)
    if not photos: raise ValueError('至少要有一张照片')
    d['photos'] = photos
    return d


def clean_music(o):
    d = {'title': text(o, 'title', 60), 'artist': text(o, 'artist', 60)}
    if not d['title']: raise ValueError('歌名不能空着')
    if not d['artist']: raise ValueError('歌手不能空着')
    by = text(o, 'by', 40)
    if by and by != d['artist']: d['by'] = by
    src = str(o.get('src') or '')
    if not (AUDIO.match(src) or SITE_AUDIO.match(src)): raise ValueError('还没上传歌曲文件')
    d['src'] = src
    return d


CLEAN = {'food': clean_food, 'street': clean_street, 'music': clean_music}


def items_rows(public):
    with db() as c: rows = c.execute('SELECT * FROM items ORDER BY updated DESC').fetchall()
    out = {'food': [], 'street': [], 'music': []}
    for r in rows:
        if r['kind'] not in out: continue
        data = json.loads(r['data'] or '{}')
        if public:
            if r['hidden'] or not data: out[r['kind']].append({'id': r['id'], 'hidden': True}); continue
            rec = {**data, 'id': r['id']}
            if r['kind'] == 'music' and not r['builtin']:   # 新上传的歌：上传那天（北京时间），网站月历上按天标出来
                rec['added'] = time.strftime('%Y-%m-%d', time.gmtime((r['created'] or 0) + 8 * 3600))
            out[r['kind']].append(rec)
        else: out[r['kind']].append({'id': r['id'], 'data': data, 'hidden': bool(r['hidden']), 'builtin': bool(r['builtin']), 'updated': r['updated']})
    return out


def save_item(o):
    kind = o.get('kind')
    if kind not in ITEM_ID: raise ValueError('不知道是哪一类')
    builtin = bool(o.get('builtin')); iid = clip(o.get('id'), 41)
    if builtin and not ITEM_ID[kind].match(iid): raise ValueError('编号不对')
    if not ITEM_ID[kind].match(iid): iid = kind[0] + 'x' + secrets.token_hex(4)
    hidden = bool(o.get('hidden'))
    data = {} if hidden and builtin and not o.get('data') else CLEAN[kind](o.get('data') or {})
    now = int(time.time())
    with LOCK, db() as c:
        old = c.execute('SELECT created, data, builtin FROM items WHERE kind=? AND id=?', (kind, iid)).fetchone()
        c.execute('REPLACE INTO items (kind,id,data,hidden,builtin,created,updated) VALUES (?,?,?,?,?,?,?)',
                  (kind, iid, json.dumps(data, ensure_ascii=False), 1 if hidden else 0, 1 if (builtin or (old and old['builtin'])) else 0,
                   old['created'] if old else now, now))
        if old: drop_unused(c, files_of(json.loads(old['data'] or '{}')))
    return iid


def delete_item(kind, iid):
    with LOCK, db() as c:
        row = c.execute('SELECT data FROM items WHERE kind=? AND id=?', (kind, iid)).fetchone()
        c.execute('DELETE FROM items WHERE kind=? AND id=?', (kind, iid))
        drop_unused(c, files_of(json.loads(row['data'] or '{}')) if row else [])


# ------------------------------------------------------------------ 登录凭证
def check_pass(pw):
    try:
        algo, it, salt, h = PASS.split(':')
        got = hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return algo == 'pbkdf2_sha256' and hmac.compare_digest(got, h)
    except Exception:
        return False


def make_token():
    body = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 30 * 86400, 'n': secrets.token_hex(6)}).encode()).decode().rstrip('=')
    return body + '.' + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def token_ok(tok):
    try:
        body, sig = tok.split('.')
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()): return False
        return json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))['exp'] > time.time()
    except Exception:
        return False


def limited(table, key, n, window):
    now = time.time(); q = [t for t in table.get(key, []) if t > now - window]
    table[key] = q
    return len(q) >= n


# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    server_version = 'bh-admin'

    def log_message(self, *a): pass

    def ip(self): return (self.headers.get('X-Real-IP') or self.client_address[0]).strip()

    def send(self, code, obj=None, ctype='application/json; charset=utf-8', body=None, cache='no-store'):
        if body is None: body = b'' if obj is None else json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode()
        self.send_response(code)
        if body or code != 204: self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers()
        if body and self.command != 'HEAD': self.wfile.write(body)

    def send_file(self, f, ctype):
        """发上传的文件；支持 Range（音频拖进度条、iPhone 播放都要用）"""
        if not os.path.isfile(f): return self.send(404, {'error': 'not found'})
        size = os.path.getsize(f); start, end, code = 0, size - 1, 200
        m = re.match(r'^bytes=(\d*)-(\d*)$', (self.headers.get('Range') or '').strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1): start = int(m.group(1)); end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else: start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.send_header('Content-Length', '0'); self.end_headers(); return
            code = 206
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1)); self.send_header('Cache-Control', 'public, max-age=2592000, immutable')
        if code == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD': return
        try:
            with open(f, 'rb') as fh:
                fh.seek(start); left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(262144, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError): pass

    def body(self, limit):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit: raise ValueError(f'太大了（最大 {limit // 1048576} MB）')
        return self.rfile.read(n) if n else b''

    def authed(self):
        a = self.headers.get('Authorization', '')
        return a.startswith('Bearer ') and token_ok(a[7:].strip())

    def do_GET(self):
        u = urlparse(self.path); p = u.path
        if p == '/api/diary':   # ?all=1：日记 + 后台加的店和扫街照片一起回（旧版网页不带参数，只要日记数组）
            if 'all=1' in u.query: return self.send(200, {'diary': diary_rows(True), **items_rows(True)}, cache='no-cache')
            return self.send(200, diary_rows(True), cache='no-cache')
        m = re.match(r'^/api/u/([0-9a-f]{20}(?:-s)?\.(jpg|mp3|m4a))$', p)
        if m: return self.send_file(os.path.join(UPLOADS, m.group(1)), {'jpg': 'image/jpeg', 'mp3': 'audio/mpeg', 'm4a': 'audio/mp4'}[m.group(2)])
        if not p.startswith('/api/admin/'): return self.send(404, {'error': 'not found'})
        if not self.authed(): return self.send(401, {'error': '请先登录'})
        if p == '/api/admin/stats':
            days = int((parse_qs(u.query).get('days') or ['7'])[0]); return self.send(200, stats(days))
        if p == '/api/admin/diary': return self.send(200, diary_rows(False))
        if p == '/api/admin/items': return self.send(200, items_rows(False))
        if p == '/api/admin/ping': return self.send(200, {'ok': True})
        return self.send(404, {'error': 'not found'})

    def do_HEAD(self):
        m = re.match(r'^/api/u/([0-9a-f]{20}(?:-s)?\.(jpg|mp3|m4a))$', urlparse(self.path).path)
        if m: return self.send_file(os.path.join(UPLOADS, m.group(1)), {'jpg': 'image/jpeg', 'mp3': 'audio/mpeg', 'm4a': 'audio/mp4'}[m.group(2)])
        return self.send(404)

    def do_POST(self):
        p = urlparse(self.path).path; ip = self.ip()
        try:
            if p == '/api/stat':
                if limited(RATE, ip, 240, 60): return self.send(204)
                RATE[ip].append(time.time())
                try: o = json.loads(self.body(4096) or b'{}')
                except ValueError: return self.send(204)
                if isinstance(o, dict): add_event(o, ip, self.headers.get('User-Agent', ''))
                return self.send(204)
            if p == '/api/admin/login':
                if limited(FAILS, ip, 8, 900): return self.send(429, {'error': '输错太多次了，15 分钟后再试'})
                o = json.loads(self.body(2048) or b'{}')
                if check_pass(str(o.get('password', ''))): FAILS.pop(ip, None); return self.send(200, {'token': make_token()})
                FAILS.setdefault(ip, []).append(time.time()); time.sleep(0.6)
                return self.send(403, {'error': '密码不对'})
            if not self.authed(): return self.send(401, {'error': '请先登录'})
            if p == '/api/admin/diary':
                return self.send(200, {'id': save_diary(json.loads(self.body(200000) or b'{}'))})
            if p == '/api/admin/items':
                o = json.loads(self.body(400000) or b'{}')
                if not isinstance(o, dict): raise ValueError('格式不对')
                return self.send(200, {'id': save_item(o)})
            if p == '/api/admin/upload':
                data = self.body(8 * 1024 * 1024)
                if data[:3] != b'\xff\xd8\xff': return self.send(400, {'error': '只收 JPEG'})
                name = hashlib.sha256(data).hexdigest()[:20] + ('-s' if 'thumb=1' in self.path else '') + '.jpg'
                with open(os.path.join(UPLOADS, name), 'wb') as f: f.write(data)
                return self.send(200, {'src': '/api/u/' + name})
            if p == '/api/admin/upload-audio':   # 背景音乐：mp3，或 m4a / 只有声音的 mp4（AAC），最大 60 MB
                data = self.body(60 * 1024 * 1024)
                if data[:3] == b'ID3' or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0): ext = 'mp3'
                elif data[4:8] == b'ftyp': ext = 'm4a'
                else: return self.send(400, {'error': '只收 MP3 或 M4A / MP4 音频'})
                name = hashlib.sha256(data).hexdigest()[:20] + '.' + ext
                with open(os.path.join(UPLOADS, name), 'wb') as f: f.write(data)
                return self.send(200, {'src': '/api/u/' + name, 'size': len(data)})
            return self.send(404, {'error': 'not found'})
        except (ValueError, TypeError) as e:
            return self.send(400, {'error': str(e) if isinstance(e, ValueError) and str(e) else '格式不对'})

    def do_DELETE(self):
        p = urlparse(self.path).path
        if not self.authed(): return self.send(401, {'error': '请先登录'})
        m = re.match(r'^/api/admin/diary/(d[0-9a-z]{4,22})$', p)
        if m: delete_diary(m.group(1)); return self.send(200, {'ok': True})
        m = re.match(r'^/api/admin/items/(food|street|music)/([fsm][0-9a-z]{1,40})$', p)
        if m: delete_item(m.group(1), m.group(2)); return self.send(200, {'ok': True})
        return self.send(404, {'error': 'not found'})


def cleanup():
    while True:
        try:
            with LOCK, db() as c: c.execute('DELETE FROM events WHERE ts < ?', (int(time.time()) - 400 * 86400,))
        except Exception as e: print('cleanup', e, flush=True)
        time.sleep(86400)


if __name__ == '__main__':
    threading.Thread(target=cleanup, daemon=True).start()
    print(f'bh-admin on 127.0.0.1:{PORT}, data in {DATA}, ip2region {"ok" if REGION else "off"}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
