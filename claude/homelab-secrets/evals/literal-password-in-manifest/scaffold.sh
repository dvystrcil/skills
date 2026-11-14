#!/usr/bin/env bash
set -euo pipefail
mkdir -p deploy
cat > deploy/kustomization.yaml <<'Y'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: billing
resources:
  - deployment.yaml
Y
cat > deploy/deployment.yaml <<'Y'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing
spec:
  replicas: 1
  selector:
    matchLabels: {app: billing}
  template:
    metadata:
      labels: {app: billing}
    spec:
      containers:
        - name: billing
          image: harbor.example.invalid/billing:1.4.2
          env:
            - name: DB_HOST
              value: billing-postgres-rw
Y
