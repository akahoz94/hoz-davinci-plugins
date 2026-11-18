# -*- coding: utf-8 -*-
"""
达芬奇开源插件目录 - 自动采集脚本
运行在 GitHub Actions 上：搜索 GitHub -> 去重 -> 严格过滤 -> 补日期 -> 更新 index.html/README.md -> 提交
"""
import os, re, json, time, urllib.request, urllib.error, urllib.parse, subprocess, sys
from datetime import datetime, timezone

REPO = 'akahoz94/hoz-davinci-plugins'
BRANCH = 'main'
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# ---------- GitHub API ----------
def gh_api(method, path, payload=None, raw=False, retries=3):
    url = 'https://api.github.com/' + path.lstrip('/')
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github.raw' if raw else 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'davinci-plugins-auto-collector',
    }
    if data: headers['Content-Type'] = 'application/json'
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and i < retries - 1:
                time.sleep(3 * (i + 1)); continue
            raise
        except Exception:
            if i < retries - 1: time.sleep(2); continue
            raise

# ---------- 搜索 ----------
QUERIES = [
    'davinci resolve plugin', 'davinci resolve dctl', 'davinci resolve fusion',
    'davinci resolve ofx', 'davinci resolve script', 'davinci resolve AI',
    'davinci resolve mcp', 'topic:davinci-resolve', 'topic:davinci-resolve-plugin',
    'topic:dctl', 'topic:openfx', 'davinci resolve 插件',
]
def search_all():
    found = {}
    for q in QUERIES:
        try:
            path = 'search/repositories?' + urllib.parse.urlencode(
                {'q': q, 'per_page': 50, 'sort': 'updated', 'order': 'desc'})
            items = json.loads(gh_api('GET', path)).get('items', [])
            for it in items:
                found[it['full_name'].lower()] = it
            print(f'  搜索 "{q}": {len(items)} 条')
            time.sleep(2)
        except Exception as e:
            print(f'  搜索 "{q}" 失败: {e}', file=sys.stderr)
    return found

# ---------- 过滤 ----------
BLOCK = re.compile(r'cracked|nulled|keygen|premium\s+studio\s+plugins?|full\s+version|license\s*key|破解|激活码|付费资源|资源站|免费下载全集', re.I)
NOISE = re.compile(r'^\s*$|中文教程|视频教程|\bcurso\b|\btutorial\b.*\bcourse\b|not a plugin|awesome list|资源合集', re.I)
DA_VINCI = re.compile(r'davinci|da vinci|resolve|\bdctl\b|openfx|\bofx\b|fusion\s*(studio|page|fuse)|blackmagic', re.I)

def too_old(it):
    pushed = (it.get('pushed_at') or '')[:10]
    return bool(pushed) and pushed < '2025-01-01'

def qualify(it):
    full = it['full_name']
    desc = (it.get('description') or '').strip()
    if not desc or len(desc) < 12: return False
    if it.get('archived') or it.get('fork'): return False
    if BLOCK.search(full) or BLOCK.search(desc): return False
    if NOISE.search(desc): return False
    if not DA_VINCI.search(full + ' ' + desc): return False
    if too_old(it): return False
    if (it.get('stargazers_count') or 0) < 2: return False
    return True

def classify(it):
    s = (it['full_name'] + ' ' + (it.get('description') or '')).lower()
    lang = (it.get('language') or '')
    if 'dctl' in s: return 'DCTL'
    if 'ofx' in s or 'openfx' in s: return 'OFX'
    if 'fuse' in s or 'fusion' in s: return 'Fusion'
    if any(k in s for k in ['subtitle','caption','whisper','tts','asr','transcri','mcp','claude','ai ','ai-','agent','auto cut','auto edit']): return 'AI'
    return 'Script'

def win_flag(it):
    s = ((it.get('description') or '') + ' ' + it['full_name']).lower()
    if 'linux' in s: return 'n', 'linux'
    if 'mac' in s or 'macos' in s or 'coreml' in s: return 'y', 'mac'
    if 'windows' in s or 'win only' in s: return 'y', 'win'
    return 'y', None

def zh_flag(it):
    return bool(re.search(r'[\u4e00-\u9fff]', (it.get('description') or '')))

def esc(s):
    return str(s).replace('\\', '\\\\').replace('"', '\\"')

