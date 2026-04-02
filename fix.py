import os

files = [
    'backend/data/yahoo_fetcher.py',
    'backend/data/processor.py',
    'backend/main.py',
]

for f in files:
    if os.path.exists(f):
        t = open(f, 'r').read()
        t = t.replace('tz_localize(None)', 'tz_convert(None)')
        open(f, 'w').write(t)
        print('Fixed', f)
    else:
        print('Not found', f)
