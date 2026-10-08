#!/bin/sh
# snapserver always passes --get-coverart; the base64 art then bloats every
# Server.GetStatus reply to ~240 KB, which the bedroom Pi polls every 2 s.
# Speakers have no screen, so drop it.
for a; do shift; [ "$a" = "--get-coverart" ] || set -- "$@" "$a"; done
exec /usr/bin/shairport-sync "$@"
