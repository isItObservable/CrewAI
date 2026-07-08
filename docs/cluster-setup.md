# Provision a Kubernetes cluster

The BMAD crew runs on any Kubernetes cluster. This guide gives you two ways to
get one, and — importantly — keeps **every environment-specific value (Proxmox
node, IPs, GCP project) as a variable you supply.** Nothing here hard-codes our
homelab. Placeholder addresses use the reserved
[RFC 5737](https://datatracker.ietf.org/doc/html/rfc5737) documentation range
`192.0.2.0/24`; replace them with values that are free on **your** network.

- **Option A — Cluster API on Proxmox** — what we use. Declarative, reproducible,
  self-hosted. [Jump ↓](#option-a--cluster-api-on-proxmox)
- **Option B — Google Kubernetes Engine** — managed, one command, no homelab.
  [Jump ↓](#option-b--google-kubernetes-engine-gke)

Once you have a cluster and `kubectl get nodes` works, return to
[`TUTORIAL.md` step 8](../TUTORIAL.md#8-deploy-to-kubernetes).

---

## Option A — Cluster API on Proxmox

We provision our tutorial clusters with [Cluster
API](https://cluster-api.sigs.k8s.io/) (CAPI) and the
[Proxmox infrastructure provider](https://github.com/ionos-cloud/cluster-api-provider-proxmox).
The reusable manifests and render tooling live in the companion
**[proxmox-clusters](https://github.com/henrikrexed/proxmox-clusters)** repo —
clone it alongside this one.

### Prerequisites

- A **Proxmox VE** cluster you control, reachable over its API.
- A **CAPI management cluster** — any conformant k8s cluster (a local `kind`
  cluster works) with the Proxmox provider installed via
  `clusterctl init --infrastructure proxmox`.
- A **golden VM template** on Proxmox: Ubuntu + a matching Kubernetes version,
  cloud-init + qemu-guest-agent. This is your `os_image` / `template_id`.
- Local tools: `clusterctl`, `kubectl`, `kustomize`.

### 1. Supply your Proxmox credentials (never commit them)

Credentials are read from the environment and handed to the management cluster
as a Kubernetes `Secret` — they are **never** stored in git.

```sh
cp .env.example .env          # in the proxmox-clusters repo; .env is git-ignored
$EDITOR .env                  # PROXMOX_URL / PROXMOX_TOKEN / PROXMOX_SECRET
set -a; . ./.env; set +a
```

### 2. Describe *your* cluster in `values.env`

Copy the documented example and set every value for your environment. There are
**no default IPs or node names** — the render step substitutes exactly what you
put here.

```sh
cp -r clusters/example-cluster clusters/my-cluster
$EDITOR clusters/my-cluster/values.env
```

| Variable | What it is | Example |
| --- | --- | --- |
| `cluster_name` | Must match the directory name. | `my-cluster` |
| `k8s_version` | Kubernetes version; must match your golden template. | `v1.35.3` |
| `source_node` | The **Proxmox node** hosting your golden template. | `pve01` |
| `template_id` | The Proxmox VM template id to clone. | `9000` |
| `cp_replicas` / `worker_replicas` | Control-plane / worker counts. | `1` / `3` |
| `cp_disk_storage` / `worker_disk_storage` | Proxmox storage pool names on your cluster. | `local-lvm` |
| `vip` | Control-plane virtual IP (kube-vip). Free on your LAN. | `192.0.2.10` |
| `node_pool_start` / `node_pool_end` | IP range CAPI assigns to VMs. | `192.0.2.11`–`192.0.2.20` |
| `metallb_pool_start` / `metallb_pool_end` | LoadBalancer pool (≥ 32 addresses). | `192.0.2.40`–`192.0.2.71` |

**Pick IPs that are free on your network.** The VIP, node pool, MetalLB pool, and
DHCP reserve must not overlap each other or any live host. The render step
enforces those invariants and fails closed if they're violated. If you have
`arp-scan` on your LAN, the `proxmox-ip-scan` helper can discover free addresses
and pre-fill the ranges.

### 3. Render and apply

```sh
# from the proxmox-clusters repo root
.paperclip/skills/cluster-manifest-render/scripts/render.sh my-cluster
kubectl apply -k clusters/my-cluster/
# install the CNI / MetalLB / CSI add-ons your cluster needs:
kubectl apply -k policies/addons/<your-addon-set>/
```

Watch CAPI bring the cluster up, then pull its kubeconfig:

```sh
clusterctl describe cluster my-cluster
clusterctl get kubeconfig my-cluster > my-cluster.kubeconfig   # git-ignored
export KUBECONFIG=$PWD/my-cluster.kubeconfig
kubectl get nodes
```

---

## Option B — Google Kubernetes Engine (GKE)

No homelab? Run the crew on a managed cluster. GKE provides the control plane,
node management, and a cloud LoadBalancer — so the Proxmox-specific pieces
(MetalLB, kube-vip, the CAPI provider) are **not needed** on this path.

### Prerequisites

- A Google Cloud project with billing enabled.
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), authenticated:
  `gcloud auth login && gcloud config set project <your-gcp-project>`
- `kubectl` + the GKE auth plugin:
  `gcloud components install gke-gcloud-auth-plugin`
- Enable the APIs once:
  `gcloud services enable container.googleapis.com compute.googleapis.com`

### Create the cluster

Autopilot (Google manages the nodes) is the simplest:

```sh
gcloud container clusters create-auto bmad-crew \
  --project <your-gcp-project> --region <your-region>
```

…or a Standard cluster if you want to size the node pool yourself:

```sh
gcloud container clusters create bmad-crew \
  --project <your-gcp-project> --region <your-region> \
  --num-nodes 1 --machine-type e2-standard-4 \
  --release-channel regular --enable-ip-alias
```

Fetch credentials:

```sh
gcloud container clusters get-credentials bmad-crew --region <your-region>
kubectl get nodes
```

Prefer Terraform? A minimal Autopilot definition:

```hcl
provider "google" {
  project = "<your-gcp-project>"
  region  = "<your-region>"
}
resource "google_container_cluster" "primary" {
  name             = "bmad-crew"
  location         = "<your-region>"
  enable_autopilot = true
}
```

### Differences from the Proxmox path

| Concern | Proxmox / CAPI | GKE |
| --- | --- | --- |
| Control plane | You provision it (kube-vip VIP) | Google-managed |
| Nodes | CAPI clones your golden template | Managed node pool / Autopilot |
| LoadBalancer IPs | MetalLB pool in `values.env` | Cloud LB, auto-assigned — **skip MetalLB** |
| CNI | You install (Cilium / Calico) | GKE default |
| Ollama reachability | LAN-direct | Ollama must be reachable *from GKE* (VPN, public endpoint, or run Ollama in-cluster) |

### Tear down

```sh
gcloud container clusters delete bmad-crew --region <your-region>
```

---

Cluster ready? Continue with [`TUTORIAL.md` step 8 — Deploy to
Kubernetes](../TUTORIAL.md#8-deploy-to-kubernetes).
