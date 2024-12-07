#!/bin/bash 
# now convert this into a makefile that tests each size of aws instance types in a structured matrix from small to large, and doing expensive ones after cheaper ones failed.
# generate a directory structure for the output per type and wish it into existst as dynamic targets
#
INSTANCE_SIZES=" t3.medium t3.large"
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

for instance_size in $INSTANCE_SIZES;
do echo
   echo "Testing with instance size: $instance_size"
   sky launch -t $instance_size --use-spot -y -c swarms cluster_docker.yaml --image-id $AMI --region=$REGION; 
   if [ $? -eq 0 ]; then 
       sky exec swarms job-install-swarms.yaml; 
       sky exec swarms jobswarms.yaml; 
   else 
       echo "Test failed for instance size: $instance_size";
       sky down swarms -y
       break; 
   fi;
   sky down swarms -y
done

#launch: $(generate "some how magically we create output/size-${Type}/test-${TestName}/first-report.org targets in a intelligent matrix")

#output/size-${Type}/test-${TestName}/first-report.org
#	bash ./generate_report.sh ${Type} ${TestName}

