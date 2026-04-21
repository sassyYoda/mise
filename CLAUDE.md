# CLAUDE.md

This file guides Claude Code when working in this repository.

## Project

Mise en Place

## Technology Stack

# Stack Research

**Domain:** Real-time web scraping + event pipeline + multi-channel notification platform (Mise en Place)
**Researched:** 2026-04-20
**Overall confidence:** HIGH (versions verified against PyPI / Context7 / official docs on research date)

---

## Executive Summary

The PRD-proposed stack is 90% sound. The notable issues:

1. **Next.js 14 is two majors behind** — 15 and 16 are released. Move to **Next.js 15.x LTS** (or 16.x if the team wants the latest). Keeping 14 is an anti-pattern in a portfolio-grade 2026 project.
2. **Kafka client: use `aiokafka` for MVP, not `confluent-kafka`** — as of 2.13.0 (late 2025), `confluent-kafka` reached asyncio GA and is strictly superior at high throughput, but `aiokafka` has a cleaner pure-asyncio API, is simpler to reason about, and is *more than enough* for ~400 events/day. Revisit at v2 if throughput matters.
3. **redis-py 7.x is the answer — `aioredis` is dead.** `aioredis` was merged into `redis-py` in 4.2 and the standalone pa
