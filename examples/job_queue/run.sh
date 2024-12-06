#!/bin/bash -x
# ~root/sky_workdir
# /var/task/agent_workspace/run.sh
export HOME=/home/swarms
if [ ! -f /var/task/agent_workspace/.venv/ ];
then
   virtualenv /var/task/agent_workspace/.venv/
fi
#ls /var/task/agent_workspace/.venv/bin/activate
. /var/task/agent_workspace/.venv/bin/activate
pip install fastapi loguru pydantic uvicorn swarms termcolor
# dotenv

#cd /var/task/agent_workspace
cd /var/task/

python3 /opt/swarms/api/agent_api.py
#bash
