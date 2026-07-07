# Hosting Analysis — Deployment Guide Index

## Overview

This directory contains six deployment implementation plans for the TenBit RAG Platform, organized from simplest/cheapest to most complex/scalable. Each document is self-contained with executive summaries, architecture diagrams, cost tables, step-by-step implementation, and production readiness checklists.

## Documents

| # | Document | Strategy | Est. Monthly Cost | Effort | Best For |
|---|----------|----------|------------------|--------|----------|
| 1 | [Docker Compose Deployment](01-docker-compose-deployment.md) | Containerized stack on single VPS | €5–30/mo | 2–4 days | Teams familiar with Docker |
| 2 | [VPS Bare-Metal Deployment](02-vps-baremetal-deployment.md) | Native systemd services on VPS | €4–25/mo | 3–5 days | Ops teams, full control |
| 3 | [Cloud Managed Platforms](03-cloud-managed-platforms.md) | Railway / Render / Fly.io PaaS | €4–40/mo | 1–2 days | Small teams, no DevOps |
| 4 | [Kubernetes (K3s) Deployment](04-kubernetes-k3s-deployment.md) | Multi-node K3s cluster | €39–144/mo | 5–10 days | Scale, HA, orchestration |
| 5 | [Hybrid Distributed Deployment](05-hybrid-distributed-deployment.md) | Tiny VPS + managed cloud DBs | €4–50/mo | 1–2 days | Best balance of cost + reliability |
| 6 | [MVP Minimum Production](06-mvp-minimum-production.md) | Single tiny VPS, SQLite, no extras | **€4/mo** | **4–6 hours** | Evaluation, demo, small-scale |

## Recommendation Summary

**TL;DR:** Start with Document 6 (MVP). If it grows, upgrade to Document 5 (Hybrid). Only invest in Document 4 (K8s) when you have multiple teams and 10k+ daily queries.

For the detailed reasoning behind each recommendation, see the [Project Documentation](./PROJECT_DOCUMENTATION.md#11-deployment-recommendations).
