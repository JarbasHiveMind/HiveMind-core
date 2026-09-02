# Changelog

## [4.13.20a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.20a1) (2026-09-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.19a1...4.13.20a1)

**Merged pull requests:**

- fix: refresh can\_escalate/can\_propagate/can\_broadcast per message [\#291](https://github.com/JarbasHiveMind/HiveMind-core/pull/291) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.19a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.19a1) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.18a1...4.13.19a1)

**Merged pull requests:**

- fix: close 1008 on handshake-time auth/credential rejections [\#289](https://github.com/JarbasHiveMind/HiveMind-core/pull/289) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.18a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.18a1) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.17a1...4.13.18a1)

**Merged pull requests:**

- fix: derive Layer-1 session per message and merge session contents [\#287](https://github.com/JarbasHiveMind/HiveMind-core/pull/287) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.17a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.17a1) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.16a1...4.13.17a1)

**Merged pull requests:**

- fix: re-resolve is\_admin fresh in the post-transformer session re-stamp [\#285](https://github.com/JarbasHiveMind/HiveMind-core/pull/285) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.16a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.16a1) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.15a3...4.13.16a1)

**Merged pull requests:**

- fix: re-assert Layer-1 session after transformers and refresh is\_admin for all admin gates [\#283](https://github.com/JarbasHiveMind/HiveMind-core/pull/283) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.15a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.15a3) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.15a2...4.13.15a3)

**Merged pull requests:**

- Re-check is\_admin from the DB at the session-NAT boundary [\#281](https://github.com/JarbasHiveMind/HiveMind-core/pull/281) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.15a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.15a2) (2026-09-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.15a1...4.13.15a2)

**Merged pull requests:**

- Accept a remote 'default' session; admin connections skip NAT \(BRIDGE-1 §4.1\) [\#279](https://github.com/JarbasHiveMind/HiveMind-core/pull/279) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.15a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.15a1) (2026-08-31)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.14a1...4.13.15a1)

**Merged pull requests:**

- fix: translate session\_id to a per-connection Layer-1 id at the bridge [\#277](https://github.com/JarbasHiveMind/HiveMind-core/pull/277) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.14a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.14a1) (2026-08-31)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.13a1...4.13.14a1)

**Merged pull requests:**

- fix: evict flooding peer's own outstanding queries first [\#275](https://github.com/JarbasHiveMind/HiveMind-core/pull/275) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.13a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.13a1) (2026-08-17)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.12a1...4.13.13a1)

**Merged pull requests:**

- fix: bind QUERY/CASCADE answer routing to a request the node saw \(MSG-1 §5.2\) [\#273](https://github.com/JarbasHiveMind/HiveMind-core/pull/273) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.12a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.12a1) (2026-08-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.11a2...4.13.12a1)

**Merged pull requests:**

- fix: disable rendezvous mailbox when hivemind-rendezvous is too old to deliver [\#271](https://github.com/JarbasHiveMind/HiveMind-core/pull/271) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.11a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.11a2) (2026-08-15)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.11a1...4.13.11a2)

**Merged pull requests:**

- docs: add AGENTS.md with per-repo agent conventions [\#269](https://github.com/JarbasHiveMind/HiveMind-core/pull/269) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.11a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.11a1) (2026-08-14)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.10a1...4.13.11a1)

**Merged pull requests:**

- fix: raise ovos-bus-client floor to 2.8.3a1 for send-side wire twins [\#267](https://github.com/JarbasHiveMind/HiveMind-core/pull/267) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.10a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.10a1) (2026-08-14)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.9a1...4.13.10a1)

**Merged pull requests:**

- fix: raise ovos-bus-client floor to 2.2.0a1 for receive-side migration [\#265](https://github.com/JarbasHiveMind/HiveMind-core/pull/265) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.9a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.9a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.8a1...4.13.9a1)

**Merged pull requests:**

- fix: CLI client commands accept an access key, not only a numeric id [\#263](https://github.com/JarbasHiveMind/HiveMind-core/pull/263) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.8a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.8a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.7a1...4.13.8a1)

## [4.13.7a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.7a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.6a1...4.13.7a1)

## [4.13.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.6a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.5a1...4.13.6a1)

**Merged pull requests:**

- fix: gate QUERY/CASCADE response routing behind the request-path ACL check [\#257](https://github.com/JarbasHiveMind/HiveMind-core/pull/257) ([JarbasAl](https://github.com/JarbasAl))
- fix: say which node's mailbox answered a RENDEZVOUS request [\#255](https://github.com/JarbasHiveMind/HiveMind-core/pull/255) ([JarbasAl](https://github.com/JarbasAl))
- fix: answer PING floods when the agent bus is unreachable [\#254](https://github.com/JarbasHiveMind/HiveMind-core/pull/254) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.5a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.4a1...4.13.5a1)

## [4.13.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.4a1) (2026-08-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.3a1...4.13.4a1)

**Merged pull requests:**

- fix: rename-client must not blank the name it was not given [\#256](https://github.com/JarbasHiveMind/HiveMind-core/pull/256) ([JarbasAl](https://github.com/JarbasAl))
- fix: generate a node public key when the server has none [\#252](https://github.com/JarbasHiveMind/HiveMind-core/pull/252) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.3a1) (2026-08-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.2a1...4.13.3a1)

**Closed issues:**

- PING flood dedup: core and the conformance harness disagree on what a flood is \(nodes below a relay never learn the rest of the hive\) [\#245](https://github.com/JarbasHiveMind/HiveMind-core/issues/245)

**Merged pull requests:**

- fix: dedup PING floods per announcement, so nodes below a relay see the hive [\#250](https://github.com/JarbasHiveMind/HiveMind-core/pull/250) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.2a1) (2026-08-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.1a1...4.13.2a1)

**Merged pull requests:**

- fix: derive the rendezvous mailbox from proven identity, not a declared pubkey [\#248](https://github.com/JarbasHiveMind/HiveMind-core/pull/248) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.1a1) (2026-08-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.13.0a1...4.13.1a1)

**Merged pull requests:**

- fix: give a client that lost its Noise key a way back in [\#246](https://github.com/JarbasHiveMind/HiveMind-core/pull/246) ([JarbasAl](https://github.com/JarbasAl))

## [4.13.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.13.0a1) (2026-08-11)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.9a1...4.13.0a1)

**Merged pull requests:**

- feat: route RENDEZVOUS to an optional store-and-forward mailbox [\#243](https://github.com/JarbasHiveMind/HiveMind-core/pull/243) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.9a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.9a1) (2026-08-11)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.8a1...4.12.9a1)

**Merged pull requests:**

- fix: accept the hybrid INTERCOM envelope the client actually sends [\#236](https://github.com/JarbasHiveMind/HiveMind-core/pull/236) ([JarbasAl](https://github.com/JarbasAl))
- docs: correct claims that no longer match the code [\#234](https://github.com/JarbasHiveMind/HiveMind-core/pull/234) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.8a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.8a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.7a1...4.12.8a1)

**Merged pull requests:**

- fix: do not backfill a multi-transport block [\#240](https://github.com/JarbasHiveMind/HiveMind-core/pull/240) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.7a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.7a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.6a1...4.12.7a1)

**Merged pull requests:**

- fix: keep defaults for a partially specified config block [\#238](https://github.com/JarbasHiveMind/HiveMind-core/pull/238) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.6a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.5a2...4.12.6a1)

**Merged pull requests:**

- fix: give \_forwarded\_flood\_ids a bypass-safe default [\#235](https://github.com/JarbasHiveMind/HiveMind-core/pull/235) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.5a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.5a2) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.5a1...4.12.5a2)

**Merged pull requests:**

- chore\(ci\): drop the broken, redundant Dependabot config [\#232](https://github.com/JarbasHiveMind/HiveMind-core/pull/232) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.5a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.4a1...4.12.5a1)

## [4.12.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.4a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.3a1...4.12.4a1)

**Merged pull requests:**

- fix: send INTERCOM as text on a binarize connection \(WIRE-1 §4.3\) [\#220](https://github.com/JarbasHiveMind/HiveMind-core/pull/220) ([JarbasAl](https://github.com/JarbasAl))
- fix: give bypass-constructed HiveMindListenerProtocol test fixtures real attribute defaults [\#219](https://github.com/JarbasHiveMind/HiveMind-core/pull/219) ([JarbasAl](https://github.com/JarbasAl))
- fix: drop already-seen floods when forwarding, not only when answering [\#212](https://github.com/JarbasHiveMind/HiveMind-core/pull/212) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.3a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.2a1...4.12.3a1)

## [4.12.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.2a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.1a1...4.12.2a1)

**Merged pull requests:**

- fix: hold the send lock across encrypt and enqueue [\#217](https://github.com/JarbasHiveMind/HiveMind-core/pull/217) ([JarbasAl](https://github.com/JarbasAl))
- fix: cascade thread races and TOFU pin leak [\#211](https://github.com/JarbasHiveMind/HiveMind-core/pull/211) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.1a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.12.0a1...4.12.1a1)

**Merged pull requests:**

- fix: keep the node up when the agent backend or a listener fails [\#214](https://github.com/JarbasHiveMind/HiveMind-core/pull/214) ([JarbasAl](https://github.com/JarbasAl))
- docs: drop misleading listener terminology [\#200](https://github.com/JarbasHiveMind/HiveMind-core/pull/200) ([JarbasAl](https://github.com/JarbasAl))
- docs: remove THIRDPRTY from the message-type table [\#195](https://github.com/JarbasHiveMind/HiveMind-core/pull/195) ([JarbasAl](https://github.com/JarbasAl))

## [4.12.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.12.0a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.6a2...4.12.0a1)

## [4.11.6a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.6a2) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.6a1...4.11.6a2)

**Merged pull requests:**

- perf: cut per-peer cost in message fan-out [\#204](https://github.com/JarbasHiveMind/HiveMind-core/pull/204) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.6a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.5a1...4.11.6a1)

**Merged pull requests:**

- fix: a node emits at most one responsive PING flood per interval [\#208](https://github.com/JarbasHiveMind/HiveMind-core/pull/208) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.5a1) (2026-08-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.4a2...4.11.5a1)

**Merged pull requests:**

- fix: three races and a missing relay announcement in the PING and CASCADE paths [\#216](https://github.com/JarbasHiveMind/HiveMind-core/pull/216) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.4a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.4a2) (2026-08-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.4a1...4.11.4a2)

**Merged pull requests:**

- perf: derive the noise PSK once per password and node [\#215](https://github.com/JarbasHiveMind/HiveMind-core/pull/215) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.4a1) (2026-08-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.3a1...4.11.4a1)

**Merged pull requests:**

- fix\(deps\): allow hivemind-bus-client 1.x [\#199](https://github.com/JarbasHiveMind/HiveMind-core/pull/199) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.3a1) (2026-08-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.2a1...4.11.3a1)

**Merged pull requests:**

- fix: correct the misleading admin-bypass note in add-client output [\#213](https://github.com/JarbasHiveMind/HiveMind-core/pull/213) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.2a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.1a3...4.11.2a1)

**Merged pull requests:**

- fix: a node answers a PING flood exactly once [\#196](https://github.com/JarbasHiveMind/HiveMind-core/pull/196) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.1a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.1a3) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.1a2...4.11.1a3)

**Merged pull requests:**

- perf: import the RSA identity key once per node [\#205](https://github.com/JarbasHiveMind/HiveMind-core/pull/205) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.1a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.1a2) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.1a1...4.11.1a2)

## [4.11.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.1a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.11.0a1...4.11.1a1)

**Merged pull requests:**

- docs: recommend redis for large deployments [\#203](https://github.com/JarbasHiveMind/HiveMind-core/pull/203) ([JarbasAl](https://github.com/JarbasAl))
- fix: throttle last\_seen writes by default [\#202](https://github.com/JarbasHiveMind/HiveMind-core/pull/202) ([JarbasAl](https://github.com/JarbasAl))
- fix: iterate a snapshot of clients during fan-out [\#201](https://github.com/JarbasHiveMind/HiveMind-core/pull/201) ([JarbasAl](https://github.com/JarbasAl))

## [4.11.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.11.0a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.16a1...4.11.0a1)

**Merged pull requests:**

- feat: let a node be given an upstream in server.json [\#194](https://github.com/JarbasHiveMind/HiveMind-core/pull/194) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.16a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.16a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.15a1...4.10.16a1)

**Merged pull requests:**

- fix: reject malformed wrapper payloads instead of crashing [\#193](https://github.com/JarbasHiveMind/HiveMind-core/pull/193) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.15a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.15a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.14a1...4.10.15a1)

**Merged pull requests:**

- fix: key collected CASCADE responses by responder [\#190](https://github.com/JarbasHiveMind/HiveMind-core/pull/190) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.14a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.14a1) (2026-08-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.13a1...4.10.14a1)

**Merged pull requests:**

- fix: drop QUERY/CASCADE responses with no return path [\#189](https://github.com/JarbasHiveMind/HiveMind-core/pull/189) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.13a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.13a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.12a1...4.10.13a1)

**Merged pull requests:**

- fix: make-admin now reports Invalid Node ID like its sibling commands [\#182](https://github.com/JarbasHiveMind/HiveMind-core/pull/182) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.12a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.12a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.11a1...4.10.12a1)

**Merged pull requests:**

- fix\(test\): give the broadcast fixture an identity [\#186](https://github.com/JarbasHiveMind/HiveMind-core/pull/186) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.11a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.11a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.10a1...4.10.11a1)

## [4.10.10a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.10a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.9a2...4.10.10a1)

**Merged pull requests:**

- fix: stamp provenance with the node public key, not a shared constant [\#183](https://github.com/JarbasHiveMind/HiveMind-core/pull/183) ([JarbasAl](https://github.com/JarbasAl))
- fix: honour the can\_broadcast grant on BROADCAST [\#181](https://github.com/JarbasHiveMind/HiveMind-core/pull/181) ([JarbasAl](https://github.com/JarbasAl))
- refactor: readability and duplication pass over the CLI, service, database and config [\#180](https://github.com/JarbasHiveMind/HiveMind-core/pull/180) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.9a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.9a2) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.9a1...4.10.9a2)

**Merged pull requests:**

- docs: correct stale CLI, config, and protocol claims [\#177](https://github.com/JarbasHiveMind/HiveMind-core/pull/177) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.9a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.9a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.8a1...4.10.9a1)

**Merged pull requests:**

- fix: isolate peer sessions and surface backend failures [\#174](https://github.com/JarbasHiveMind/HiveMind-core/pull/174) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.8a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.8a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.7a1...4.10.8a1)

**Merged pull requests:**

- fix: preserve routing envelopes, isolate query responses, and bound relay floods [\#172](https://github.com/JarbasHiveMind/HiveMind-core/pull/172) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.7a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.7a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.6a1...4.10.7a1)

**Merged pull requests:**

- fix: close three admission-control gaps in the policy chain [\#171](https://github.com/JarbasHiveMind/HiveMind-core/pull/171) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.6a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.5a1...4.10.6a1)

**Merged pull requests:**

- fix: refuse unauthenticated INTERCOM when crypto is required [\#169](https://github.com/JarbasHiveMind/HiveMind-core/pull/169) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.5a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.4a1...4.10.5a1)

**Merged pull requests:**

- fix: require a verifiable origin on signed INTERCOM, and drop rejected frames [\#166](https://github.com/JarbasHiveMind/HiveMind-core/pull/166) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.4a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.3a2...4.10.4a1)

**Merged pull requests:**

- fix: enforce min\_protocol\_version at handshake time [\#165](https://github.com/JarbasHiveMind/HiveMind-core/pull/165) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.3a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.3a2) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.3a1...4.10.3a2)

## [4.10.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.3a1) (2026-08-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.2a3...4.10.3a1)

**Merged pull requests:**

- fix: suppress routing loops per MSG-1 §5 \(append self-hop, drop already-routed\) [\#162](https://github.com/JarbasHiveMind/HiveMind-core/pull/162) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.2a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.2a3) (2026-07-30)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.2a2...4.10.2a3)

**Merged pull requests:**

- docs: rewrite README in Simplified Technical English [\#160](https://github.com/JarbasHiveMind/HiveMind-core/pull/160) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.2a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.2a2) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.2a1...4.10.2a2)

## [4.10.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.2a1) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.1a3...4.10.2a1)

## [4.10.1a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.1a3) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.1a2...4.10.1a3)

## [4.10.1a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.1a2) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.1a1...4.10.1a2)

## [4.10.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.1a1) (2026-07-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.0a2...4.10.1a1)

## [4.10.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.0a2) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.0a1...4.10.0a2)

## [4.10.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.9.0a1...4.10.0a1)

## [4.9.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.9.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.8.0a1...4.9.0a1)

## [4.8.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.8.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.7.0a1...4.8.0a1)

## [4.7.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.7.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.7a1...4.7.0a1)

## [4.6.7a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.7a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.6a1...4.6.7a1)

## [4.6.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.6a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.5a1...4.6.6a1)

## [4.6.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.5a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.4a1...4.6.5a1)

## [4.6.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.4a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.3a1...4.6.4a1)

## [4.6.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.3a1) (2026-06-20)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.2a1...4.6.3a1)

## [4.6.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.2a1) (2026-06-20)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.1a1...4.6.2a1)

## [4.6.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.1a1) (2026-06-06)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.0a2...4.6.1a1)

## [4.6.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.0a1...4.6.0a2)

## [4.6.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.5.0a1...4.6.0a1)

## [4.5.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.5.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.4.0a2...4.5.0a1)

## [4.4.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.4.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.4.0a1...4.4.0a2)

## [4.4.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.4.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.3.0a2...4.4.0a1)

## [4.3.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.3.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.3.0a1...4.3.0a2)

## [4.3.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.3.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a3...4.3.0a1)

## [4.2.0a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a3) (2026-05-19)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a2...4.2.0a3)

## [4.2.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a2) (2026-05-18)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a1...4.2.0a2)

## [4.2.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a1) (2026-05-18)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.1.1a1...4.2.0a1)

## [4.1.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.1.1a1) (2026-05-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.1.0a1...4.1.1a1)

## [4.1.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.1.0a1) (2026-05-07)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.0.1a1...4.1.0a1)

## [4.0.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.0.1a1) (2026-03-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.0.0...4.0.1a1)

## [4.0.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.0.0) (2026-01-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.1a4...4.0.0)

## [3.4.1a4](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.1a4) (2026-01-13)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.1a3...3.4.1a4)

## [3.4.1a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.1a3) (2026-01-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.1a2...3.4.1a3)

## [3.4.1a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.1a2) (2025-12-18)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.1a1...3.4.1a2)

## [3.4.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.1a1) (2025-04-26)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.0...3.4.1a1)

## [3.4.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.0) (2025-04-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.4.0a1...3.4.0)

## [3.4.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.4.0a1) (2025-04-12)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.3.0a1...3.4.0a1)

## [3.3.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.3.0a1) (2025-02-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.3...3.3.0a1)

## [3.2.3](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.3) (2025-01-09)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.3a1...3.2.3)

## [3.2.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.3a1) (2025-01-09)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.2...3.2.3a1)

## [3.2.2](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.2) (2025-01-08)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.2a1...3.2.2)

## [3.2.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.2a1) (2025-01-08)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.1...3.2.2a1)

## [3.2.1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.1) (2025-01-08)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.1a1...3.2.1)

## [3.2.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.1a1) (2025-01-07)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.2.0a1...3.2.1a1)

## [3.2.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.2.0a1) (2025-01-07)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.1.1...3.2.0a1)

## [3.1.1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.1.1) (2025-01-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.1.1a1...3.1.1)

## [3.1.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.1.1a1) (2025-01-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.1.0...3.1.1a1)

## [3.1.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.1.0) (2025-01-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.1.0a1...3.1.0)

## [3.1.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.1.0a1) (2025-01-03)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.3...3.1.0a1)

## [3.0.3](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.3) (2025-01-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.3a1...3.0.3)

## [3.0.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.3a1) (2025-01-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.2...3.0.3a1)

## [3.0.2](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.2) (2025-01-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.2a1...3.0.2)

## [3.0.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.2a1) (2025-01-02)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.1a1...3.0.2a1)

## [3.0.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.1a1) (2025-01-01)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.0...3.0.1a1)

## [3.0.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.0) (2024-12-29)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/3.0.0a1...3.0.0)

## [3.0.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/3.0.0a1) (2024-12-29)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/2.0.0...3.0.0a1)

## [2.0.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/2.0.0) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/1.0.2a1...2.0.0)

## [1.0.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/1.0.2a1) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/1.0.1...1.0.2a1)

## [1.0.1](https://github.com/JarbasHiveMind/HiveMind-core/tree/1.0.1) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/1.0.1a1...1.0.1)

## [1.0.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/1.0.1a1) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/1.0.0...1.0.1a1)

## [1.0.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/1.0.0) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/1.0.0a1...1.0.0)

## [1.0.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/1.0.0a1) (2024-12-28)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.2...1.0.0a1)

## [0.2.2](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.2) (2024-12-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.2a1...0.2.2)

## [0.2.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.2a1) (2024-12-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.1...0.2.2a1)

## [0.2.1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.1) (2024-12-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.1a1...0.2.1)

## [0.2.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.1a1) (2024-12-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.0a2...0.2.1a1)

## [0.2.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.0a2) (2024-12-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.0...0.2.0a2)

## [0.2.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.0) (2024-12-22)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.1.1...0.2.0)

## [0.1.1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.1.1) (2024-12-22)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.2.0a1...0.1.1)

## [0.2.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.2.0a1) (2024-12-22)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.1.1a1...0.2.0a1)

## [0.1.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.1.1a1) (2024-12-21)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/0.1.0...0.1.1a1)

## [0.1.0](https://github.com/JarbasHiveMind/HiveMind-core/tree/0.1.0) (2024-12-20)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/66e6f7f991347ceed423f4cfd0a78ba17dc413e9...0.1.0)



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
