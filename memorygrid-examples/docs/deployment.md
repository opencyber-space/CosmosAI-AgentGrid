# Deployment Guide

`agentic-memory` requires three databases: **PostgreSQL**, **ArangoDB**, and **Weaviate**.
This guide covers Kubernetes deployment using the manifests in [`k8s/`](../k8s/).

---

## Kubernetes deployment

All three databases run as `StatefulSet` workloads in the `agentic-memory` namespace,
exposed via `NodePort` services for development access from outside the cluster.

### Prerequisites

- A single-node cluster: minikube, kind, or k3s
- `kubectl` configured to target the cluster
- Node directories created for host-path volumes:

```bash
mkdir -p /data/agentic-memory/{postgres,arango,weaviate}
```

For production, replace `hostPath` in `pv-pvc.yaml` with your preferred CSI driver or
`StorageClass`.

---

### Apply order

The PVs and PVCs must exist before the StatefulSets start — apply them first:

```bash
kubectl apply -f k8s/pv-pvc.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/arango.yaml
kubectl apply -f k8s/weaviate.yaml
```

Wait for all pods to reach `Running` state before connecting:

```bash
kubectl get pods -n agentic-memory -w
```

---

## Storage — `pv-pvc.yaml`

**File:** [`k8s/pv-pvc.yaml`](../k8s/pv-pvc.yaml)

Three `PersistentVolume` / `PersistentVolumeClaim` pairs, all using `hostPath` storage.

| Database | PV name | PVC name | Capacity | Host path |
|---|---|---|---|---|
| PostgreSQL | `postgres-pv` | `postgres-pvc` | 10 Gi | `/data/agentic-memory/postgres` |
| ArangoDB | `arango-pv` | `arango-pvc` | 10 Gi | `/data/agentic-memory/arango` |
| Weaviate | `weaviate-pv` | `weaviate-pvc` | 10 Gi | `/data/agentic-memory/weaviate` |

All PVs use:
- `storageClassName: ""` — empty string bypasses StorageClass matching entirely;
  binding is guaranteed by the `claimRef` on each PV
- `persistentVolumeReclaimPolicy: Retain` — data is preserved if the PVC is deleted
- `accessModes: [ReadWriteOnce]` — single-node access

---

## PostgreSQL — `postgres.yaml`

**File:** [`k8s/postgres.yaml`](../k8s/postgres.yaml)

| Property | Value |
|---|---|
| Image | `postgres:16` |
| Database | `agent_memory` |
| User | `postgres` |
| Password | from `postgres-secret` (default: `postgres`) |
| Port | `5432` (NodePort `30432`) |
| Data path | `/var/lib/postgresql/data` (subPath `pgdata`) |
| Readiness probe | `pg_isready -U postgres` every 5s, initial 5s delay |

The schema (all five tables + indices) is created automatically by `PostgresClient` on
first connection — no manual `psql` initialization needed.

### Secret

```yaml
kind: Secret
metadata:
  name: postgres-secret
stringData:
  POSTGRES_PASSWORD: postgres   # change this for production
```

### Connect from outside the cluster

```bash
psql -h <node-ip> -p 30432 -U postgres -d agent_memory
```

### Connect from Python (NodePort)

```python
from agentic_memory.config import PostgresConfig

PostgresConfig(host="<node-ip>", port=30432, password="postgres")
```

---

## ArangoDB — `arango.yaml`

**File:** [`k8s/arango.yaml`](../k8s/arango.yaml)

| Property | Value |
|---|---|
| Image | `arangodb:3.12` |
| Root password | from `arango-secret` (default: `password`) |
| Port | `8529` (NodePort `30529`) |
| Data path | `/var/lib/arangodb3` |
| Readiness probe | `GET /_api/version` every 5s, initial 10s delay |

The `agent_memory` database and all vertex/edge collections are created automatically by
`ArangoBackend` on first connection.

### Secret

```yaml
kind: Secret
metadata:
  name: arango-secret
stringData:
  ARANGO_ROOT_PASSWORD: password   # change this for production
```

### ArangoDB web UI

```
http://<node-ip>:30529
```

Login with `root` / `password`. The `agent_memory` database appears after the first
`AgentMemory()` instance connects.

### Connect from Python (NodePort)

```python
from agentic_memory.config import ArangoConfig

ArangoConfig(url="http://<node-ip>:30529", password="password")
```

---

## Weaviate — `weaviate.yaml`

**File:** [`k8s/weaviate.yaml`](../k8s/weaviate.yaml)

| Property | Value |
|---|---|
| Image | `semitechnologies/weaviate:1.25.0` |
| HTTP port | `8080` (NodePort `30880`) |
| gRPC port | `50051` (NodePort `30851`) |
| Data path | `/var/lib/weaviate` |
| Readiness probe | `GET /v1/.well-known/ready` on port 8080 every 5s, initial 10s delay |

### Resource limits

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "1"
```

### Configuration (environment variables)

```yaml
AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
PERSISTENCE_DATA_PATH: /var/lib/weaviate
DEFAULT_VECTORIZER_MODULE: none   # embeddings are provided by the client
ENABLE_MODULES: ""
CLUSTER_HOSTNAME: node1
```

No external etcd or object store is needed — Weaviate persists directly to the PVC.

### Connect from Python (NodePort)

```python
from agentic_memory.config import WeaviateConfig

WeaviateConfig(host="<node-ip>", port=30880, grpc_port=30851)
```

---

## Verifying the deployment

```bash
# All pods ready
kubectl get pods -n agentic-memory

# Postgres
kubectl exec -n agentic-memory deploy/postgres -- pg_isready -U postgres

# ArangoDB
curl http://<node-ip>:30529/_api/version

# Weaviate
curl http://<node-ip>:30880/v1/.well-known/ready
```

---

## Connecting the library to the cluster

```python
from agentic_memory import AgentMemory
from agentic_memory.config import MemoryConfig, WeaviateConfig, ArangoConfig, PostgresConfig

NODE_IP = "<your-node-ip>"

config = MemoryConfig(
    postgres=PostgresConfig(host=NODE_IP, port=30432, password="postgres"),
    arango=ArangoConfig(url=f"http://{NODE_IP}:30529", password="password"),
    weaviate=WeaviateConfig(host=NODE_IP, port=30880, grpc_port=30851),
)

with AgentMemory(config) as mem:
    mem.remember_episode("Connected successfully", session_id="test")
```

---

## Tearing down

```bash
kubectl delete namespace agentic-memory
```

PVs are **not** deleted automatically (Retain policy). To reclaim disk space:

```bash
kubectl delete pv postgres-pv arango-pv weaviate-pv
rm -rf /data/agentic-memory
```

---

## Production considerations

| Concern | Recommendation |
|---|---|
| Secrets | Use sealed secrets, Vault, or external-secrets-operator instead of `stringData` |
| Storage | Replace `hostPath` PVs with a cloud CSI driver (EBS, GCE PD, Azure Disk) |
| Weaviate | For large-scale deployments replace standalone with Weaviate cluster mode |
| ArangoDB | Use ArangoDB Enterprise with active-failover or cluster mode |
| PostgreSQL | Use a managed service (RDS, Cloud SQL) or a Postgres Operator (Zalando, CNPG) |
| Networking | Replace `NodePort` with `ClusterIP` + Ingress or internal `Service` for production |
