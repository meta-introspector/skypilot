#!/bin/bash -x
# ~root/sky_workdir
# /var/task/agent_workspace/run.sh
export HOME=/home/swarms
if [ ! -f /var/task/agent_workspace/.venv/ ];
then
   virtualenv /var/task/agent_workspace/.venv/
fi
#ls /var/task/agent_workspace/.venv/bin/activate
. /var/task/agent_workspace/.venv/bin/activateo
pip install fastapi loguru pydantic uvicorn  termcolor

# install wr
pip install -e /opt/swarms/
# pip install swarms # failed on opencv
# pip install dotenv

#cd /var/task/agent_workspace
cd /var/task/
pip install -e  /opt/swarms-memory

pip install  pydantic==2.8.2

unset CONDA_EXE
unset CONDA_PYTHON_EXE
export HOME=/home/swarms
export PATH=/var/task/agent_workspace/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

pip install "fastapi[standard]"

#fastapi /opt/swarms/api/agent_api.py
python /opt/swarms/api/main.py
#bash
