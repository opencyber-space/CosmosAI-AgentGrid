##First Build the docker image
bash remove-agents.sh
echo "Sleeping for 20 seconds"
sleep 25
pushd ../../agent_codes
    bash build_markating_and_push.bash
popd

bash unregister-agents.sh
sleep 2
bash register-agents.sh
sleep 2
bash deploy-agents.sh

#sleep 5

#bash inference_request.sh