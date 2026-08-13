#!/usr/bin/env python3
"""Verify the fix for the bug that ate real notifications: a dropped BLE link
must NOT deactivate ordinary notifications (the displays refuse to toast
anything with active=false), but must still cancel a ringing call."""
import sys
sys.path.insert(0, "/opt/ancs")
import ancs_gateway as g

S = g.Store(10)

msg = {"uid": 1, "call": False, "active": True, "ts": 0}
call = {"uid": 2, "call": True, "active": True, "ts": 0}
S.add(msg)
S.add(call)
S.set_link(True, "iPhone")

# the phone walks out of range mid-conversation
S.set_link(False)

ok = True
if msg["active"] is not True:
    print("FAIL: an ordinary notification was deactivated by a dropped link "
          "- this is the bug that made every message invisible")
    ok = False
else:
    print("PASS: ordinary notification survived the disconnect (active=True)")

if call["active"] is not False:
    print("FAIL: a ringing call stayed active after the phone vanished")
    ok = False
else:
    print("PASS: ringing call was cancelled by the disconnect (active=False)")

# a real ANCS removal must still work
S.add({"uid": 1, "call": False, "active": True, "ts": 0})
S.remove(1)
if msg["active"] is not False:
    print("FAIL: EVT_REMOVED no longer clears active")
    ok = False
else:
    print("PASS: phone-side removal still clears active")

sys.exit(0 if ok else 1)
