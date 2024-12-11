#!/bin/bash
. .env # load env

AMI=docker:python:latest
REGION=us-east-1

echo "Testing with instance size: $instance_size"
#sky exec --env-file .env swarms2 job-install-swarms.yaml; 
sky exec --env-file .env swarms2 jobswarms.yaml; 

