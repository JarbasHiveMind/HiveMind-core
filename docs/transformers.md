# Transformer Pipelines

hivemind-core can run OVOS transformer plugins on the text/bus path, so
**plain-text clients** (CLI, webchat, bridges — anything without the audio
binary protocol) get the same rewriting machinery voice clients get.

- **Utterance transformers** rewrite `recognizer_loop:utterance` messages
  after policy admission and before they are injected into the agent bus.
- **Metadata transformers** enrich the message context at the same point.
- **Dialog transformers** rewrite QUERY/CASCADE answer chunks (`speak`
  messages) before they are streamed back to clients.

Cancellation follows OVOS-TRANSFORM §8.1/§8.2: a transformer returning a
valid `canceled`/`cancel_reason` pair terminates the lifecycle — the
utterance never reaches the agent, and the client receives
`ovos.utterance.cancelled` followed by `ovos.utterance.handled`.

## Configuration

New blocks in `~/.config/hivemind-core/server.json`. Loading is opt-in: a
plugin only runs when named in its section; empty sections (the default)
are no-ops.

```json
{
  "utterance_transformers": {
    "ovos-utterance-corrections-plugin": {},
    "ovos-utterance-plugin-cancel": {}
  },
  "metadata_transformers": {},
  "dialog_transformers": {}
}
```

Chains run in ascending priority order (OVOS-TRANSFORM §4); an explicit
`"order"` list wins over priorities. See the
[ovos-plugin-manager transformer docs](https://github.com/OpenVoiceOS/ovos-plugin-manager/blob/dev/docs/transformers.md)
for the full contract.

## When to use — and the surprise factor

Transformers on the hivemind server apply to **every client in the mesh** —
that is the point, and also the surprise: a client that sends "turn on teh
lights" and watches the bus will see its own utterance arrive corrected, and
a QUERY client may receive answer text the agent never literally said
(because a dialog transformer rewrote the chunk).

Deliberate uses:

- **Mesh-wide policy stop-words**: `ovos-utterance-plugin-cancel` here
  cancels utterances for every client, uniformly.
- **Shared corrections/normalization**: fix domain vocabulary once for all
  text clients.
- **Uniform answer tone**: a dialog transformer here rewrites QUERY/CASCADE
  answers for the whole mesh.

Watch for **double-processing** in split deployments: the OVOS agent behind
this server (ovos-core) also runs utterance/metadata transformers, and
hivemind-audio-binary-protocol runs its own chains for voice clients. Enable
each plugin in exactly one place. As a rule: text-client-facing rewrites
belong here; skill-facing rewrites belong in ovos-core; voice-specific
chains belong in the audio binary protocol or on the satellite.
