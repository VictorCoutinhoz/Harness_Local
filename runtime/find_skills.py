"""Query the public skills.sh index when the user asks to discover skills."""

import argparse
import json
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, choices=range(1, 21), default=8)
    args = parser.parse_args()
    query = args.query.strip()
    if not 1 <= len(query) <= 180:
        parser.error("Use entre 1 e 180 caracteres de busca.")
    url = "https://skills.sh/api/search?" + urlencode({"q": query, "limit": args.limit})
    with urlopen(url, timeout=20) as response:
        matches = json.loads(response.read(2 * 1024 * 1024))["skills"]
    print(json.dumps([
        {"name": item["name"], "source": item["source"], "installs": item["installs"],
         "url": "https://skills.sh/" + item["id"]}
        for item in matches[:args.limit]
    ], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
