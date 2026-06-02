#!/bin/bash

python3 deployer.py \
    --base-url=http://x.x.x.x:30721 \
    create \
    --kubeconfig=/home/cognitifai/configs/cluster-6.yaml \
    --deployer-id='deployer-123' \
    --deployer-public-ip="x.x.x.x"

