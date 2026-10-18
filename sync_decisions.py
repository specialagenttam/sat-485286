#!/usr/bin/env python3
"""Pull Tam's decisions and merge them into decisions.json (+ decisions.csv).

Sources (merged, de-duplicated by each answer's uid):
  1. the live inbox: ntfy.sh topic from config.json (keeps answers ~12 hours)
  2. the archive: decisions.json on the gh-pages branch (the GitHub Action copies the inbox there every ~15 min)
  3. the local decisions.json
Usage:
  python3 sync_decisions.py                 # local: merge everything into ./decisions.json and print a summary
  python3 sync_decisions.py --file X --topic T --no-remote   # what the GitHub Action runs
"""
import argparse, csv, json, pathlib, sys, urllib.request, datetime

HERE = pathlib.Path(__file__).resolve().parent
VALID = {"approved", "changes"}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "satboard-sync", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()

def from_ntfy(topic):
    out = []
    for line in get(f"https://ntfy.sh/{topic}/json?poll=1&since=all").splitlines():
        try:
            ev = json.loads(line)
            if ev.get("event") != "message": continue
            rec = json.loads(ev["message"])
        except Exception:
            continue
        if isinstance(rec, dict):
            rec["ntfy_id"] = ev.get("id")
            rec["received"] = datetime.datetime.fromtimestamp(ev["time"], datetime.timezone.utc).isoformat()
            out.append(rec)
    return out

def clean(rec):
    if not isinstance(rec, dict): return None
    if not all(rec.get(k) for k in ("uid", "post_id", "platform", "decision")) or rec["decision"] not in VALID: return None
    keep = ("uid", "post_id", "platform", "decision", "note", "at", "received", "ntfy_id", "device")
    r = {k: rec.get(k) for k in keep if rec.get(k) is not None}
    r["note"] = str(r.get("note", ""))[:4000]
    return r

def merge(existing, incoming):
    by = {d["uid"]: d for d in existing}
    added = 0
    for rec in incoming:
        r = clean(rec)
        if not r: continue
        if r["uid"] in by:
            for k, v in r.items(): by[r["uid"]].setdefault(k, v)
        else:
            by[r["uid"]] = r; added += 1
    return sorted(by.values(), key=lambda d: d.get("at", "")), added

def main():
    cfg = json.loads((HERE / "config.json").read_text()) if (HERE / "config.json").exists() else {}
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "decisions.json"))
    ap.add_argument("--topic", default=cfg.get("ntfy_topic"))
    ap.add_argument("--no-remote", action="store_true", help="skip the gh-pages archive (the Action edits it directly)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    f = pathlib.Path(a.file)
    data = json.loads(f.read_text()) if f.exists() else {"updated": None, "decisions": []}
    decs = data.get("decisions", [])
    total_added = 0
    if not a.no_remote and cfg.get("repo"):
        try:
            remote = json.loads(get(f"https://raw.githubusercontent.com/{cfg['repo']}/{cfg['branch']}/{cfg['board_path']}/decisions.json"))
            decs, n = merge(decs, remote.get("decisions", [])); total_added += n
        except Exception as e:
            print(f"warning: archive not reachable ({e})", file=sys.stderr)
    try:
        decs, n = merge(decs, from_ntfy(a.topic)); total_added += n
    except Exception as e:
        print(f"warning: live inbox not reachable ({e})", file=sys.stderr)
    if total_added or not f.exists():
        data = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "decisions": decs}
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        with open(f.with_suffix(".csv"), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["at_utc", "post_id", "platform", "decision", "note", "uid"])
            for d in decs: w.writerow([d.get("at"), d["post_id"], d["platform"], d["decision"], d.get("note", ""), d["uid"]])
    print(f"{total_added} new decision(s); {len(decs)} total in {f}")
    if not a.quiet:
        latest = {}
        for d in decs: latest[(d["post_id"], d["platform"])] = d
        for (pid, pl), d in sorted(latest.items()):
            print(f"  {pid:9} {pl:9} {d['decision']:8} {d.get('at','')[:16]}  {d.get('note','')[:90]}")
    # exit code 0 always; the Action decides whether to commit by git diff

if __name__ == "__main__":
    main()
