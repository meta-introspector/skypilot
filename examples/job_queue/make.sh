#!/bin/bash 
# now convert this into a makefile that tests each size of aws instance types in a structured matrix from small to large, and doing expensive ones after cheaper ones failed.
# generate a directory structure for the output per type and wish it into existst as dynamic targets
#

# t3.small
#t2.micro t3.small c5.large T4g.large-Linux
#m4.xlarge r5.large
## us-east-1: ami-070b8a957568adf70 # (suse-sle-micro-6-0-byos-v20241204-hvm-ssd-arm64

#us-east-1: ami-0c2a1f58a3414ec50 # (debian-12-amd64-20241201-1948)
#us-east-2: ami-012d573ea418f6053 # (debian-12-amd64-20241201-1948)
#us-west-1: ami-0e0fa77836d91d50a # (debian-12-amd64-20241201-1948)
#us-west-2: ami-087669cf9d44ccdde # (debian-12-amd64-20241201-1948)
#AMI=ami-0c2a1f58a3414ec50
AMI=docker:python:latest
REGION=us-east-1

#
INSTANCE_SIZES="t3.large"
for instance_size in $INSTANCE_SIZES;
do echo
   echo "Testing with instance size: $instance_size"
   sky launch -t $instance_size \
       --use-spot \
       -y \
       -c swarms \
       --image-id $AMI \
       --region=$REGION \
       --memory=8+ \
       cluster_docker.yaml
#                                   GB (e.g., ``--memory=16`` (exactly 16GB),
#   -s, --detach-setup              If True, run setup in non-interactive mode
#                                   as part of the job itself. You can safely
#                                   ctrl-c to detach from logging, and it will
#                                   not interrupt the setup process. To see the
#                                   logs again after detaching, use `sky logs`.
#                                   To cancel setup, cancel the job via `sky
#                                   cancel`. Useful for long-running setup
#                                   commands.
#   -d, --detach-run                If True, as soon as a job is submitted,
#                                   return from this call and do not stream
#                                   execution logs.
#   --docker                        If used, runs locally inside a docker
#                                   container.
#   --region TEXT                   The region to use. If specified, overrides
#   --zone TEXT                     The zone to use. If specified, overrides the
#   --num-nodes INTEGER             Number of nodes to execute the task on.
#   --cpus TEXT                     Number of vCPUs each instance must have
#   --memory TEXT                   Amount of memory each instance must have in
#   --disk-size INTEGER             OS disk size in GBs.
#   --disk-tier [low|medium|high|ultra|best|none]
#   --use-spot / --no-use-spot      Whether to request spot instances. If
#   --image-id TEXT                 Custom image id for launching the instances.
#   --env-file DOTENV_VALUES        Path to a dotenv file with environment
#   --env _PARSE_ENV_VAR            Environment variable to set on the remote
#   --gpus TEXT                     Type and number of GPUs to use. Example
#   -t, --instance-type TEXT        The instance type to use. If specified,
#   --ports TEXT                    Ports to open on the cluster. If specified,
#   -i, --idle-minutes-to-autostop INTEGER
#   --down                          Autodown the cluster: tear down the cluster
#   -r, --retry-until-up            Whether to retry provisioning infinitely
#   -y, --yes                       Skip confirmation prompt.
#   --no-setup                      Skip setup phase when (re-)launching
#   --clone-disk-from, --clone TEXT
#   --fast                          [Experimental] If the cluster is already up

   if [ $? -eq 0 ]; then 
       sky exec swarms job-install-swarms.yaml; 
       sky exec swarms jobswarms.yaml; 
   else 
       echo "Test failed for instance size: $instance_size";
#       sky down swarms -y
       break; 
   fi;
#   sky down swarms -y
done

#launch: $(generate "some how magically we create output/size-${Type}/test-${TestName}/first-report.org targets in a intelligent matrix")

#output/size-${Type}/test-${TestName}/first-report.org
#	bash ./generate_report.sh ${Type} ${TestName}

