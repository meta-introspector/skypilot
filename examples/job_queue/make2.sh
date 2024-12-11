#!/bin/bash 
. .env # load env

AMI=docker:python:latest
REGION=us-east-1
INSTANCE_SIZES="t3.large"
for instance_size in $INSTANCE_SIZES;
do echo
   echo "Testing with instance size: $instance_size"
   sky launch -t $instance_size \
       --use-spot \
       -y \
       --retry-until-up \
       -c swarms2 \
       --image-id $AMI \
       --ports 8000 \
       --region=$REGION \
       --memory=8+ \
       --env-file .env\
       cluster_docker.yaml

   if [ $? -eq 0 ]; then 
       sky exec --env-file .env swarms job-install-swarms.yaml
       sky exec --detach-run --env-file .env swarms jobswarms.yaml

  #        -d, --detach-run                If True, as soon as a job is submitted,
  # -n, --name TEXT                 Task name. Overrides the "name" config in
  # --workdir DIRECTORY             If specified, sync this dir to the remote
  # --cloud TEXT                    The cloud to use. If specified, overrides
  # --region TEXT                   The region to use. If specified, overrides
  # --zone TEXT                     The zone to use. If specified, overrides the
  # --num-nodes INTEGER             Number of nodes to execute the task on.
  # --cpus TEXT                     Number of vCPUs each instance must have
  # --memory TEXT                   Amount of memory each instance must have in
  # --disk-size INTEGER             OS disk size in GBs.
  # --disk-tier [low|medium|high|ultra|best|none]
  # --use-spot / --no-use-spot      Whether to request spot instances. If
  # --image-id TEXT                 Custom image id for launching the instances.
  # --env-file DOTENV_VALUES        Path to a dotenv file with environment
  # --env _PARSE_ENV_VAR            Environment variable to set on the remote
  # --gpus TEXT                     Type and number of GPUs to use. Example
  # -t, --instance-type TEXT        The instance type to use. If specified,
  # --ports TEXT                    Ports to open on the cluster. If specified,

   else 
       echo "Test failed for instance size: $instance_size";
#       sky down swarms -y
       break; 
   fi;
#   sky down swarms -y
done
