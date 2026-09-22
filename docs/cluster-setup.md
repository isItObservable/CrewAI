# Provision a Kubernetes cluster

The BMAD crew runs on any conformant Kubernetes cluster. If you already have one
and `kubectl get nodes` returns healthy nodes, **skip ahead to
[`TUTORIAL.md` step 8](../TUTORIAL.md#8-deploy-to-kubernetes)**.

If you need a cluster, the fastest option is a local one — no cloud account or
homelab required.

---

## Local cluster with kind

[kind](https://kind.sigs.k8s.io/) (Kubernetes-in-Docker) spins up a
single-node cluster in seconds and works on macOS, Linux, and Windows.

### Prerequisites

- Docker Desktop (or Docker Engine on Linux) running.
- `kind` installed: `brew install kind` (macOS) or see
  [kind.sigs.k8s.io](https://kind.sigs.k8s.io/docs/user/quick-start/#installation).
- `kubectl` installed: `brew install kubectl` or via your package manager.

### Create the cluster

```bash
kind create cluster --name bmad-crew
kubectl get nodes   # should show one node in Ready state
```

### MetalLB (LoadBalancer IPs on kind)

The CopilotKit UI service is `type: LoadBalancer`. On a cloud cluster a cloud
load-balancer IP is assigned automatically. On kind you need MetalLB to give
it an IP from your Docker bridge network:

```bash
# Install MetalLB
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.9/config/manifests/metallb-native.yaml
kubectl -n metallb-system rollout status deploy/controller --timeout=90s

# Find the Docker bridge subnet kind uses (usually 172.18.0.0/16)
docker network inspect kind | grep -A2 '"Subnet"'

# Create an IPAddressPool in a free range of that subnet
# Example: if the subnet is 172.18.0.0/16 use 172.18.255.200-172.18.255.250
kubectl apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: kind-pool
  namespace: metallb-system
spec:
  addresses:
  - 172.18.255.200-172.18.255.250   # adjust to your docker subnet
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: kind-l2
  namespace: metallb-system
EOF
```

> **Ollama reachability.** Pods inside kind must reach your Ollama host. If
> Ollama runs on your laptop (same machine as Docker), use the Docker host
> gateway IP (`host-gateway` or `172.17.0.1` on Linux, `host.docker.internal`
> on macOS/Windows) instead of `localhost`.

### Tear down

```bash
kind delete cluster --name bmad-crew
```

---

Cluster ready? Continue with [`TUTORIAL.md` step 8 — Deploy to
Kubernetes](../TUTORIAL.md#8-deploy-to-kubernetes).
