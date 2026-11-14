"""让 map.howardleong.work 打开 Beyond Horizons（在服务器上运行：sudo python3 /var/www/beyond-horizons/server/map-domain.py）
把 nginx 里现在 8080 端口那个站点的配置复制一份，改成 80 端口、域名 map.howardleong.work；原来的站点和 8080 都不动。
nginx 配置检查不通过就自动撤回，什么都不改。可以重复运行。"""
import glob, os, re, subprocess, sys
D = os.environ.get('NGX', '/etc/nginx'); HOST = 'map.howardleong.work'; TEST = os.environ.get('NGX_TEST')
def blocks(txt):
    for m in re.finditer(r'\bserver\s*\{', txt):
        i, dep = m.end(), 1
        while dep and i < len(txt): dep += {'{': 1, '}': -1}.get(txt[i], 0); i += 1
        yield txt[m.start():i]
src = None
for f in sorted(glob.glob(D + '/sites-enabled/*') + glob.glob(D + '/conf.d/*.conf') + [D + '/nginx.conf']):
    try: t = open(f, encoding='utf-8', errors='replace').read()
    except Exception: continue
    for b in blocks(t):
        if re.search(r'^\s*listen\s+[^;#]*\b8080\b', b, re.M) and HOST not in b: src = (f, b); break
    if src: break
if not src: sys.exit('没找到监听 8080 的 nginx 配置，请把 sudo nginx -T 的输出发给我')
f, b = src
nb = re.sub(r'^(\s*listen\s+)([^;]*?)\b8080\b([^;]*);', lambda m: m.group(1) + (m.group(2) + '80' + m.group(3)).replace('default_server', '').rstrip() + ';', b, flags=re.M)
nb = re.sub(r'\s+;', ';', nb)
if re.search(r'^\s*server_name\s', nb, re.M): nb = re.sub(r'^(\s*)server_name\s[^;]*;', r'\1server_name ' + HOST + ';', nb, count=1, flags=re.M)
else: nb = re.sub(r'(^\s*listen\s[^;]*;)', r'\1\n    server_name ' + HOST + ';', nb, count=1, flags=re.M)
avail = os.path.isdir(D + '/sites-available')
out = D + ('/sites-available/' if avail else '/conf.d/') + HOST + ('' if avail else '.conf')
open(out, 'w').write('# Beyond Horizons on ' + HOST + ' (copied from the :8080 site in ' + f + ')\n' + nb + '\n')
link = D + '/sites-enabled/' + HOST
if avail and not os.path.exists(link): os.symlink(out, link)
print('从', f, '复制了 8080 那个站点 →', out); print(nb)
if TEST: sys.exit(0)
r = subprocess.run(['nginx', '-t'], capture_output=True, text=True)
if r.returncode:
    print(r.stderr); os.remove(out)
    if avail and os.path.islink(link): os.remove(link)
    sys.exit('nginx 配置检查没通过，已撤回，没有改动任何东西。把上面的报错发给我')
subprocess.run(['systemctl', 'reload', 'nginx'], check=True); print('nginx 已重新加载：', HOST, '现在指向 Beyond Horizons')
