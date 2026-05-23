
#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/orchestrator_agent/remove-agent.sh

bash $CUR_DIR/content_creator_agent/remove-agent.sh

bash $CUR_DIR/image_generator_agent/remove-agent.sh

bash $CUR_DIR/image_reviewer_agent/remove-agent.sh

bash $CUR_DIR/social_media_compaigner/remove-agent.sh
