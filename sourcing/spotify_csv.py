"""Spotify playlist/album URL → CSV (Artist,Title,Length) without API credentials.

Reads the public embed page's __NEXT_DATA__. Good enough to drive sockseek
(`sockseek tracks.csv`) when there's no Premium-backed Spotify developer app.
Public playlists only, and the embed caps at 100 tracks — for longer playlists
use exportify.net (or a Spotify dev app with sockseek's native Spotify input).

    python3 -m sourcing.spotify_csv <spotify-url> [-o out.csv | -d dir]

Prints the CSV path on stdout (summary on stderr), so scripts can capture it.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?(playlist|album)/([A-Za-z0-9]+)")


def _next_data(path):
    req = urllib.request.Request(f"https://open.spotify.com/embed/{path}", headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):  # ride out flaky wifi / VPN reconnects
        try:
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
            break
        except urllib.error.URLError as e:
            if attempt == 3:
                sys.exit(f"couldn't reach Spotify ({e.reason}) — check the network/VPN and re-run")
            time.sleep(2 ** attempt)
    data = NEXT_DATA.search(html)
    if not data:
        sys.exit("embed page had no __NEXT_DATA__ (private playlist, or Spotify changed the page)")
    return json.loads(data.group(1))["props"]["pageProps"]["state"]["data"]["entity"]


def fetch_entity(url):
    m = URL.search(url)
    if not m:
        sys.exit(f"not a Spotify playlist/album URL: {url}")
    kind, sid = m.groups()
    return _next_data(f"{kind}/{sid}")


def lead_artist(track):
    """The playlist embed only has "A, B" as one string, which mangles bands like
    "Earth, Wind & Fire". When there's a comma, ask the track's own embed for real artists."""
    if "," not in track["subtitle"]:
        return track["subtitle"].strip()
    try:
        return _next_data(f"track/{track['uri'].split(':')[-1]}")["artists"][0]["name"]
    except (SystemExit, KeyError, IndexError):
        return track["subtitle"].split(",")[0].strip()


def rows(entity):
    tracks = entity["trackList"]
    with ThreadPoolExecutor(8) as pool:
        artists = list(pool.map(lead_artist, tracks))
    for t, artist in zip(tracks, artists):
        yield {"Artist": artist, "Title": t["title"], "Length": round(t["duration"] / 1000)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url")
    p.add_argument("-o", "--out", help="output CSV (default: <playlist name>.csv)")
    p.add_argument("-d", "--dir", default=".", help="directory for the default-named CSV")
    args = p.parse_args(argv)

    entity = fetch_entity(args.url)
    tracks = list(rows(entity))
    # The CSV's stem becomes the playlist's folder name downstream — keep it Windows-safe.
    name = re.sub(r"[^\w\-& ]+", "", entity["name"]).strip() or entity["id"]
    out = args.out or os.path.join(args.dir, name + ".csv")
    with open(out + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Artist", "Title", "Length"])
        w.writeheader()
        w.writerows(tracks)
    os.replace(out + ".tmp", out)  # atomic: a running sockseek may be about to read it
    print(f"{entity['name']}: {len(tracks)} tracks → {out}", file=sys.stderr)
    print(out)
    if len(tracks) >= 100:
        print("  WARNING: the embed caps at 100 tracks — if the playlist is longer,"
              " export it with exportify.net instead", file=sys.stderr)


if __name__ == "__main__":
    main()
