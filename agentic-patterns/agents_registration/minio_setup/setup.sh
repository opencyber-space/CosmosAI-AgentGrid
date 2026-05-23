#!/bin/bash

kubectl create ns alerts
kubectl create -f secrets.yml

# Create minio directory in node where the pod will be scheduled
# replace nodeName: agents-worker-node2 with your node name in minio_deploy.yaml
mkdir -p /home/ubuntu/minio

kubectl create -f minio_deploy.yaml

