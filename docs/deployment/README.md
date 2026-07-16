# Hosting Analysis — Deployment Guide Index

## Overview

This directory contains deployment implementation plans for the TenBit RAG Platform, organized from simplest/cheapest to most complex/scalable. Each document is self-contained with executive summaries, architecture diagrams, cost tables, step-by-step implementation, and production readiness checklists.

> **Note:** The project now ships with a complete `docker-compose.yml` — see [RUN_GUIDE.md](../RUN_GUIDE.md) for the single-command Docker setup. The docs below cover specific hosting scenarios in more detail.

## Documents

| # | Document | Strategy | Est. Monthly Cost | Effort | Best For |
|---|----------|----------|------------------|--------|----------|
| 1 | [Docker Compose Deployment](01-docker-compose-deployment.md) | Containerized stack on single VPS | €5–30/mo | 2–4 days | Teams familiar with Docker |
| 2 | [VPS Bare-Metal Deployment](02-vps-baremetal-deployment.md) | Native systemd services on VPS | €4–25/mo | 3–5 days | Ops teams, full control |
| 3 | [Cloud Managed Platforms](03-cloud-managed-platforms.md) | Railway / Render / Fly.io PaaS | €4–40/mo | 1–2 days | Small teams, no DevOps |
| 4 | [Kubernetes (K3s) Deployment](04-kubernetes-k3s-deployment.md) | Multi-node K3s cluster | €39–144/mo | 5–10 days | Scale, HA, orchestration |
| 5 | [Hybrid Distributed Deployment](05-hybrid-distributed-deployment.md) | Tiny VPS + managed cloud DBs | €4–50/mo | 1–2 days | Best balance of cost + reliability |
| 6 | [MVP Minimum Production](06-mvp-minimum-production.md) | Single tiny VPS, SQLite, no extras | **€4/mo** | **4–6 hours** | Evaluation, demo, small-scale |
| 7 | [On-Premises Windows Server](07-on-premises-windows-server.md) | Windows VM + WSL2 + Docker | **€0–15/mo** | 1–2 days | Local server, full data control |

## Recommendation Summary

**For your setup** (Windows VM, 16GB RAM, Docker installed): Use Document 7 (On-Premises Windows Server) with the project's built-in `docker-compose.yml`. Start with `docker compose up -d`, then optionally add SSL and the OCR/Scraper microservices. See [RUN_GUIDE.md](../RUN_GUIDE.md) for the zero-config start.

For the detailed reasoning behind each recommendation, see the [Project Documentation](./PROJECT_DOCUMENTATION.md#11-deployment-recommendations).
