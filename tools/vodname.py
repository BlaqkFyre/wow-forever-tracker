#!/usr/bin/env python3
"""Find a streamer's WoW Forever character by reading their recent Twitch VODs.

Grabs a few frames from the latest WoW Forever broadcasts, reads all on-screen
text with Tesseract OCR, and tries every two-word name it sees against the
official Armory. Names that show up in several frames (the player's own unit
frame) win over names that appear once (chat, party members, nameplates).
Needs ffmpeg and tesseract-ocr on the machine.
"""
import collections, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request

GQL = "https://gql.twitch.tv/gql"
CID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web client id
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(GQL, data=body, headers={**UA, "Client-Id": CID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(url, binary=True):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")


def recent_vods(login, n=6):
    q = """query($login:String!,$n:Int!){user(login:$login){displayName videos(first:$n,type:ARCHIVE,sort:TIME){edges{node{id title lengthSeconds createdAt game{name}}}}}}"""
    d = gql(q, {"login": login, "n": n}).get("data", {}).get("user")
    if not d: return None, []
    vids = [e["node"] for e in (d.get("videos") or {}).get("edges") or []]
    wow = [v for v in vids if v.get("game") and "warcraft" in (v["game"]["name"] or "").lower()]
    return d.get("displayName"), (wow or vids)


def vod_playlist(vid):
    q = """query($id:ID!){videoPlaybackAccessToken(id:$id,params:{platform:"web",playerBackend:"mediaplayer",playerType:"site"}){value signature}}"""
    t = gql(q, {"id": vid})["data"]["videoPlaybackAccessToken"]
    master = fetch(f"https://usher.ttvnw.net/vod/{vid}.m3u8?" + urllib.parse.urlencode(
        {"sig": t["signature"], "token": t["value"], "allow_source": "true", "player": "twitchweb"}), binary=False)
    urls = [l for l in master.splitlines() if l.startswith("http")]
    if not urls: raise RuntimeError("no playlist")
    best = urls[0]  # first variant is the source/highest quality
    pl = fetch(best, binary=False)
    base = best.rsplit("/", 1)[0] + "/"
    segs = [l for l in pl.splitlines() if l and not l.startswith("#")]
    m = re.search(r'#EXT-X-MAP:URI="([^"]+)"', pl)  # fragmented-MP4 VODs need their init segment
    init = (m.group(1) if m.group(1).startswith("http") else base + m.group(1)) if m else None
    return [s if s.startswith("http") else base + s for s in segs], init


def frames_from(vid, k, tmp):
    segs, init = vod_playlist(vid)
    if not segs: return []
    head = fetch(init) if init else b""
    out = []
    picks = sorted({int(len(segs) * f) for f in [0.15, 0.3, 0.45, 0.6, 0.75, 0.9][:k]})
    for i in picks:
        seg = os.path.join(tmp, f"{vid}-{i}.ts"); png = seg + ".png"
        try:
            open(seg, "wb").write(head + fetch(segs[min(i, len(segs) - 1)]))
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", seg, "-frames:v", "1", "-vf", "scale=1920:-2", png], check=True, timeout=60)
            out.append(png)
        except Exception as e:
            print("frame failed", vid, i, e, file=sys.stderr)
        finally:
            if os.path.exists(seg): os.remove(seg)
    return out


def ocr_words(png):
    """All OCR lines from the frame (upscaled, greyscale), as lists of words."""
    big = png + ".x2.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", png, "-vf", "scale=iw*2:ih*2,format=gray", big], check=True, timeout=60)
    lines = []
    for psm in ("11",):
        r = subprocess.run(["tesseract", big, "-", "--psm", psm], capture_output=True, text=True, timeout=120)
        lines += [l for l in r.stdout.splitlines() if l.strip()]
    os.remove(big)
    return lines


STOP = set("""damage done healing taken threat dps hps details skada recount meter overall current segment total party raid guild
general trade local defense combat log quest quests level target focus player group chat whisper say yell world looking for lfg
auction house main hand off ranged hit crit miss dodge parry block resist absorb gold silver copper bag bags bank map minimap
mana health rage energy focus combo points buff buffs debuff debuffs spell book talents talent character reputation honor
the and you your are with from into this that has have was will not now new old all any one two three four five six seven
eight nine ten aya ya vek kek lol omegalul pog poggers lul kappa sub subs follow follows prime gifted bits cheer hype train
chatters viewers stream live twitch discord youtube sponsor brought by today tomorrow press click enter accept decline
alliance horde stormwind orgrimmar ironforge darnassus undercity thunder bluff time played day days hours minutes""".split())


def name_pairs(lines):
    pairs = set()
    for l in lines:
        words = re.findall(r"[A-Z][a-zà-ÿ']{1,13}", l)
        for a, b in zip(words, words[1:]):
            if a.lower() in STOP or b.lower() in STOP or a == b: continue
            pairs.add(f"{a} {b}")
    return pairs


def find_character(login, check, keys=(), max_checks=45):
    """check(name) -> (name, region, level) if the name is a real Forever character, else None.
    Returns (hits, display_name): hits is a list of (name, region, level, frames_seen, matches_channel), best first."""
    disp, vids = recent_vods(login)
    if not vids: return [], disp
    counts = collections.Counter()
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for v in vids[:3]:
            try: frames += frames_from(v["id"], 3, tmp)
            except Exception as e: print("vod failed", v["id"], e, file=sys.stderr)
            if len(frames) >= 6: break
        for f in frames:
            for p in name_pairs(ocr_words(f)): counts[p] += 1
    if not counts: return [], disp
    keys = [k.lower() for k in keys if k]
    def keyed(p):
        w = p.lower().split()
        return any(k in p.lower().replace(" ", "") or any(len(x) >= 3 and x in k for x in w) for k in keys)
    def score(p):
        return counts[p] * 10 + (60 if keyed(p) else 0)
    ranked = sorted(counts, key=score, reverse=True)
    found = []
    for p in ranked[:max_checks]:
        hit = check(p)
        if hit:
            found.append((hit[0], hit[1], hit[2], counts[p], keyed(p), score(p)))
            if len(found) >= 6: break
    found.sort(key=lambda x: -x[5])
    return [f[:5] for f in found], disp


if __name__ == "__main__":
    import refresh
    def check(name):
        base = name.lower().replace(" ", "-")
        for slug in (base, "eu/" + base):
            try:
                c = refresh.state(refresh.armory_path(slug))["character"]
                return (c["name"] + (" " + c["surname"] if c.get("surname") else ""), "eu" if "/" in slug else "us", c["level"])
            except Exception:
                pass
        return None
    for login in sys.argv[1:]:
        print(login, find_character(login, check, keys=[login]), flush=True)
