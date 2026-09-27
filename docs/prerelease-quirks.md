# Prerelease quirks

HiveMind-core ships as a prerelease line. This page records behaviour that
changed between prereleases, and behaviour that is known to be incomplete. Each
entry names the version that first has it.

Use this page when an upgrade changes what your node does and the change is not a
bug. A known limit is recorded here with the case that is still open, so you can
tell a limit from a fault.

## 5.3.2a1 — a HANDSHAKE frame on an established session is dropped, not fatal

**What changed.** A protocol v3 HANDSHAKE frame that arrives after the Noise
session is established is now ignored. Before 5.3.2a1 it closed the connection
with 1008.

**Why it matters to you.** The old behaviour ended a healthy session. The client
recorded the 1008 as a refused identity, so a correctly registered satellite left
the mesh and stayed off it until somebody restarted it. A duplicate or replayed
frame was enough to cause this, so one injected frame could end a connection.

**What you will see now.** The server keeps the session and writes one warning
per frame:

```
ignoring a HANDSHAKE frame from <peer>: the Noise session is already established
```

A node that logged 1008 disconnects during normal operation should stop logging
them after the upgrade. If you count disconnects for alerting, expect that count
to fall.

**What did not change.** A bad frame during a handshake still closes the
connection with 1008. This is correct: a handshake that cannot complete must fail,
and fail fast. The frame is only harmless once the session exists.

The envelope parse also moved to run after the established-session check. One byte
of bad hex in the `msg` field used to close a healthy session; it no longer does.

See [Protocol Internals](protocol.md), "HANDSHAKE frame behaviour", for the state
table.

## 5.3.2a1 — known limit: a bad frame during key derivation still closes the connection

**Status: open.** This is a limit of 5.3.2a1, not a fault in your deployment.

The Noise pre-shared key is derived with argon2id. The derivation runs off the IO
loop, so that it does not stall the loop that serves every other client. Noise
message 1 waits on the connection until the key arrives.

A duplicate frame in that window is dropped, and the connection lives. A **bad**
frame in the same window still closes the connection with 1008: a malformed
envelope, or a pattern or suite the server did not offer. The drop for this window
sits after the envelope parse, after the pattern and suite check, and after the
pinned-key lookup, so only a well formed and correctly negotiated duplicate
reaches it.

The window is short, and it opens only when the key for that password is not
already cached. A burst of duplicate frames is the common case and is handled. An
injected malformed frame that arrives inside the window is not.

Whether every frame in that window should be dropped, whatever its shape, is not
decided yet.
