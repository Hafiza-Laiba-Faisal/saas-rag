# Kubernetes (K3s) Cluster Deployment

## 1. Executive Summary (Management Brief)

**Objective:** Deploy the TenBit RAG Platform on a lightweight Kubernetes cluster using K3s — providing container orchestration, auto-healing, scaling, and rolling updates across multiple nodes.

**Why Kubernetes / K3s?**
- Production-grade orchestration — self-healing, rolling updates, auto-scaling
- K3s is CNCF-certified, single-binary Kubernetes for resource-constrained environments
- Run the same YAML manifests on-prem, cloud, or edge
- Built-in service discovery, load balancing, and ingress
- Future-proof: scales from 1 node to 100+

**Timeline:** 5–10 days for cluster setup + app deployment

**Team Requirements:** 1 DevOps Engineer (full-time during setup, part-time after)

**Key Risks:**
- Steeper learning curve (need k8s familiarity)
- Overkill for single-tenant/small deployments
- Requires 3 nodes for high-availability etcd
- Network complexity (CNI, DNS, ingress)

---

## 2. Architecture

```
                         Internet
                            │
                     ┌──────▼──────┐
                     │  Load Balancer │
                     │  (MetalLB/IP) │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  Ingress     │
                     │  (Traefik)   │
                     └──────┬──────┘
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
│  Node 1      │     │  Node 2      │     │  Node 3      │
│ (Control+Worker)   │ (Worker)     │     │ (Worker)     │
│              │     │              │     │              │
│  ┌────────┐  │     │  ┌────────┐  │     │  ┌────────┐  │
│  │ RAG    │  │     │  │ Qdrant │  │     │  │ RAG    │  │
│  │ API    │  │     │  │ (state)│  │     │  │ API    │  │
│  └────────┘  │     │  └────────┘  │     │  └────────┘  │
│  ┌────────┐  │     │  ┌────────┐  │     │  ┌────────┐  │
│  │ Redis  │  │     │  │Postgres│  │     │  │ Redis  │  │
│  └────────┘  │     │  └────────┘  │     │  └────────┘  │
│              │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘

  K3s Cluster (3 nodes, embedded etcd HA)
  CNI: Flannel or Calico
  Storage: Longhorn (distributed block storage) or Rook/Ceph
```

---

## 3. Resource Requirements

### Minimum Viable Cluster (3 nodes, HA)

| Node Role   | vCPU | RAM   | Storage | Count | Total vCPU | Total RAM | Total Storage |
|-------------|------|-------|---------|-------|-----------|-----------|---------------|
| Control + Worker | 2 | 4 GB | 40 GB  | 1     | 2         | 4 GB      | 40 GB         |
| Worker      | 2    | 4 GB  | 40 GB   | 2     | 4         | 8 GB      | 80 GB         |
| **Cluster Total** | | | | **3** | **6** | **12 GB** | **120 GB** |

### Recommended Cluster (3 nodes, production)

| Node Role   | vCPU | RAM   | Storage | Count | Total vCPU | Total RAM | Total Storage |
|-------------|------|-------|---------|-------|-----------|-----------|---------------|
| Control + Worker | 4 | 8 GB | 100 GB | 1     | 4         | 8 GB      | 100 GB        |
| Worker      | 4    | 8 GB  | 100 GB  | 2     | 8         | 16 GB     | 200 GB        |
| **Cluster Total** | | | | **3** | **12** | **24 GB** | **300 GB** |

### Per-Pod Resource Allocation

| Pod          | Request       | Limit         | Storage Claim  |
|--------------|--------------|---------------|----------------|
| rag-api      | 500m CPU / 512 MB | 2 CPU / 2 GB | —             |
| qdrant       | 1 CPU / 2 GB     | 2 CPU / 4 GB | 20 GB (Longhorn) |
| postgresql   | 1 CPU / 1 GB     | 2 CPU / 2 GB | 30 GB (Longhorn) |
| redis        | 200m CPU / 256 MB | 1 CPU / 512 MB | 5 GB (Longhorn) |
| traefik      | 200m CPU / 128 MB | 500m CPU / 256 MB | —          |

---

## 4. Cost Comparison

### 3-Node K3s Cluster Pricing

| Provider     | Node Spec        | Per Node | 3 Nodes/Month | Managed K8s Option | Price |
|--------------|-----------------|----------|---------------|--------------------|-------|
| **Hetzner**  | CX32 (4vCPU/8GB)| €13      | **~€39**      | —                  | —     |
| **DigitalOcean** | Premium 8GB | $48      | **~$144**     | DOKS: $0/mo        | $144  |
| **Linode**   | Dedicated 8GB    | $48      | **~$144**     | LKE: $0/mo         | $144  |
| **AWS**      | t3.large (2vCPU/8GB)| $69  | **~$207**     | EKS: $73/mo + nodes | ~$280 |
| **GCP**      | e2-standard-2    | $49      | **~$147**     | GKE: $0/mo         | $147  |
| **Azure**    | B4ms (4vCPU/16GB)| $121     | **~$363**     | AKS: $0/mo         | $363  |
| **Vultr**    | 4 vCPU / 8 GB    | $40      | **~$120**     | VKE: $0/mo         | $120  |

