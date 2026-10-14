#!/usr/bin/env python3
"""Switch the image-generation stack between profiles in config/image-model-profiles.json.

Flips, atomically and reversibly:
  - extension_settings.sd.*   in settings.json  (workflow, checkpoint, prompts, sampler...)
  - the image-guidance block  in Galileo.png    (Danbooru tags <-> natural-language prose)

Both profiles stay installed; nothing is deleted. Reverting is just the other name.

    scripts/switch-image-model.py --status
    scripts/switch-image-model.py pony
    scripts/switch-image-model.py flux

After switching, hard-reload any open SillyTavern tab: a stale tab holds the old
settings in memory and will write them back over settings.json.
"""
import json, struct, base64, zlib, sys, shutil, collections, datetime, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = os.path.join(ROOT, 'config/image-model-profiles.json')
SETTINGS = os.path.join(ROOT, 'sillytavern/data/default-user/settings.json')
CARD     = os.path.join(ROOT, 'sillytavern/data/default-user/characters/Galileo.png')
BACKUPS  = os.path.join(ROOT, 'backups/image-model-switch')
MARKER   = "ISTRUZIONI PER IL FUNCTION CALLING (Fase 3):"


def png_chunks(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    i = 8
    while i < len(data):
        ln = struct.unpack('>I', data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        yield typ, data[i + 8:i + 8 + ln]
        i += 12 + ln


def read_card_tail():
    """Return the current image-guidance block from the card's 'chara' chunk."""
    for typ, body in png_chunks(open(CARD, 'rb').read()):
        if typ == b'tEXt':
            k, _, v = body.partition(b'\x00')
            if k == b'chara':
                c = json.loads(base64.b64decode(v))
                sp = c.get('data', c)['system_prompt']
                if MARKER not in sp:
                    sys.exit(f'! card system_prompt has no {MARKER!r} marker; refusing to guess')
                return MARKER + sp.split(MARKER, 1)[1]
    sys.exit('! no chara chunk in card')


def write_card_tail(new_tail):
    """Rewrite the guidance block in BOTH tEXt chunks; they must stay in sync."""
    data = open(CARD, 'rb').read()
    out = bytearray(data[:8])
    touched = []
    for typ, body in png_chunks(data):
        if typ == b'tEXt':
            k, _, v = body.partition(b'\x00')
            if k in (b'chara', b'ccv3'):
                c = json.loads(base64.b64decode(v), object_pairs_hook=collections.OrderedDict)
                d = c.get('data', c)
                head = d['system_prompt'].split(MARKER, 1)[0]
                d['system_prompt'] = head + new_tail
                body = k + b'\x00' + base64.b64encode(
                    json.dumps(c, ensure_ascii=False).encode('utf-8'))
                touched.append(k.decode())
        out += struct.pack('>I', len(body)) + typ + body
        out += struct.pack('>I', zlib.crc32(typ + body) & 0xFFFFFFFF)
    if sorted(touched) != ['ccv3', 'chara']:
        sys.exit(f'! expected to rewrite chara+ccv3, rewrote {touched}')
    open(CARD, 'wb').write(bytes(out))
    return touched


def detect(profiles):
    """Which profile is live? Requires sd settings AND card to agree."""
    sd = json.load(open(SETTINGS))['extension_settings']['sd']
    tail = read_card_tail()
    hits = []
    for name, p in profiles.items():
        sd_match = all(sd.get(k) == v for k, v in p['sd'].items())
        hits.append((name, sd_match, tail == p['card_tail']))
    for name, s, c in hits:
        if s and c:
            return name, hits
    return None, hits


def main():
    profiles = json.load(open(PROFILES), object_pairs_hook=collections.OrderedDict)
    arg = sys.argv[1] if len(sys.argv) > 1 else '--status'

    if arg in ('--status', '-s', 'status'):
        cur, hits = detect(profiles)
        print(f'active profile: {cur or "MIXED / custom"}')
        for name, s, c in hits:
            print(f'  {name:5}  settings={"match" if s else "differ"}  card={"match" if c else "differ"}'
                  f'   {profiles[name]["label"]}')
        if cur is None:
            print('\n  (settings and card disagree, or values were hand-edited --'
                  '\n   run with a profile name to force a consistent state)')
        return

    if arg not in profiles:
        sys.exit(f'usage: {sys.argv[0]} [--status|{"|".join(profiles)}]')

    p = profiles[arg]
    ckpt = os.path.join(ROOT, 'comfyui/models/checkpoints', p['sd']['model'])
    if not os.path.exists(ckpt):
        sys.exit(f'! checkpoint missing: {ckpt}\n  refusing to switch to a model that is not installed')
    wf = os.path.join(ROOT, 'sillytavern/data/default-user/user/workflows', p['sd']['comfy_workflow'])
    if not os.path.exists(wf):
        sys.exit(f'! workflow missing: {wf}')

    os.makedirs(BACKUPS, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    for src in (SETTINGS, CARD):
        dst = os.path.join(BACKUPS, f'{os.path.basename(src)}.{stamp}')
        shutil.copy2(src, dst)
    print(f'backed up settings.json + Galileo.png to backups/image-model-switch/*.{stamp}')

    s = json.load(open(SETTINGS), object_pairs_hook=collections.OrderedDict)
    sd = s['extension_settings']['sd']
    for k, v in p['sd'].items():
        if sd.get(k) != v:
            old = sd.get(k)
            shown = (repr(old)[:44] + '..') if len(repr(old)) > 46 else repr(old)
            new = (repr(v)[:44] + '..') if len(repr(v)) > 46 else repr(v)
            print(f'  sd.{k:<16} {shown} -> {new}')
        sd[k] = v
    json.dump(s, open(SETTINGS, 'w'), indent=4, ensure_ascii=False)
    open(SETTINGS, 'a').write('\n')

    if read_card_tail() != p['card_tail']:
        print(f'  card guidance block -> {len(p["card_tail"])} chars ({arg})')
        print('  rewrote tEXt chunks:', ', '.join(write_card_tail(p['card_tail'])))

    cur, _ = detect(profiles)
    if cur != arg:
        sys.exit(f'! verification failed: expected {arg}, detected {cur}')
    print(f'\nactive profile: {arg}  ({p["label"]})')
    if p.get('notes'):
        print('  note:', p['notes'])
    print('\nHard-reload any open SillyTavern tab before using it.')


if __name__ == '__main__':
    main()
