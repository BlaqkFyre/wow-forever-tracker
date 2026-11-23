#!/usr/bin/env python3
"""Refresh the WoW Forever streamer cards from the official Armory.

Run by .github/workflows/refresh.yml on a schedule, on demand, and when someone
opens an "Add a streamer" or "Remove a streamer" issue. Writes:
  roster.json, gear-data.js, chars.js, events.js, history.json,
  sprite.webp, showcase.webp, talents.webp, renders/<slug>.webp
and updates the ROSTER block, version strings and "checked" time in index.html.
"""
import hashlib, io, json, math, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
ARM = "https://worldofwarcraft.blizzard.com/en-us/forever/"
ICON = "https://render.worldofwarcraft.com/forever-us/icons/56/{}.jpg"
SYD = ZoneInfo("Australia/Sydney")
Q = {"POOR": 0, "COMMON": 1, "UNCOMMON": 2, "RARE": 3, "EPIC": 4, "LEGENDARY": 5, "ARTIFACT": 6, "HEIRLOOM": 7}
QNAME = ["poor", "common", "uncommon", "rare", "epic", "legendary", "artifact", "heirloom"]
STAND = [0, 0, 0, 0, 3000, 9000, 21000, 42000]
STAT_KEYS = {"health": "hp", "mana": "mp", "strength": "str", "agility": "agi", "stamina": "sta", "intellect": "int",
             "armor": "arm", "attack-power": "ap", "spell-power": "sp", "critical-strike": "crit", "dodge": "dodge",
             "parry": "parry", "block": "block", "mana-regen": "mp5"}


def get(url, tries=4):
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read()
        except Exception as e:
            if t == tries - 1:
                raise
            time.sleep(1.5 * (t + 1))


def armory_path(slug):
    return ARM + (slug.replace("/", "/armory/character/", 1) if "/" in slug else "us/armory/character/" + slug)


def state(url):
    html = get(url).decode("utf-8", "replace")
    m = re.search(r"var characterProfileInitialState = (\{.*?\});\s*\n", html, re.S)
    if not m:
        raise ValueError("no profile data on " + url)
    return json.loads(m.group(1))


def item_lines(g):
    L = []
    if g.get("binding"): L.append(g["binding"]["name"])
    it, sub = g.get("inventory_type") or {}, g.get("item_subclass") or {}
    L.append("\t".join(x for x in [it.get("name"), None if g.get("is_subclass_hidden") else sub.get("name")] if x))
    w = g.get("weapon")
    if w:
        L.append(w["damage"]["display_string"] + "\t" + w["attack_speed"]["display_string"])
        L.append(w["dps"]["display_string"])
    if (g.get("armor") or {}).get("value"): L.append(f'{g["armor"]["value"]} Armor')
    for s in g.get("stats") or []:
        t = (s.get("display") or {}).get("display_string", "")
        L.append("Equip: " + t if s.get("is_equip_bonus") else t)
    lv = (g.get("requirements") or {}).get("level")
    if lv: L.append(lv["display_string"])
    for s in g.get("spells") or []: L.append(s.get("description", ""))
    st = g.get("set")
    if st:
        L.append(st["display_string"])
        for e in st.get("effects") or []:
            d = e["display_string"]
            L.append(d if d.startswith("(") else f'({e["required_count"]}) {d}')
    return [x for x in L if x]


def clean(a):
    return [s for s in (a or []) if not re.match(r"(?i)^sell price", s)]


def category(slot, x):
    x = "\n".join(x)
    if re.search(r"Relic\t", x) or slot in ("leftTrinket", "rightTrinket"): return 3
    if "Damage\tSpeed" in x: return 0
    if slot in ("neck", "leftFinger", "rightFinger"): return 2
    return 1


def icon_id(asset_url):
    m = re.search(r"/(\d+|[a-z0-9_]+)\.jpg", asset_url or "")
    return m.group(1) if m else None