> **Hetzner is by far the most cost-effective** for self-managed K3s at ~€39/mo for the cluster.
>
> Managed K8s (DOKS, LKE, VKE) add zero control-plane cost but same node pricing.
>
> AWS/GCP/Azure are 2–4× more expensive but offer integrated load balancers and monitoring.

---

## 5. Step-by-Step Implementation

### 5.1 Provision VPS Nodes

```bash
# Create 3 VPS instances with Ubuntu 22.04 (one script per node)
# Requirements: static IPs or DNS records, all nodes in same private network

# On each node:
apt update && apt upgrade -y
apt install -y curl wget git
```

### 5.2 Install K3s Cluster (with embedded etcd HA)

**On Node 1 (first control plane):**

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --cluster-init \
  --disable traefik \
  --node-name node1 \
  --write-kubeconfig-mode 644
```

**On Node 2 (control plane):**

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --server https://<NODE1_IP>:6443 \
  --token <NODE1_TOKEN> \
  --node-name node2
```

**On Node 3 (control plane):**

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --server https://<NODE1_IP>:6443 \
  --token <NODE1_TOKEN> \
  --node-name node3
```

### 5.3 Install Cluster Add-ons

```bash
# Install Helm (on node 1)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install Longhorn (distributed storage)
kubectl create namespace longhorn-system
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn longhorn/longhorn --namespace longhorn-system

# Install Prometheus + Grafana
kubectl create namespace monitoring
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring

# Install cert-manager
kubectl create namespace cert-manager
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true
```

### 5.4 Deploy RAG Application

#### Namespace + ConfigMap

```yaml
# 01-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rag-production
```

```yaml
# 02-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rag-config
  namespace: rag-production
data:
  RAG_ENV: "production"
  RAG_LLM_PROVIDER: "gemini"
  RAG_QDRANT_HOST: "qdrant.rag-production.svc.cluster.local"
  RAG_QDRANT_PORT: "6333"
  RAG_REDIS_HOST: "redis.rag-production.svc.cluster.local"
  RAG_REDIS_PORT: "6379"
```

#### Secrets

```yaml
# 03-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-secrets
  namespace: rag-production
type: Opaque
stringData:
  RAG_LLM_API_KEY: "your-gemini-api-key"
  RAG_QDRANT_API_KEY: "your-qdrant-cloud-api-key"
  POSTGRES_PASSWORD: "strong-password"
```

#### PostgreSQL StatefulSet

```yaml
# 04-postgresql.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgresql
  namespace: rag-production
spec:
  serviceName: postgresql
  replicas: 1
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
      - name: postgresql
        image: postgres:16-alpine
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: rag
        - name: POSTGRES_USER
          value: rag_user
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: POSTGRES_PASSWORD
        resources:
          requests:
            cpu: "1"
            memory: "1Gi"
          limits:
            cpu: "2"
            memory: "2Gi"
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 30Gi
      storageClassName: longhorn
---
apiVersion: v1
kind: Service
metadata:
  name: postgresql
  namespace: rag-production
spec:
  selector:
    app: postgresql
  ports:
  - port: 5432
    targetPort: 5432
```

#### Qdrant StatefulSet

```yaml
# 05-qdrant.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: qdrant
  namespace: rag-production
spec:
  serviceName: qdrant
  replicas: 1
  selector:
    matchLabels:
      app: qdrant
  template:
    metadata:
      labels:
        app: qdrant
    spec:
      containers:
      - name: qdrant
        image: qdrant/qdrant:latest
        ports:
        - containerPort: 6333
        - containerPort: 6334
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: qdrant-data
          mountPath: /qdrant/storage
  volumeClaimTemplates:
  - metadata:
      name: qdrant-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 20Gi
      storageClassName: longhorn
---
apiVersion: v1
kind: Service
metadata:
  name: qdrant
  namespace: rag-production
spec:
  selector:
    app: qdrant
    ports:
    - name: http
      port: 6333
    - name: grpc
      port: 6334
```

#### Redis Deployment

```yaml
# 06-redis.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: rag-production
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command: ["redis-server", "--appendonly", "yes"]
        ports:
        - containerPort: 6379
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "1"
            memory: "512Mi"
        volumeMounts:
        - name: redis-data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 5Gi
      storageClassName: longhorn
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: rag-production
spec:
  selector:
    app: redis
    ports:
    - port: 6379
