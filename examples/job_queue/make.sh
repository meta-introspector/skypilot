#!/bin/bash 
# now convert this into a makefile that tests each size of aws instance types in a structured matrix from small to large, and doing expensive ones after cheaper ones failed.
# generate a directory structure for the output per type and wish it into existst as dynamic targets
#
INSTANCE_SIZES="t4g.small t4g.medium t4g.large"
#t2.micro t3.small c5.large T4g.large-Linux
#m4.xlarge r5.large

for instance_size in $INSTANCE_SIZES;
do echo
   echo "Testing with instance size: $instance_size"; \
       # us-east-1: ami-070b8a957568adf70 # (suse-sle-micro-6-0-byos-v20241204-hvm-ssd-arm64
       sky launch -t $instance_size --use-spot -y -c swarms cluster_docker.yaml --image-id ami-070b8a957568adf70; 
       if [ $$? -eq 0 ]; then 
	   sky exec swarms job-install-swarms.yaml; 
	   sky exec swarms jobswarms.yaml; 
       else 
	   echo "Test failed for instance size: $instance_size"; 
	   break; 
       fi;
       sky down swarms
done

#launch: $(generate "some how magically we create output/size-${Type}/test-${TestName}/first-report.org targets in a intelligent matrix")

#output/size-${Type}/test-${TestName}/first-report.org
#	bash ./generate_report.sh ${Type} ${TestName}

