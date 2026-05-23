#!/bin/bash
##First Build the docker image
bash remove-agents.sh
echo "Sleeping for 30 seconds"
sleep 30
pushd ../../agent_codes
    bash build_debater_and_push.bash
popd

bash unregister-agents.sh
sleep 2
bash register-agents.sh
sleep 2
bash deploy-agents.sh
