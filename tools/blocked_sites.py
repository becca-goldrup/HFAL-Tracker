"""
Some hospital websites block all automated access (for example a "verify you are
human" check). We don't try to get around that. Instead a person saves those
hospitals' documents by hand, and the tool grades from those files.

    python tools/blocked_sites.py

After `python run.py --fetch-only`, this lists every website the tool couldn't open
and creates a folder for each one under data/manual/ with instructions inside.
Put the files in, then run `python run.py --only "<hospital>"` to grade it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from hfal.fetch import load_site, site_slug  # noqa: E402
from hfal.spreadsheet import Tracker  # noqa: E402
from run import pick_input  # noqa: E402

INSTRUCTIONS = """Hospital(s): {names}
Financial assistance page: {url}
Why this folder exists: {why}

Open the page above in your normal browser and save every financial assistance
document into THIS folder:
  * the application (PDF or Word file, every language posted)
  * the plain language summary
  * the full financial assistance policy
  * if the page itself has policy text, save it too: in Chrome use File > Save Page As,
    format "Webpage, HTML Only"
Keep the original file names if you can, and include the language in the name for
translations (for example "application-spanish.pdf").

Then run:   python run.py --only "{first}"
The tool will note in the spreadsheet that this hospital was graded from saved files.
"""


def main():
    tracker = Tracker(pick_input(None))
    groups = {}
    for h in tracker.hospitals():
        if h["hfa_url"]:
            groups.setdefault(h["hfa_url"], []).append(h["name"])

    blocked = []
    for url, names in groups.items():
        site = load_site(url)
        if site is None:
            continue
        manual = config.MANUAL_DIR / site_slug(url)
        has_files = manual.exists() and any(f.suffix.lower() in (".pdf", ".docx", ".html", ".htm", ".txt")
                                            and f.name.lower() != "readme.txt" for f in manual.iterdir())
        if site.landing_ok and not has_files:
            continue
        if not site.landing_ok and "404" in (site.error or ""):
            print(f"BROKEN LINK (page not found, update the link in the spreadsheet):\n  {url}\n  {', '.join(names)}\n")
            continue
        if site.landing_ok and has_files:
            print(f"OK, graded from saved files: {', '.join(names)}  ({manual.relative_to(config.ROOT)})\n")
            continue
        manual.mkdir(parents=True, exist_ok=True)
        (manual / "README.txt").write_text(INSTRUCTIONS.format(
            names=", ".join(names), url=url, why=site.error or "the website blocks automated access", first=names[0]))
        blocked.append((url, names, manual))

    if blocked:
        print("These websites block automated access. Save their documents by hand into the folder shown:\n")
        for url, names, folder in blocked:
            print(f"  {', '.join(names)}\n    page:   {url}\n    folder: {folder.relative_to(config.ROOT)}/\n")
    else:
        print("No blocked websites waiting for documents.")


if __name__ == "__main__":
    main()
