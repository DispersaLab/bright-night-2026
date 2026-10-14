#!/usr/bin/env python3
"""Build a SillyTavern character card PNG from a JSON content file.

The schema of a v2/v3 card is large, fussy and mostly boilerplate, so rather than
re-declaring it we clone an existing card as a structural template and substitute
only the content fields. Every extension key SillyTavern expects therefore
survives untouched.

    scripts/build-character-card.py --content config/galileo-card.json \
        --template sillytavern/data/default-user/characters/Cortana.png \
        --avatar   assets/galileo-placeholder.png \
        --out      sillytavern/data/default-user/characters/Galileo.png

The image-guidance block (everything from MARKER onwards in system_prompt) is
copied verbatim from the template and is never taken from the content file.
Rewording it took tool calling from 12/12 to 0/12 on 2026-08-31.

Both the 'chara' (v2) and 'ccv3' (v3) tEXt chunks are written and kept in sync;
SillyTavern prefers ccv3 and silently falls back to chara, so a card whose two
chunks disagree behaves differently depending on which reader you ask.
"""
import argparse, base64, collections, datetime, json, os, struct, sys, zlib

MARKER = "ISTRUZIONI PER IL FUNCTION CALLING (Fase 3):"
CRLF_FIELDS = ('description', 'first_mes', 'scenario', 'system_prompt')


