#!/usr/bin/env bash
# deploy.sh — deploy the full BMAD crew stack to Kubernetes and open the UI.
#
# Usage:
#   ./scripts/deploy.sh                 # apply all manifests, then wait for URL
#   ./scripts/deploy.sh --port-forward  # use kubectl port-forward instead of LoadBalancer
#
# Prerequisites:
#   - kubectl configured and pointing at your target cluster
#   - images pushed to GHCR (CI/CD does this on push to main)
#   - k8s/secret.yaml filled in (GITHUB_PERSONAL_ACCESS_TOKEN, etc.)

set -euo pipefail

NAMESPACE="bmad-crew"
UI_SVC="bmad-crew-ui"
PORT_FORWARD=false
LOCAL_PORT=3000

for arg in "$@"; do
  [[ "$arg" == "--port-forward" ]] && PORT_FORWARD=true
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── 1. Apply manifests ────────────────────────────────────────────────────────

echo "▶ Applying namespace..."
kubectl apply -f "$REPO_ROOT/k8s/namespace.yaml"

echo "▶ Applying backend (bmad-crew)..."
kubectl apply -f "$REPO_ROOT/k8s/configmap.yaml"
kubectl apply -f "$REPO_ROOT/k8s/secret.yaml"    2>/dev/null || echo "  (secret.yaml skipped — fill in k8s/secret.yaml and re-run)"
kubectl apply -f "$REPO_ROOT/k8s/pvc.yaml"
kubectl apply -f "$REPO_ROOT/k8s/deployment.yaml"
kubectl apply -f "$REPO_ROOT/k8s/service.yaml"
kubectl apply -f "$REPO_ROOT/k8s/hpa.yaml"       2>/dev/null || true

echo "▶ Applying frontend (bmad-crew-ui)..."
kubectl apply -f "$REPO_ROOT/ui/k8s/configmap.yaml"
kubectl apply -f "$REPO_ROOT/ui/k8s/deployment.yaml"
kubectl apply -f "$REPO_ROOT/ui/k8s/service.yaml"

# ── 2. Wait for pods ──────────────────────────────────────────────────────────

echo ""
echo "⏳ Waiting for backend pod to be ready..."
kubectl rollout status deployment/bmad-crew -n "$NAMESPACE" --timeout=120s

echo "⏳ Waiting for frontend pod to be ready..."
kubectl rollout status deployment/bmad-crew-ui -n "$NAMESPACE" --timeout=120s

# ── 3. Get URL ────────────────────────────────────────────────────────────────

echo ""
if [[ "$PORT_FORWARD" == "true" ]]; then
  # Local clusters (kind, k3d, minikube) that don't provision LoadBalancer IPs.
  echo "▶ Starting port-forward → http://localhost:${LOCAL_PORT}"
  echo "  Press Ctrl-C to stop."
  echo ""
  # Open the browser first, then block on the port-forward.
  (sleep 1 && open "http://localhost:${LOCAL_PORT}" 2>/dev/null \
              || xdg-open "http://localhost:${LOCAL_PORT}" 2>/dev/null \
              || echo "  Open http://localhost:${LOCAL_PORT} in your browser") &
  kubectl port-forward \
    -n "$NAMESPACE" \
    "svc/${UI_SVC}" \
    "${LOCAL_PORT}:80"
else
  # Cloud clusters (GKE, EKS, AKS) that provision an external IP.
  echo "⏳ Waiting for LoadBalancer external IP (may take 60–90 s on cloud)..."
  EXTERNAL_IP=""
  for i in $(seq 1 30); do
    EXTERNAL_IP=$(kubectl get svc "$UI_SVC" -n "$NAMESPACE" \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
    # Some clouds use hostname instead of IP (e.g. AWS ELB)
    [[ -z "$EXTERNAL_IP" ]] && \
      EXTERNAL_IP=$(kubectl get svc "$UI_SVC" -n "$NAMESPACE" \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
    if [[ -n "$EXTERNAL_IP" ]]; then
      break
    fi
    echo -n "."
    sleep 5
  done
  echo ""

  if [[ -z "$EXTERNAL_IP" ]]; then
    echo ""
    echo "⚠️  LoadBalancer IP not yet assigned."
    echo "   Check status:  kubectl get svc ${UI_SVC} -n ${NAMESPACE}"
    echo "   For local clusters, re-run with:  ./scripts/deploy.sh --port-forward"
  else
    UI_URL="http://${EXTERNAL_IP}"
    echo ""
    echo "✅ BMAD Crew UI is live at: ${UI_URL}"
    echo ""
    echo "   Backend API:   http://$(kubectl get svc bmad-crew -n "$NAMESPACE" \
      -o jsonpath='{.spec.clusterIP}'):80  (cluster-internal)"
    echo ""
    # Open browser
    open "$UI_URL" 2>/dev/null \
      || xdg-open "$UI_URL" 2>/dev/null \
      || echo "   Open your browser at: ${UI_URL}"
  fi
fi