```

#### RAG API Deployment

```yaml
# 07-rag-api.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-api
  namespace: rag-production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rag-api
  template:
    metadata:
      labels:
        app: rag-api
    spec:
      containers:
      - name: rag-api
        image: ghcr.io/your-org/rag-api:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: rag-config
        - secretRef:
            name: rag-secrets
        env:
        - name: RAG_DB_URL
          value: "postgresql+asyncpg://rag_user:$(POSTGRES_PASSWORD)@postgresql:5432/rag"
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2"
            memory: "2Gi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: rag-data
          mountPath: /app/.rbs_rag
      volumes:
      - name: rag-data
        persistentVolumeClaim:
          claimName: rag-data-pvc
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rag-data-pvc
  namespace: rag-production
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
  storageClassName: longhorn
---
apiVersion: v1
kind: Service
metadata:
  name: rag-api
  namespace: rag-production
spec:
  selector:
    app: rag-api
  ports:
  - port: 8000
    targetPort: 8000
```

#### Ingress with SSL

```yaml
# 08-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rag-ingress
  namespace: rag-production
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    traefik.ingress.kubernetes.io/router.middlewares: "rag-production-rate-limit@kubernetescrd"
spec:
  ingressClassName: traefik
  tls:
  - hosts:
    - rag.yourdomain.com
    secretName: rag-tls
  rules:
  - host: rag.yourdomain.com
    http:
      paths:
      - path: /api/
        pathType: Prefix
        backend:
          service:
            name: rag-api
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: rag-api
            port:
              number: 8000
```

### 5.5 CI/CD with ArgoCD (GitOps)

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Access UI
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Login (default admin / pod name)
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Create application
cat > rag-app.yaml << 'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tenbit-rag
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/tenbit-rag
    path: k8s/
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
    namespace: rag-production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF

kubectl apply -f rag-app.yaml
```

---

## 6. Security & Backup

### Cluster Security

- **RBAC:** Restrict service account permissions per namespace
- **Network Policies:** Restrict pod-to-pod communication
- **Pod Security Standards:** `restricted` profile for all workloads
- **Secrets:** Encrypted at rest (K3s default + etcd encryption)
- **Image Scanning:** Trivy in CI/CD pipeline
- **Runtime Security:** Falco or KubeArmor for anomaly detection

### Backup Strategy (Velero)

```bash
# Install Velero with S3-compatible storage
velero install \
  --provider aws \
  --bucket rag-backups \
  --backup-location-config region=auto,s3ForcePathStyle=true,s3Url=https://s3.eu-central-1.wasabisys.com \
  --plugins velero/velero-plugin-for-aws:v1.0.0 \
  --use-volume-snapshots=true

# Backup all namespaces daily
cat > daily-backup.yaml << 'EOF'
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    ttl: "720h"  # 30 days
    includedNamespaces:
    - rag-production
    - monitoring
EOF

kubectl apply -f daily-backup.yaml
```

---

## 7. Production Readiness Checklist

- [ ] K3s cluster installed with 3 HA control plane nodes
- [ ] Longhorn storage class configured as default
- [ ] cert-manager installed and issuing valid SSL certificates
- [ ] Ingress controller (Traefik) configured with rate limiting
- [ ] PostgreSQL StatefulSet running with Longhorn PVC
- [ ] Qdrant StatefulSet running with Longhorn PVC
- [ ] Redis Deployment running with Longhorn PVC
- [ ] RAG API Deployment with liveness/readiness probes
- [ ] Horizontal Pod Autoscaler configured for rag-api
- [ ] Resource requests and limits set on all pods
- [ ] Network policies applied (deny all by default, allow specific)
- [ ] Prometheus + Grafana monitoring stack deployed
- [ ] Alert rules configured (pod restarts, high CPU, disk space)
- [ ] Arkade/Velero backup running daily
- [ ] Backup restore tested on staging cluster
- [ ] CI/CD with ArgoCD or GitHub Actions
- [ ] Load test: 200 concurrent users across 2 API pods
- [ ] Rolling update strategy: maxSurge=1, maxUnavailable=0
- [ ] Rollback: `kubectl rollout undo deployment/rag-api`

---

## Appendix: Single-Node K3s (for low-budget deployments)

If 3 nodes are too expensive, a single-node setup still provides Docker Compose-like simplicity with Kubernetes-native config:

```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
```

**Single node cost:** Hetzner CX32 (~€13/mo) — supports all the same manifests, just no HA.

**Limitations:**
- No workload HA (node failure = outage)
- No etcd quorum (use SQLite backend, not embedded etcd)
- Same resource limits as the single VPS
