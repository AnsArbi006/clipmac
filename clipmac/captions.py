"""Local, word-timed ASS captions with stable layout and a moving highlight."""
import math
import re
from functools import lru_cache
from pathlib import Path

VERSION = 2
FONT_NAME = 'Arial'
FONT_PATH = Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')
MAX_WIDTH = 800
CENTER_X = 500
CENTER_Y = 1370


def ass_time(seconds):
    cs = max(0, round(seconds * 100))
    return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'


def safe_ass(text):
    return re.sub(r'[\\{}\r\n]', ' ', str(text)).strip()


@lru_cache(maxsize=80)
def font(size, font_path=None):
    from PIL import ImageFont
    path = Path(font_path) if font_path is not None else FONT_PATH
    if not path.is_file():
        raise RuntimeError('Untertitel-Schrift Arial Bold fehlt. Bitte die lokale Schriftinstallation prüfen.')
    return ImageFont.truetype(str(path), size)


def groups(transcript):
    """Use real word timestamps only, split at pauses and sentence boundaries."""
    words = []
    for segment in transcript.get('segments', []):
        for w in segment.get('words', []):
            try:
                a, b = float(w['start']), float(w['end'])
                text = safe_ass(w['word'])
                if text and math.isfinite(a) and math.isfinite(b) and 0 <= a < b:
                    words.append({'start': a, 'end': b, 'word': text})
            except (KeyError, ValueError, TypeError):
                continue
    words.sort(key=lambda w: (w['start'], w['end']))
    # Prevent overlapping ASR segments producing two simultaneous active words.
    for i in range(len(words)-1):
        words[i]['end'] = min(words[i]['end'], words[i+1]['start'])
    words = [w for w in words if round(w['end']*100) > round(w['start']*100)]
    result, group = [], []
    for w in words:
        if group and (len(group) >= 4 or w['start']-group[-1]['end'] > .42
                      or w['end']-group[0]['start'] > 2.2
                      or len(' '.join(x['word'] for x in group)) + len(w['word']) > 34
                      or re.search(r'[.!?]["»”]*$', group[-1]['word'])):
            result.append(group)
            group = []
        group.append(w)
    if group:
        result.append(group)
    return result


def layout(group, *, font_path=None):
    """Measure actual font advances, center at most two lines in the safe area."""
    texts = [w['word'].upper() for w in group]
    for size in range(84, 11, -2):
        f = font(size) if font_path is None else font(size, font_path)
        widths = [float(f.getlength(t)) for t in texts]
        gap = 30
        def width(indices):
            return sum(widths[i] for i in indices) + gap * max(0, len(indices)-1)
        indices = list(range(len(texts)))
        if width(indices) <= MAX_WIDTH:
            lines = [indices]
            break
        choices = [(indices[:i], indices[i:]) for i in range(1,len(indices))]
        valid = [pair for pair in choices if max(map(width,pair)) <= MAX_WIDTH]
        if valid:
            lines = min(valid, key=lambda pair: abs(width(pair[0])-width(pair[1])))
            break
    else:
        raise ValueError('Ein erkanntes Wort passt nicht sicher ins Untertitelformat.')
    positions = []
    for line_no, indices in enumerate(lines):
        x = CENTER_X - width(indices)/2
        y = CENTER_Y + (line_no-(len(lines)-1)/2)*108
        for i in indices:
            positions.append({'index': i, 'text': texts[i], 'x': x+widths[i]/2,
                              'y': y, 'width': widths[i], 'size': size})
            x += widths[i]+gap
    return positions


def rounded_box(width, height, radius=15):
    w,h,r = round(width),round(height),radius
    return (f'm {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} '
            f'b {w} {h} {w} {h} {w-r} {h} l {r} {h} b 0 {h} 0 {h} 0 {h-r} '
            f'l 0 {r} b 0 0 0 0 {r} 0')


def write_subtitles(path, transcript, *, font_path=None):
    events, srt, bounds = [], [], []
    def event(layer,a,b,tags,text):
        if round(b*100) > round(a*100):
            events.append(f'Dialogue: {layer},{ass_time(a)},{ass_time(b)},Caption,,0,0,0,,{{{tags}}}{text}')
    def stamp(t):
        ms = round(t*1000)
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    for group in groups(transcript):
        a,b = group[0]['start'],group[-1]['end']
        positions = layout(group) if font_path is None else layout(group, font_path=font_path)
        for p in positions:
            pos = rf'\an5\pos({p["x"]:.1f},{p["y"]:.1f})\fs{p["size"]}'
            event(1,a,b,pos+r'\fad(45,35)\fscx97\fscy97\t(0,80,\fscx100\fscy100)',p['text'])
            i = p['index']; word = group[i]
            end = min(group[i+1]['start'],word['end']+.12) if i+1<len(group) else b
            w,h = p['width']+28,96
            x,y = p['x']-w/2,p['y']-h/2
            event(2,word['start'],end,rf'\an7\pos({x:.1f},{y:.1f})\p1\bord0\shad0\1c&H44FFB7&\fad(25,0)',rounded_box(w,h))
            event(3,word['start'],end,pos+r'\1c&H0B160D&\bord0\shad0\fscx104\fscy104\t(0,70,\fscx100\fscy100)',p['text'])
            bounds.append({'start':word['start'],'end':end,'x':x,'y':y,'width':w,'height':h,'word':word['word']})
        srt.append(f'{len(srt)+1}\n{stamp(a)} --> {stamp(b)}\n'+ ' '.join(w['word'] for w in group)+'\n')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,84,&H00FFFFFF,&H0044FFB7,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,90,160,380,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    path.with_suffix('.srt').write_text('\n'.join(srt),encoding='utf-8')
    return {'version':VERSION,'style':'word-highlight','groups':len(srt),'words':len(bounds),'bounds':bounds}
