#!/bin/bash

kubectl create ns alerts
kubectl create -f secrets.yml

# Create minio directory in node where the pod will be scheduled
# replace nodeName: agents-worker-node2 with your node name in minio_deploy.yaml
# sudo useradd -m ubuntu  --> for ubuntu user creation and creating /home/ubuntu

mkdir -p /home/ubuntu/minio

kubectl create -f minio_deploy.yaml

#if image viewing capability is needed for the bucket then do below steps
# $ docker run -it --entrypoint=/bin/sh --net=host --name miniomc minio/mc
# > mc alias set myminio http://EXTERNALIP:32752/
# Give the access and secrets from secrets.yaml
# mc anonymous set download myminio/marketing-images
# mc anonymous set download myminio/dev-code-bucket