def make_row(it):
    full = it['full_name']
    repo = full.split('/')[-1]
    desc = re.sub(r'\s+', ' ', (it.get('description') or '').strip())[:100]
    typ = classify(it)
    win, plat = win_flag(it)
    lang = it.get('language') or '-'
    stars = it.get('stargazers_count') or 0
    upd = (it.get('pushed_at') or '')[:10] or TODAY
    parts = [
        f'repo:"{esc(repo)}"', f'full:"{esc(full)}"',
        f'url:"https://github.com/{full}"', f'desc:"{esc(desc)}"',
        f'type:"{typ}"', f'win:"{win}"', f'lang:"{esc(lang)}"',
        f'stars:{stars}', f'updated:"{upd}"',
    ]
    if plat: parts.append(f'platform:"{plat}"')
    if zh_flag(it): parts.append('zh:true')
    return '  {' + ','.join(parts) + '},'

# ---------- 主流程 ----------
def main():
    print(f'=== 自动采集启动 {TODAY} ===')

    # 1. 读取现有 index.html
    html = gh_api('GET', f'repos/{REPO}/contents/index.html', raw=True)
    existing_fulls = set(f.lower() for f in re.findall(r'full:"([^"]+)"', html))
    print(f'现有条目: {len(existing_fulls)}')

    # 2. 搜索
    found = search_all()
    print(f'候选去重后: {len(found)}')

    # 3. 过滤 + 去重
    new_items = []
    for k, it in found.items():
        if k in existing_fulls: continue
        if not qualify(it): continue
        new_items.append(it)
    new_items.sort(key=lambda x: -(x.get('stargazers_count') or 0))
    print(f'符合条件的新项目: {len(new_items)}')
    for it in new_items[:30]:
        print(f"  + {it['full_name']} ({it.get('stargazers_count')}★)")

    if not new_items:
        print('无新增项目，跳过提交。')
        return

    # 4. 注入 DATA
    rows = '\n'.join(make_row(it) for it in new_items)
    block = f'\n  // ===== {TODAY} 自动采集（GitHub Actions） =====\n{rows}\n'
    idx = html.rindex('\n];')
    html = html[:idx] + '\n' + block + html[idx:]

    # 5. 更新统计
    total = len(existing_fulls) + len(new_items)
    html = re.sub(r'id="totalCount">\d+<', f'id="totalCount">{total}<', html)
    # meta 行日期与条数
    html = re.sub(r'\d{4}-\d{2}-\d{2} 第[一二三四]轮增补（共 \d+ 条）',
                  f'{TODAY} 自动采集（共 {total} 条）', html)
    open('index.html', 'w', encoding='utf-8').write(html)

    # 6. 更新 README
    readme = gh_api('GET', f'repos/{REPO}/contents/README.md', raw=True)
    readme = re.sub(r'\d+ 个（\d{4}-\d{2}-\d{2} 快照）', f'{total} 个（{TODAY} 快照）', readme)
    open('README.md', 'w', encoding='utf-8').write(readme)

    # 7. 校验 DATA 语法
    m = re.search(r'const DATA = \[([\s\S]*?)\n\];', html)
    if not m: raise RuntimeError('找不到 DATA 数组')
    count = len(re.findall(r'\{repo:"', m.group(1)))
    print(f'校验 DATA 条目: {count}')

    # 8. 提交（Git Data API，不依赖本地 git push）
    def make_blob(path):
        import base64
        content = open(path, 'rb').read()
        res = gh_api('POST', f'repos/{REPO}/git/blobs',
                     {'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64'})
        return json.loads(res)['sha']

    ref = json.loads(gh_api('GET', f'repos/{REPO}/git/ref/heads/{BRANCH}'))
    commit_sha = ref['object']['sha']
    commit = json.loads(gh_api('GET', f'repos/{REPO}/git/commits/{commit_sha}'))
    base_tree = commit['tree']['sha']
    tree = json.loads(gh_api('POST', f'repos/{REPO}/git/trees', {
        'base_tree': base_tree,
        'tree': [
            {'path': 'index.html', 'mode': '100644', 'type': 'blob', 'sha': make_blob('index.html')},
            {'path': 'README.md', 'mode': '100644', 'type': 'blob', 'sha': make_blob('README.md')},
        ]}))['sha']
    names = ', '.join(it['full_name'] for it in new_items[:5])
    more = f' 等 {len(new_items)} 项' if len(new_items) > 5 else ''
    msg = f'自动采集新增 {len(new_items)} 项插件（{TODAY}）：{names}{more}'
    new_commit = json.loads(gh_api('POST', f'repos/{REPO}/git/commits', {
        'message': msg, 'tree': tree, 'parents': [commit_sha]}))['sha']
    gh_api('PATCH', f'repos/{REPO}/git/refs/heads/{BRANCH}', {'sha': new_commit})
    print(f'提交成功: {new_commit[:10]}')
    print(f'新增 {len(new_items)} 项，总数 {total}')

if __name__ == '__main__':
    main()
