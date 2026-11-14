"""让你的域名打开 Beyond Horizons。在服务器上运行（不写域名就用 www.howardleong.work 和 howardleong.work）：
    sudo python3 /var/www/beyond-horizons/server/domain.py [域名 ...]
做的事：把 nginx 里现在 8080 端口那个站点的配置复制一份，改成 80 端口、用这些域名打开；8080 照旧能用。
如果别的站点（比如原来的网页）的配置里也写了这些域名，就把这些域名从那里拿掉（原文件先备份），免得两个站点抢同一个域名。
最后用 nginx -t 检查，不通过就全部恢复原样，什么都不改。可以重复运行。"""
import glob, os, re, shutil, subprocess, sys, time
D = os.environ.get('NGX', '/etc/nginx'); TEST = os.environ.get('NGX_TEST')
HOSTS = [h.lower() for h in sys.argv[1:]] or ['www.howardleong.work', 'howardleong.work']
MARK = '# Beyond Horizons (server/domain.py)'


def blocks(txt):
    for m in re.finditer(r'\bserver\s*\{', txt):
        i, dep = m.end(), 1
        while dep and i < len(txt): dep += {'{': 1, '}': -1}.get(txt[i], 0); i += 1
        yield m.start(), i


avail = os.path.isdir(D + '/sites-available')
OUT = D + ('/sites-available/beyond-horizons-domain' if avail else '/conf.d/beyond-horizons-domain.conf')
LINK = D + '/sites-enabled/beyond-horizons-domain'
files = [f for f in sorted(set(glob.glob(D + '/sites-enabled/*') + glob.glob(D + '/conf.d/*.conf') + [D + '/nginx.conf'])) if os.path.realpath(f) != os.path.realpath(OUT)]
text = {}
for f in files:
    try: text[f] = open(f, encoding='utf-8', errors='replace').read()
    except Exception: pass
src = next(((f, t[a:b]) for f, t in text.items() for a, b in blocks(t) if re.search(r'^\s*listen\s+[^;#]*\b8080\b', t[a:b], re.M)), None)
if not src: sys.exit('没找到监听 8080 的 nginx 配置，请把 sudo nginx -T 的输出截图发给我')
f8080, b = src
nb = re.sub(r'^(\s*listen\s+)([^;]*?)\b8080\b([^;]*);', lambda m: m.group(1) + (m.group(2) + '80' + m.group(3)).replace('default_server', '').rstrip() + ';', b, flags=re.M)
nb = re.sub(r'[ \t]+;', ';', nb)
if re.search(r'^\s*server_name\s', nb, re.M): nb = re.sub(r'^(\s*)server_name\s[^;]*;', lambda m: m.group(1) + 'server_name ' + ' '.join(HOSTS) + ';', nb, count=1, flags=re.M)
else: nb = re.sub(r'(^\s*listen\s[^;]*;)', lambda m: m.group(1) + '\n    server_name ' + ' '.join(HOSTS) + ';', nb, count=1, flags=re.M)
# other sites that already answer to these names: take the names out of their server_name (backed up first)
backup = '/root/nginx-backup-' + time.strftime('%Y%m%d-%H%M%S') if not TEST else D + '/_backup'
changed = []
for f, t in text.items():
    def fix(m):
        names = m.group(2).split(); keep = [n for n in names if n.lower() not in HOSTS]
        return m.group(0) if keep == names else m.group(1) + 'server_name ' + (' '.join(keep) or '_') + ';'
    t2 = re.sub(r'^(\s*)server_name\s+([^;]*);', fix, t, flags=re.M)
    if t2 != t:
        real = os.path.realpath(f); os.makedirs(backup, exist_ok=True); shutil.copy2(real, os.path.join(backup, os.path.basename(real)))
        open(real, 'w', encoding='utf-8').write(t2); changed.append(real)
        print('原来', real, '里写着', '/'.join(HOSTS), '：已从那里拿掉（备份在', backup + '）')
open(OUT, 'w').write(MARK + ' — copied from the :8080 site in ' + f8080 + '\n' + nb + '\n')
if avail and not os.path.lexists(LINK): os.symlink(OUT, LINK)
print('新站点配置', OUT, '：'); print(nb)
if TEST: sys.exit(0)
r = subprocess.run(['nginx', '-t'], capture_output=True, text=True)
if r.returncode:
    print(r.stderr)
    for real in changed: shutil.copy2(os.path.join(backup, os.path.basename(real)), real)
    os.remove(OUT)
    if avail and os.path.islink(LINK): os.remove(LINK)
    sys.exit('nginx 配置检查没通过，已经全部恢复原样，什么都没改。把上面的报错截图发给我')
subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
print('成功：nginx 已重新加载，', ' 和 '.join(HOSTS), '现在打开 Beyond Horizons')
