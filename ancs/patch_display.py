#!/usr/bin/env python3
"""
Inject the ANCS notification toast into one of the house displays.

Idempotent: re-running replaces the previously injected block rather than
stacking copies. Always writes a timestamped .bak first.

  patch_display.py <html-file> <widget-file> <ancs-url> [theme]

[theme] is 'light' for host pages that are light-themed but don't use the
body.light convention (the bedroom kiosk); omit it otherwise.
"""
import os
import shutil
import sys
import time

BEGIN = "<!-- ANCS-NOTIFY-BEGIN -->"
END = "<!-- ANCS-NOTIFY-END -->"


def main():
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        return 2
    html_path, widget_path, ancs_url = sys.argv[1], sys.argv[2], sys.argv[3]
    theme = sys.argv[4] if len(sys.argv) == 5 else ""

    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()
    with open(widget_path, encoding="utf-8") as fh:
        widget = fh.read()

    cfg = "window.ANCS_URL=%r;" % ancs_url
    if theme:
        cfg += "window.ANCS_THEME=%r;" % theme
    block = "%s\n<script>%s</script>\n%s\n%s\n" % (
        BEGIN, cfg, widget.strip(), END)

    if BEGIN in html and END in html:
        start = html.index(BEGIN)
        stop = html.index(END) + len(END)
        # keep whatever trailing newline the old block had
        new = html[:start] + block.rstrip("\n") + html[stop:]
        action = "replaced"
    else:
        idx = html.rfind("</body>")
        if idx == -1:
            print("ERROR: no </body> in %s" % html_path)
            return 1
        new = html[:idx] + block + html[idx:]
        action = "inserted"

    if new == html:
        print("no change needed: %s" % html_path)
        return 0

    bak = "%s.bak.%d" % (html_path, int(time.time()))
    shutil.copy2(html_path, bak)
    tmp = html_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    shutil.copymode(html_path, tmp)
    os.replace(tmp, html_path)
    print("%s toast in %s (url=%s), backup %s"
          % (action, html_path, ancs_url, os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
