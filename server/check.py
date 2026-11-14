"""核对服务器上的网站文件和 GitHub 上的最新版是否一致（按 server/manifest.txt 里每个文件的 sha256）。
在服务器上运行：sudo python3 /var/www/beyond-horizons/server/check.py"""
import hashlib, os, sys
ROOT = '/var/www/beyond-horizons'
man = os.path.join(ROOT, 'server', 'manifest.txt')
if not os.path.exists(man): sys.exit('没有 server/manifest.txt，没法核对')
bad, n = [], 0
for line in open(man, encoding='utf-8'):
    h, size, path = line.rstrip('\n').split('  ', 2); n += 1
    f = os.path.join(ROOT, path)
    if not os.path.isfile(f): bad.append('缺少  ' + path); continue
    if os.path.getsize(f) != int(size) or hashlib.sha256(open(f, 'rb').read()).hexdigest() != h: bad.append('不一样 ' + path)
if bad:
    print(f'有 {len(bad)} 个文件和最新版不一致（共 {n} 个）：'); print('\n'.join(bad[:40])); print('把这个截图发给我'); sys.exit(1)
print(f'核对完毕：{n} 个文件全部和最新版一致')
