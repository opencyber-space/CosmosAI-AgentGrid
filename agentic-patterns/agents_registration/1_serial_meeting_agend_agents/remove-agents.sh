
#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/1_meeting-expert-brainstormer/remove-agent.sh

bash $CUR_DIR/1_meeting-agenda-architect/remove-agent.sh

bash $CUR_DIR/1_meeting-invitation-crafter/remove-agent.sh