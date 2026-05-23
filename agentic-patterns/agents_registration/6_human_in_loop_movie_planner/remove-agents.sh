
#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/planner_agent/remove-agent.sh

bash $CUR_DIR/calendar_agent/remove-agent.sh

bash $CUR_DIR/preference_agent/remove-agent.sh

bash $CUR_DIR/bookmyshow_agent/remove-agent.sh
