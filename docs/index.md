# HiveMind Core Documentation

Welcome to the HiveMind Core documentation. This guide provides an in-depth look at the architecture, security, and protocol of the HiveMind network.

## Navigation
- [Architecture](architecture.md): Understand the core components and how they interact.
- [Authentication](auth.md): Learn about client registration and session management.
- [Security](security.md): Explore the encryption and authorization mechanisms.
- [Protocol](protocol.md): Detailed information on HiveMessages and communication flows.
- [QUERY & CASCADE](query-cascade.md): Request-response message types for distributed queries and multi-node disambiguation.
- [Hive Map](hive_map.md): Visualizing the HiveMind network topology.

## Core Concepts
HiveMind is designed to be a decentralized, secure, and modular communication protocol for AI agents and smart devices.

- **Hub (Mind)**: The central point of coordination and intelligence.
- **Satellite (Terminal)**: User-facing devices that connect to the Hub.
- **Bridge**: Adapters for connecting external services (e.g., Mattermost, Matrix) to the Hive.
Source: `HiveMindNodeType` — `hivemind_core/protocol.py:64`

## Getting Started
To begin using HiveMind, refer to the [Quick Start section in the README](../README.md#🛰️-quick-start) for installation and basic configuration.
