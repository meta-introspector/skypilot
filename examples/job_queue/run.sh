#!/bin/bash -x
# ~root/sky_workdir
# /var/task/agent_workspace/run.sh
export HOME=/home/swarms
unset CONDA_EXE
unset CONDA_PYTHON_EXE
export PATH=/var/task/agent_workspace/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if [ ! -f /var/task/agent_workspace/.venv/ ];
then
   virtualenv /var/task/agent_workspace/.venv/
fi
#ls /var/task/agent_workspace/.venv/bin/activate
. /var/task/agent_workspace/.venv/bin/activate

pip install fastapi   uvicorn  termcolor

# install wr
pip install -e /opt/swarms/
# pip install swarms # failed on opencv
# pip install dotenv

#cd /var/task/agent_workspace
cd /var/task/
pip install -e  /opt/swarms-memory

pip install "fastapi[standard]"
pip install "loguru"

pip install  pydantic==2.8.2
pip freeze
python /opt/swarms/api/main.py
#bash

