# Changelog

## [4.10.1a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.1a2) (2026-07-16)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.1a1...4.10.1a2)

**Merged pull requests:**

- perf: move last\_seen persistence off the message loop [\#150](https://github.com/JarbasHiveMind/HiveMind-core/pull/150) ([goldyfruit](https://github.com/goldyfruit))
- Debounce last\_seen database updates [\#143](https://github.com/JarbasHiveMind/HiveMind-core/pull/143) ([goldyfruit](https://github.com/goldyfruit))
- Document horizontal scaling limits [\#139](https://github.com/JarbasHiveMind/HiveMind-core/pull/139) ([goldyfruit](https://github.com/goldyfruit))
- Use direct API-key lookup when available [\#138](https://github.com/JarbasHiveMind/HiveMind-core/pull/138) ([goldyfruit](https://github.com/goldyfruit))

## [4.10.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.1a1) (2026-07-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.0a2...4.10.1a1)

**Merged pull requests:**

- fix: drop dormant beacon/ggwave presence passthrough [\#136](https://github.com/JarbasHiveMind/HiveMind-core/pull/136) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.0a2) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.10.0a1...4.10.0a2)

**Merged pull requests:**

- chore: add comprehensive documentation [\#73](https://github.com/JarbasHiveMind/HiveMind-core/pull/73) ([JarbasAl](https://github.com/JarbasAl))

## [4.10.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.10.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.9.0a1...4.10.0a1)

**Merged pull requests:**

- feat: enforce crypto\_required, verify+pin INTERCOM signatures [\#128](https://github.com/JarbasHiveMind/HiveMind-core/pull/128) ([JarbasAl](https://github.com/JarbasAl))

## [4.9.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.9.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.8.0a1...4.9.0a1)

**Merged pull requests:**

- feat: route agent bus + query answering through AgentProtocol hooks [\#115](https://github.com/JarbasHiveMind/HiveMind-core/pull/115) ([JarbasAl](https://github.com/JarbasAl))

## [4.8.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.8.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.7.0a1...4.8.0a1)

**Merged pull requests:**

- feat: optional presence advertise + GGWave pairing [\#97](https://github.com/JarbasHiveMind/HiveMind-core/pull/97) ([JarbasAl](https://github.com/JarbasAl))

## [4.7.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.7.0a1) (2026-07-04)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.7a1...4.7.0a1)

**Fixed bugs:**

- Add type to allowed\_types requires a client restart [\#45](https://github.com/JarbasHiveMind/HiveMind-core/issues/45)

**Merged pull requests:**

- feat: protocol v3 Noise handshake \(XXpsk2/KKpsk0\) with v2 fallback [\#130](https://github.com/JarbasHiveMind/HiveMind-core/pull/130) ([JarbasAl](https://github.com/JarbasAl))
- Delegate client refresh in ClientDatabase [\#129](https://github.com/JarbasHiveMind/HiveMind-core/pull/129) ([goldyfruit](https://github.com/goldyfruit))

## [4.6.7a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.7a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.6a1...4.6.7a1)

**Closed issues:**

- Unencrypted INTERCOM inner BUS never delivered \(handle\_intercom\_message dispatches on outer INTERCOM type\) [\#117](https://github.com/JarbasHiveMind/HiveMind-core/issues/117)

**Merged pull requests:**

- fix: deliver unencrypted INTERCOM inner messages \(\#117\) [\#123](https://github.com/JarbasHiveMind/HiveMind-core/pull/123) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.6a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.6a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.5a1...4.6.6a1)

**Closed issues:**

- BINARY\(FILE\) file\_name path-traversal: client-supplied file\_name not basename'd before handle\_receive\_file [\#119](https://github.com/JarbasHiveMind/HiveMind-core/issues/119)

**Merged pull requests:**

- fix: basename BINARY\(FILE\) file\_name to block path traversal \(\#119\) [\#120](https://github.com/JarbasHiveMind/HiveMind-core/pull/120) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.5a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.5a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.4a1...4.6.5a1)

**Closed issues:**

- Illegal BROADCAST/ESCALATE/PROPAGATE don't disconnect the offending client \(inconsistent with QUERY/CASCADE\) [\#116](https://github.com/JarbasHiveMind/HiveMind-core/issues/116)

**Merged pull requests:**

- fix: disconnect clients sending illegal BROADCAST/PROPAGATE/ESCALATE \(\#116\) [\#122](https://github.com/JarbasHiveMind/HiveMind-core/pull/122) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.4a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.4a1) (2026-06-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.3a1...4.6.4a1)

**Closed issues:**

- update\_last\_seen crashes \(AttributeError on None\) when client API key is revoked/missing [\#118](https://github.com/JarbasHiveMind/HiveMind-core/issues/118)

**Merged pull requests:**

- fix: guard update\_last\_seen against missing/revoked api key \(\#118\) [\#121](https://github.com/JarbasHiveMind/HiveMind-core/pull/121) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.3a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.3a1) (2026-06-20)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.2a1...4.6.3a1)

**Merged pull requests:**

- fix: allow json-database 1.x [\#112](https://github.com/JarbasHiveMind/HiveMind-core/pull/112) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.2a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.2a1) (2026-06-20)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.1a1...4.6.2a1)

**Closed issues:**

- feat: hivemind-a2a-agent-plugin — A2A agents as hive brains [\#110](https://github.com/JarbasHiveMind/HiveMind-core/issues/110)

**Merged pull requests:**

- fix\(deps\): require ovos-bus-client\>=2.0.0a3 \(drops bundled hivemind protocol\) [\#108](https://github.com/JarbasHiveMind/HiveMind-core/pull/108) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.1a1) (2026-06-06)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.0a2...4.6.1a1)

**Merged pull requests:**

- fix: restore hive.ping.received agent-bus event \(regression from \#98\) [\#107](https://github.com/JarbasHiveMind/HiveMind-core/pull/107) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.6.0a1...4.6.0a2)

**Merged pull requests:**

- ci: fix integration workflow startup\_failure \(system\_deps input\) [\#105](https://github.com/JarbasHiveMind/HiveMind-core/pull/105) ([JarbasAl](https://github.com/JarbasAl))

## [4.6.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.6.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.5.0a1...4.6.0a1)

**Merged pull requests:**

- feat: QUERY + CASCADE — streaming natural-language request/response [\#100](https://github.com/JarbasHiveMind/HiveMind-core/pull/100) ([JarbasAl](https://github.com/JarbasAl))

## [4.5.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.5.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.4.0a2...4.5.0a1)

**Merged pull requests:**

- feat: native relay support \(bind\_upstream\) [\#98](https://github.com/JarbasHiveMind/HiveMind-core/pull/98) ([JarbasAl](https://github.com/JarbasAl))

## [4.4.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.4.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.4.0a1...4.4.0a2)

**Implemented enhancements:**

- Dynamic ACL policy plugin hook [\#85](https://github.com/JarbasHiveMind/HiveMind-core/issues/85)

**Merged pull requests:**

- docs: zero-to-hero documentation [\#101](https://github.com/JarbasHiveMind/HiveMind-core/pull/101) ([JarbasAl](https://github.com/JarbasAl))

## [4.4.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.4.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.3.0a2...4.4.0a1)

**Merged pull requests:**

- feat: default to SQLite \(keep JSON for existing installs\) + migrate-db [\#95](https://github.com/JarbasHiveMind/HiveMind-core/pull/95) ([JarbasAl](https://github.com/JarbasAl))

## [4.3.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.3.0a2) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.3.0a1...4.3.0a2)

## [4.3.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.3.0a1) (2026-06-05)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a3...4.3.0a1)

**Merged pull requests:**

- feat: policy admission chain runner \(\#85 phase 2\) [\#89](https://github.com/JarbasHiveMind/HiveMind-core/pull/89) ([JarbasAl](https://github.com/JarbasAl))

## [4.2.0a3](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a3) (2026-05-19)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a2...4.2.0a3)

**Merged pull requests:**

- ci: add lint workflow [\#91](https://github.com/JarbasHiveMind/HiveMind-core/pull/91) ([JarbasAl](https://github.com/JarbasAl))

## [4.2.0a2](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a2) (2026-05-18)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.2.0a1...4.2.0a2)

**Merged pull requests:**

- Relicense to Apache-2.0 [\#87](https://github.com/JarbasHiveMind/HiveMind-core/pull/87) ([JarbasAl](https://github.com/JarbasAl))

## [4.2.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.2.0a1) (2026-05-18)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.1.1a1...4.2.0a1)

**Implemented enhancements:**

- Add client metadata option [\#86](https://github.com/JarbasHiveMind/HiveMind-core/pull/86) ([goldyfruit](https://github.com/goldyfruit))

## [4.1.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.1.1a1) (2026-05-10)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.1.0a1...4.1.1a1)

**Merged pull requests:**

- fix: preserve client session pipeline [\#79](https://github.com/JarbasHiveMind/HiveMind-core/pull/79) ([goldyfruit](https://github.com/goldyfruit))

## [4.1.0a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.1.0a1) (2026-05-07)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.0.1a1...4.1.0a1)

**Merged pull requests:**

- feat\(tests\): hivescope e2e skeleton [\#80](https://github.com/JarbasHiveMind/HiveMind-core/pull/80) ([JarbasAl](https://github.com/JarbasAl))

## [4.0.1a1](https://github.com/JarbasHiveMind/HiveMind-core/tree/4.0.1a1) (2026-03-23)

[Full Changelog](https://github.com/JarbasHiveMind/HiveMind-core/compare/4.0.0...4.0.1a1)

**Merged pull requests:**

- Feat: ping [\#75](https://github.com/JarbasHiveMind/HiveMind-core/pull/75) ([JarbasAl](https://github.com/JarbasAl))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