def sheet(ids, cols, cell, crop, out):
    rows = max(1, math.ceil(len(ids) / cols))
    o = Image.new("RGB", (cols * cell, rows * cell))
    for i, ic in enumerate(ids):
        try:
            im = Image.open(io.BytesIO(get(ICON.format(ic)))).convert("RGB")
            im = im.crop((crop, crop, im.width - crop, im.height - crop)).resize((cell, cell), Image.LANCZOS)
            if cell > 60: im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
            o.paste(im, ((i % cols) * cell, (i // cols) * cell))
        except Exception as e:
            print("icon failed", ic, e)
    o.save(out, "WEBP", quality=80 if cell > 60 else 74, method=6)


def render_art(url, out):
    im = Image.open(io.BytesIO(get(url))).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box: im = im.crop(box)
    H = 260; w = max(1, round(im.width / im.height * H))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.resize((w, H), Image.LANCZOS).save(out, "WEBP", quality=80, method=6)


def sha(b, n):
    return hashlib.sha256(b).hexdigest()[:n]


def now_text():
    d = datetime.now(SYD)
    return f'{d.day} {d.strftime("%b")}, {d.strftime("%I").lstrip("0")}:{d.strftime("%M")} {d.strftime("%p")} {d.tzname()}'


# ---------------------------------------------------------------- requests from issues
def parse_form(body):
    out, key = {}, None
    for line in (body or "").splitlines():
        m = re.match(r"^###\s+(.*)$", line.strip())
        if m: key = m.group(1).strip().lower(); out[key] = ""; continue
        if key is not None and line.strip() and line.strip() != "_No response_":
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def ruleset_of(realm):
    m = re.search(r"(?i)(roleplay|rp|pvp|normal|hardcore)", realm or "")
    if not m: return None
    w = m.group(1).lower()
    return {"rp": "roleplay"}.get(w, w)


def guess_character(ch, region=None, ruleset=None):
    """Search Out of Games' Forever armory for characters named after the channel.
    Returns [(name, region), ...] best first, or []."""
    keys = {ch}
    for suf in ("tv", "ttv", "irl", "live", "wow", "gaming", "official", "_"):
        if ch.endswith(suf) and len(ch) - len(suf) >= 3: keys.add(ch[: -len(suf)].rstrip("_"))
    cands = {}
    for k in keys:
        try:
            html = get("https://outof.games/realms/forever/search/?q=" + urllib.parse.quote(k)).decode("utf-8", "replace")
        except Exception as e:
            print("search failed", k, e); continue
        for m in re.finditer(r'href="/realms/forever/character/(us|eu)/([a-z0-9-]+)/".*?wf-char-name">([^<]+)</span>\s*<span class="wf-char-meta">(\d+)[^<]*</span>.*?wf-muted">[^<]*?(?:·|&middot;)\s*([^<]+)</span>', html, re.S):
            reg, slug, nm, lvl, rs = m.group(1), m.group(2), m.group(3).strip(), int(m.group(4)), m.group(5).strip().lower()
            parts = nm.lower().split()
            score = 0
            if any(p == k for p in parts for k in keys): score += 100
            elif any(p.startswith(k) or k.startswith(p) for p in parts for k in keys if len(p) >= 3): score += 40
            else: continue
            if region and reg != region: score -= 60
            if ruleset and ruleset not in rs.replace(" ", ""): score -= 30
            score += lvl
            cands[(nm, reg)] = max(cands.get((nm, reg), -999), score)
    return [k for k, _ in sorted(cands.items(), key=lambda kv: -kv[1])]


def handle_request(roster, kind, body, author, owner, labels):
    """Returns (message, close_issue, added_slug_or_None, removed_names)."""
    f = parse_form(body)
    ch = re.sub(r"[^a-z0-9_]", "", re.sub(r"^.*twitch\.tv/", "", (f.get("twitch channel") or "").lower()))
    name = re.sub(r"[^A-Za-zÀ-ÿ' -]", "", f.get("character name") or "").strip()
    realm = (f.get("realm") or f.get("region") or "").strip()
    region = "eu" if re.match(r"(?i)\s*eu\b", realm) else "us"
    if kind == "remove":
        if author.lower() != owner.lower() and "approved" not in labels:
            return (f"Thanks! Removing a card needs the page owner's OK. @{owner}, add the **approved** label to remove it.", False, None, [])
        target = name.lower().replace(" ", "-")
        removed = []
        for r in list(roster):
            if target:
                keep = [c for c in r["chars"] if (c.get("slug") or "").split("/")[-1] != target]
                if len(keep) < len(r["chars"]):
                    removed.append(name)
                    r["chars"] = keep
                    if not keep: roster.remove(r)
            elif r["ch"] == ch:
                removed.append(r["streamer"]); roster.remove(r)
        if not removed:
            return (f"Couldn't find a card for `{ch or name}` on the tracker.", True, None, [])
        return ("Removed " + ", ".join(removed) + " from the tracker. The page updates in a minute or two.", True, None, removed)
    # add
    if not ch:
        return ("Please give the streamer's Twitch channel.", False, None, [])
    region_given = bool(re.match(r"(?i)\s*(us|eu)\b", realm))
    rules = ruleset_of(realm)
    how = "Found on the Armory."

    def lookup(nm):
        """Exact name in each region -> list of (slug, state)."""
        b = nm.lower().strip().replace(" ", "-")
        hits = []
        slugs = ([b] if region == "us" else ["eu/" + b]) if region_given else [b, "eu/" + b]
        for sl in slugs:
            try: hits.append((sl, state(armory_path(sl))))
            except Exception: pass
        return hits

    def pick_list(title, opts):
        lines = [f"{i+1}. **{n}** · {r.upper()}{(' · ' + str(lv)) if lv else ''} · [Armory]({armory_path(n.lower().replace(' ', '-') if r == 'us' else 'eu/' + n.lower().replace(' ', '-'))})"
                 for i, (n, r, lv) in enumerate(opts)]
        return (title + "\n\n" + "\n".join(lines) + "\n\nEdit this issue and put the one you want in **Character name** (and its region in **Realm**); the tracker will try again as soon as you save.", False, None, [])

    if not name:
        vod = []
        try:
            import vodname
            def check(nm):
                h = lookup(nm)
                if not h: return None
                c = h[0][1]["character"]
                return (c["name"] + (" " + c["surname"] if c.get("surname") else ""), "eu" if "/" in h[0][0] else "us", c["level"])
            vod, _ = vodname.find_character(ch, check, keys=[ch] + [k for k in (ch[:-2], ch[:-3]) if len(k) >= 3])
        except Exception as e:
            print("VOD reading failed:", e)
        if vod and vod[0][4]:
            name, region = vod[0][0], vod[0][1]; region_given = True
            how = f"Read off {ch}'s recent WoW Forever VODs and confirmed on the Armory."
        else:
            opts = [(n, r, lv) for n, r, lv, seen, _ in vod]
            for n, r in guess_character(ch, region if region_given else None, rules):
                if all(n != o[0] for o in opts): opts.append((n, r, None))
            if not opts:
                return (f"I couldn't read a character name from `{ch}`'s recent VODs or find one by searching the Armory. Edit this issue and add the exact character name.", False, None, [])
            return pick_list(f"I checked `{ch}`'s recent VODs and the Armory but couldn't be sure which character is theirs. Names seen on stream come first — which one is it?", opts[:8])
    hits = lookup(name)
    if not hits:
        found = guess_character(name.split()[0].lower(), region if region_given else None, rules)
        if len(found) == 1:
            name, region = found[0]; region_given = True; hits = lookup(name)
        elif found:
            return pick_list(f"There's no character called **{name}** on the {region.upper() if region_given else 'US or EU'} Armory. Did you mean one of these?", [(n, r, None) for n, r in found[:8]])
        if not hits:
            return (f"Couldn't find **{name}** on the WoW Forever Armory. Check the spelling (the Armory uses the full two-part name) and edit this issue.", False, None, [])
    if len(hits) > 1:
        return pick_list(f"**{name}** exists in both regions. Which one?", [(h[1]["character"]["name"] + (" " + h[1]["character"].get("surname", "") if h[1]["character"].get("surname") else ""),
                                                                                "eu" if "/" in h[0] else "us", h[1]["character"]["level"]) for h in hits])
    slug, st = hits[0]
    for r in roster:
        for c in r["chars"]:
            if c.get("slug") == slug:
                return (f"**{c['name']}** is already on the tracker.", True, None, [])
    rs = ((st["character"].get("ruleset") or {}).get("name") or "").lower().replace(" ", "")
    if rules and rules not in rs:
        how += f" (Request said {realm}; the Armory lists this character on {(st['character'].get('ruleset') or {}).get('name', '?')}.)"
    c = st["character"]
    disp = (f.get("display name") or "").strip() or ch
    char = {"name": c["name"] + (" " + c["surname"] if c.get("surname") else ""), "slug": slug, "render": "", "bg":
            re.sub(r"[^a-z]+", "_", c["race"]["name"].lower()), "level": c["level"], "ilvl": c.get("averageItemLevel"),
            "race": c["race"]["name"], "cls": c["class"]["name"], "spec": "",
            "faction": "horde" if "horde" in json.dumps(c.get("faction")).lower() else "ally",
            "ruleset": (c.get("ruleset") or {}).get("name", ""), "guild": (c.get("guild") or {}).get("name", ""),
            "profs": [], "rep": None}
    if "/" in slug: char["region"] = slug.split("/")[0].upper()
    entry = next((r for r in roster if r["ch"] == ch), None)
    if entry:
        entry["chars"].append(char)
    else:
        entry = {"ch": ch, "streamer": disp, "added": True, "flavor": f"Added on {datetime.now(SYD).strftime('%-d %b %Y')} by @{author}.",
                 "how": f"Added through a GitHub request by @{author}. {how}", "fixed": "", "chars": [char]}
        tail = next((i for i, r in enumerate(roster) if r["ch"] == "quin69"), len(roster))
        roster.insert(tail, entry)
    note = "\n\n" + how
    return (f"Added **{char['name']}** (level {char['level']} {char['race']} {char['cls']}) for {entry['streamer']}. "
            "The card will be on the page in a minute or two." + note, True, slug, [])


# ---------------------------------------------------------------- main refresh
def main():
    roster = json.load(open(P("roster.json"), encoding="utf-8"))
    old_roster = json.loads(json.dumps(roster))
    old_gear = {}
    try:
        g = open(P("gear-data.js"), encoding="utf-8").read()
        old_gear = json.loads(g[g.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        pass
    events = []
    try:
        e = open(P("events.js"), encoding="utf-8").read()
        events = json.loads(e[e.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        pass
    stamp = datetime.now(timezone.utc).isoformat(timespec="minutes")

    def ev(kind, text):
        events.insert(0, {"t": stamp, "k": kind, "s": text})

    # ---- issue request, if this run came from one
    kind = os.environ.get("REQ_KIND", "")
    msg, close, added, removed = "", False, None, []
    if kind in ("add", "remove"):
        labels = [x.strip() for x in os.environ.get("ISSUE_LABELS", "").split(",") if x.strip()]
        msg, close, added, removed = handle_request(roster, kind, os.environ.get("ISSUE_BODY", ""),
                                                    os.environ.get("ISSUE_AUTHOR", ""), os.environ.get("REPO_OWNER", ""), labels)
        open("/tmp/issue-comment.md", "w").write(msg)
        open("/tmp/issue-close", "w").write("yes" if close else "no")
        for n in removed: ev("remove", f"{n} was removed from the tracker")

    # ---- fetch every character
    FC, build = {}, ""
    for f in ("new", "changed", "same"):
        j = json.loads(get(f"https://foreverchanges.pro/items/{f}.json"))
        build = j.get("forever_build", build)
        for it in j["items"]: FC[it["i"]] = it
    SRC = json.loads(get("https://foreverchanges.pro/items/sources.json"))["items"]

    ITEMS, C, CH, show_ids, renders, bad = {}, {}, {}, [], {}, []
    by_slug = {c["slug"]: c for r in roster for c in r["chars"] if c.get("slug")}
    for slug, ch in by_slug.items():
        try:
            st = state(armory_path(slug)); c = st["character"]
        except Exception as e:
            bad.append(f"{slug}: {e}"); continue
        C[slug] = [c["level"], c.get("averageItemLevel"), {}]
        ch["level"], ch["ilvl"] = c["level"], c.get("averageItemLevel")
        ch["guild"] = (c.get("guild") or {}).get("name") or ""
        pr = c.get("professions") or {}
        profs = [[p["name"], p["tiers"][0]["skillPoints"], p["tiers"][0]["maxSkillPoints"]]
                 for p in (pr.get("primaries") or []) + (pr.get("secondaries") or [])]
        ch["profs"] = sorted(profs, key=lambda p: (-p[1], p[0]))
        specs = sorted(c.get("specs") or [], key=lambda s: -s.get("spentPoints", 0))
        ch["spec"] = re.sub(r" Combat$", "", specs[0]["name"]) if specs and specs[0].get("spentPoints") else ch.get("spec", "")
        try:
            rs = state(armory_path(slug) + "/reputation").get("reputations")
            allr = []
            def walk(a):
                for r in a or []:
                    if r.get("standingType") and r.get("maxValue") is not None: allr.append(r)
                    walk(r.get("reputations"))
            walk(rs.get("reputations") if isinstance(rs, dict) else rs)
            sc = lambda r: 42000 if r["standingType"]["id"] >= 7 else STAND[r["standingType"]["id"]] + min(r["value"], r["maxValue"])
            allr.sort(key=sc, reverse=True)
            if allr: ch["rep"] = [allr[0]["name"], allr[0]["standingType"]["name"], round(sc(allr[0]) / 420)]
        except Exception as e:
            print("rep failed", slug, e)
        # gear
        mine = []
        for k, g in (c.get("gear") or {}).items():
            iid = (g.get("item") or {}).get("id", g.get("id")); C[slug][2][k] = iid; mine.append((k, iid))
            if iid in ITEMS: continue
            ic = next((a for a in ((g.get("media") or {}).get("content") or {}).get("assets") or [] if a.get("key") == "icon"), None)
            f = FC.get(iid)
            ITEMS[iid] = {"n": g.get("name"), "q": Q.get((g.get("quality") or {}).get("type"), 1), "il": (g.get("level") or {}).get("value"),
                          "ic": icon_id(ic["value"]) if ic else None, "t": f["t"] if f else "same",
                          "x": clean(f.get("x")) if f else item_lines(g), "y": clean(f.get("y")) if f and f["t"] == "changed" else 0,
                          "src": SRC[str(iid)][:3] if str(iid) in SRC else 0}
        cand = [(k, ITEMS[i]) for k, i in mine if k not in ("shirt", "tabard")]
        if cand:
            best = sorted(cand, key=lambda kv: (-(kv[1]["il"] or 0), -kv[1]["q"], category(kv[0], kv[1]["x"])))[0][1]
            if best["ic"] not in show_ids: show_ids.append(best["ic"])
        # talents and stats
        T = {sp["name"]: [[t["name"], t["rank"], icon_id((t.get("icon") or {}).get("url")), t.get("description", "")] for t in sp.get("talents") or []]
             for sp in c.get("specs") or []}
        S = {}
        for grp in (c.get("stats") or {}).get("groups") or []:
            for x in grp.get("stats") or []:
                v = x.get("value") or {}
                if x["slug"] in STAT_KEYS and isinstance(v.get("value"), (int, float)):
                    S[STAT_KEYS[x["slug"]]] = round(v["value"], 2)
        CH[slug] = {"s": S, "t": T}
        # art
        u = ((c.get("render") or {}).get("foreground") or {}).get("url")
        if u:
            m = re.search(r"character/(\d+/\d+)-main", u)
            if m: ch["render"] = m.group(1)
            renders[slug] = u
        ch["race"], ch["cls"] = c["race"]["name"], c["class"]["name"]
        ch["faction"] = "horde" if "horde" in json.dumps(c.get("faction")).lower() else "ally"
        ch["ruleset"] = (c.get("ruleset") or {}).get("name", ch.get("ruleset", ""))
        time.sleep(0.4)

    if bad: print("Characters that failed:", *bad, sep="\n  ")
    if not C:
        print("Every character failed; stopping without changes."); sys.exit(1)
    icons = list(dict.fromkeys(i["ic"] for i in ITEMS.values() if i["ic"]))
    ix = {v: k for k, v in enumerate(icons)}
    I = {str(k): [v["n"], v["q"], v["il"], ix.get(v["ic"], 0), v["t"][0], v["x"], v["y"] or 0, v["src"]] for k, v in sorted(ITEMS.items())}
    S = [ix[i] for i in show_ids if i in ix]
    core = json.dumps({"I": I, "C": C, "S": S}, separators=(",", ":"), ensure_ascii=False)
    gv = sha(core.encode(), 16)
    gear_changed = gv != old_gear.get("v")
    gear = {"v": gv, "checked": now_text(), "fc": build, "n": len(icons), "I": I, "C": C, "S": S}
    open(P("gear-data.js"), "w", encoding="utf-8").write("window.GEAR=" + json.dumps(gear, separators=(",", ":"), ensure_ascii=False) + ";")
    if gear_changed or not os.path.exists(P("sprite.webp")):
        sheet(icons, 12, 48, 4, P("sprite.webp"))
        sheet(show_ids, 4, 112, 3, P("showcase.webp"))
    # talents/stats
    ticons = list(dict.fromkeys(t[2] for v in CH.values() for a in v["t"].values() for t in a if t[2]))
    tix = {v: k for k, v in enumerate(ticons)}
    chars = {"n": len(ticons), "C": {s: {"s": v["s"], "t": {n: [[t[0], t[1], tix.get(t[2], -1), t[3]] for t in a] for n, a in v["t"].items()}} for s, v in CH.items()}}
    cj = "window.CHARS=" + json.dumps(chars, separators=(",", ":"), ensure_ascii=False) + ";"
    old_cj = open(P("chars.js"), encoding="utf-8").read() if os.path.exists(P("chars.js")) else ""
    open(P("chars.js"), "w", encoding="utf-8").write(cj)
    if cj != old_cj or not os.path.exists(P("talents.webp")):
        sheet(ticons, 12, 48, 4, P("talents.webp"))
    cv = sha(open(P("chars.js"), "rb").read() + open(P("talents.webp"), "rb").read(), 12)
    # art for changed characters (or missing files)
    for slug, u in renders.items():
        out = P("renders", slug + ".webp")
        old = (old_gear.get("C") or {}).get(slug)
        if not os.path.exists(out) or not old or old[0] != C[slug][0] or old[2] != C[slug][2]:
            try: render_art(u, out)
            except Exception as e: print("render failed", slug, e)
    live = {c["slug"] for r in roster for c in r["chars"] if c.get("slug")}
    for r in old_roster:
        for c in r["chars"]:
            if c.get("slug") and c["slug"] not in live:
                f = P("renders", c["slug"] + ".webp")
                if os.path.exists(f): os.remove(f)

    # ---- events for the ticker
    old_c = {c["slug"]: c for r in old_roster for c in r["chars"] if c.get("slug")}
    for r in roster:
        for c in r["chars"]:
            s = c.get("slug"); o = old_c.get(s)
            if not s: continue
            if not o:
                ev("add", f"{r['streamer']} joined the tracker: {c['name']}, level {c['level']} {c['race']} {c['cls']}"); continue
            if c["level"] != o.get("level") and c["level"] and o.get("level") and c["level"] > o["level"]:
                ev("sixty" if c["level"] >= 60 else "ding", f"{c['name']} ({r['streamer']}) hit level {c['level']}" + (" — max level!" if c["level"] >= 60 else ""))
            if (c.get("guild") or "") != (o.get("guild") or "") and c.get("guild"):
                ev("guild", f"{c['name']} joined <{c['guild']}>")
            op = {p[0]: p for p in o.get("profs") or []}
            for p in c.get("profs") or []:
                q = op.get(p[0])
                if p[1] >= p[2] and p[2] >= 150 and (not q or q[1] < q[2] or q[2] < p[2]):
                    ev("prof", f"{c['name']} maxed {p[0]} ({p[1]}/{p[2]})")
            if c.get("rep") and o.get("rep") and c["rep"][1] != o["rep"][1] and c["rep"][0] == o["rep"][0]:
                ev("rep", f"{c['name']} reached {c['rep'][1]} with {c['rep'][0]}")
            og = (old_gear.get("C") or {}).get(s)
            if og and s in C:
                before = set(map(str, og[2].values()))
                for slot, iid in C[s][2].items():
                    it = I.get(str(iid))
                    if it and str(iid) not in before and it[1] >= 3:
                        ev("loot", f"{c['name']} equipped [{it[0]}]|{it[1]}")
    events[:] = events[:60]
    open(P("events.js"), "w", encoding="utf-8").write("window.EVENTS=" + json.dumps(events, ensure_ascii=False) + ";")

    # ---- daily history for future progress charts
    hist = json.load(open(P("history.json"))) if os.path.exists(P("history.json")) else {}
    hist[datetime.now(SYD).strftime("%Y-%m-%d")] = {s: v[:2] for s, v in C.items()}
    json.dump(hist, open(P("history.json"), "w"), separators=(",", ":"))

    # ---- roster + page
    json.dump(roster, open(P("roster.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    html = open(P("index.html"), encoding="utf-8").read()
    i = html.index("const ROSTER = ["); j = html.index("\n];", i) + 3
    html = html[:i] + "const ROSTER = " + json.dumps(roster, indent=1, ensure_ascii=False) + ";" + html[j:]
    html = re.sub(r'(<b id="checked">)[^<]*(</b>)', lambda m: m.group(1) + now_text() + m.group(2), html)
    html = re.sub(r'gear-data\.js\?v=[0-9a-f]+', "gear-data.js?v=" + gv, html)
    html = re.sub(r'chars\.js\?v=[0-9a-f]+', "chars.js?v=" + cv, html)
    html = re.sub(r'talents\.webp\?v=[0-9a-f]+', "talents.webp?v=" + cv, html)
    ev_v = sha(open(P("events.js"), "rb").read(), 10)
    html = re.sub(r'events\.js\?v=[0-9a-f]+', "events.js?v=" + ev_v, html)
    open(P("index.html"), "w", encoding="utf-8").write(html)

    # ---- commit message
    new_events = [e for e in events if e["t"] == stamp]
    title = "Tracker refresh"
    if added: title = f"Add {by_slug.get(added, {}).get('name', added) if added in by_slug else added} to the tracker"
    elif removed: title = "Remove " + ", ".join(removed) + " from the tracker"
    elif new_events: title += ": " + "; ".join(e["s"].split("|")[0] for e in new_events[:2])
    summary = (f"{len(C)} characters checked on the Armory; " + (f"{len(new_events)} new events for the ticker" if new_events else "no new events")
               + ("; gear changed" if gear_changed else "") + (f"; {len(bad)} failed" if bad else "") + ".")
    open("/tmp/commit-msg.txt", "w").write(title[:72] + "\n\n" + summary + "\n")
    print(title); print(summary)


if __name__ == "__main__":
    main()