def png_chunks(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    i = 8
    while i < len(data):
        ln = struct.unpack('>I', data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        yield typ, data[i + 8:i + 8 + ln]
        i += 12 + ln


def load_card(path):
    """Return the decoded 'chara' payload of a card PNG, order preserved."""
    for typ, body in png_chunks(open(path, 'rb').read()):
        if typ == b'tEXt':
            k, _, v = body.partition(b'\x00')
            if k == b'chara':
                return json.loads(base64.b64decode(v),
                                  object_pairs_hook=collections.OrderedDict)
    sys.exit(f'! no chara chunk in {path}')


def crlf(s):
    """Normalise to CRLF, the line ending the template cards already use."""
    return s.replace('\r\n', '\n').replace('\n', '\r\n')


def build_entry(template_entry, spec, uid):
    """Clone a lorebook entry's full schema, swapping in new content."""
    e = collections.OrderedDict(template_entry)
    e['id'] = uid
    e['keys'] = spec['keys']
    e['comment'] = spec['comment']
    e['content'] = spec['content']
    ext = collections.OrderedDict(e.get('extensions', {}))
    ext['display_index'] = uid
    e['extensions'] = ext
    return e


def _strings(o, path=''):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f'{path}/{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, f'{path}[{i}]')
    elif isinstance(o, str):
        yield path, o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--content', required=True, help='JSON content file')
    ap.add_argument('--template', required=True, help='existing card PNG to clone the schema from')
    ap.add_argument('--avatar', help='PNG to use as the card image (default: the template image)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--world-template', help='existing worlds/*.json to clone the entry schema from')
    ap.add_argument('--world-out', help='write the standalone lorebook here too')
    a = ap.parse_args()

    spec = json.load(open(a.content, encoding='utf-8'))
    tpl = load_card(a.template)
    tpl_data = tpl.get('data', tpl)

    # The one thing we must not author ourselves.
    tpl_sp = tpl_data['system_prompt']
    if 'system_prompt_tail' in spec:
        tail = spec['system_prompt_tail']
        if not tail.startswith(MARKER):
            sys.exit(f'! system_prompt_tail must start with {MARKER!r}')
        tail = crlf(tail)
    else:
        if MARKER not in tpl_sp:
            sys.exit(f'! template system_prompt has no {MARKER!r}; refusing to guess')
        tail = MARKER + tpl_sp.split(MARKER, 1)[1]

    fields = {
        'name': spec['name'],
        'description': spec['description'],
        'first_mes': spec['first_mes'],
        'scenario': spec['scenario'],
        'system_prompt': spec['system_prompt_head'].rstrip('\r\n') + '\n\n' + tail,
        'personality': '',
        'mes_example': '',
    }
    for k in CRLF_FIELDS:
        fields[k] = crlf(fields[k])

    card = collections.OrderedDict(tpl)
    data = collections.OrderedDict(tpl_data)

    for k, v in fields.items():
        if k in card and k != 'data':
            card[k] = v
        data[k] = v

    # Per-instance fields inherited from the template point at the template's own
    # history. 'chat' in particular would make SillyTavern open the wrong log.
    now = datetime.datetime.now()
    card['chat'] = f"{spec['name']} - {now:%Y-%m-%d@%Hh%Mm%Ss}{now.microsecond // 1000:03d}ms"
    card['create_date'] = now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'
    card['avatar'] = 'none'
    card['fav'] = False

    card['creatorcomment'] = spec['creator_notes']
    data['creator_notes'] = spec['creator_notes']
    data['character_version'] = spec['character_version']
    data['extensions'] = collections.OrderedDict(data.get('extensions', {}))
    data['extensions']['world'] = spec['world']

    book = collections.OrderedDict(data['character_book'])
    tpl_entry = book['entries'][0]
    book['name'] = spec['character_book_name']
    book['entries'] = [build_entry(tpl_entry, s, i)
                       for i, s in enumerate(spec['character_book'])]
    data['character_book'] = book
    card['data'] = data

    v2 = json.loads(json.dumps(card), object_pairs_hook=collections.OrderedDict)
    v2['spec'], v2['spec_version'] = 'chara_card_v2', '2.0'
    v3 = json.loads(json.dumps(card), object_pairs_hook=collections.OrderedDict)
    v3['spec'], v3['spec_version'] = 'chara_card_v3', '3.0'

    payload = {
        b'chara': base64.b64encode(json.dumps(v2, ensure_ascii=False).encode('utf-8')),
        b'ccv3': base64.b64encode(json.dumps(v3, ensure_ascii=False).encode('utf-8')),
    }

    src = a.avatar or a.template
    out = bytearray(open(src, 'rb').read()[:8])
    written = []
    for typ, body in png_chunks(open(src, 'rb').read()):
        if typ == b'tEXt':
            k, _, _ = body.partition(b'\x00')
            if k in payload:
                continue                       # drop any inherited card chunk
        if typ == b'IEND':                     # inject ours immediately before IEND
            for k in (b'chara', b'ccv3'):
                b = k + b'\x00' + payload[k]
                out += struct.pack('>I', len(b)) + b'tEXt' + b
                out += struct.pack('>I', zlib.crc32(b'tEXt' + b) & 0xFFFFFFFF)
                written.append(k.decode())
        out += struct.pack('>I', len(body)) + typ + body
        out += struct.pack('>I', zlib.crc32(typ + body) & 0xFFFFFFFF)

    if sorted(written) != ['ccv3', 'chara']:
        sys.exit(f'! expected to write chara+ccv3, wrote {written}')

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'wb').write(bytes(out))

    if a.world_out:
        if not a.world_template:
            sys.exit('! --world-out needs --world-template')
        wt = json.load(open(a.world_template, encoding='utf-8'))
        proto = list(wt['entries'].values())[0]
        entries = collections.OrderedDict()
        for i, s_ in enumerate(spec['character_book']):
            e = collections.OrderedDict(proto)
            e['key'], e['keysecondary'] = s_['keys'], []
            e['comment'], e['content'] = s_['comment'], s_['content']
            e['uid'] = e['displayIndex'] = i
            e['extensions'] = collections.OrderedDict(proto.get('extensions', {}))
            e['extensions']['display_index'] = i
            entries[str(i)] = e
        world = collections.OrderedDict(entries=entries, originalData=collections.OrderedDict(
            entries=book['entries'], name=spec['character_book_name']))
        os.makedirs(os.path.dirname(a.world_out), exist_ok=True)
        with open(a.world_out, 'w', encoding='utf-8') as f:
            json.dump(world, f, ensure_ascii=False, indent=4)
        print(f'wrote {a.world_out}  ({len(entries)} entries)')

    check = load_card(a.out)
    assert check['data']['name'] == spec['name']
    assert MARKER in check['data']['system_prompt']
    assert check['data']['system_prompt'].endswith(tail)
    stale = [p for p, v in _strings(check) if 'Cortana' in v and 'creator' not in p]
    if stale:
        sys.exit(f'! template text leaked into the new card: {stale}')
    print(f'wrote {a.out}  ({len(out)} bytes)')
    print(f'  name            {check["data"]["name"]}')
    print(f'  system_prompt   {len(check["data"]["system_prompt"])} chars '
          f'({len(tail)} of them the verbatim guidance block)')
    print(f'  lorebook        {check["data"]["character_book"]["name"]}: '
          f'{len(check["data"]["character_book"]["entries"])} entries')
    print(f'  world           {check["data"]["extensions"]["world"]}')


if __name__ == '__main__':
    main()
