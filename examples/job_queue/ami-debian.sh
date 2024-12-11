#!/usr/bin/env bash

regions=(
#    "eu-central-1"
#    "eu-north-1"
#    "eu-west-1"
#    "eu-west-2"
#    "eu-west-3"
    "us-east-1"
    "us-east-2"
    "us-west-1"
    "us-west-2"
)

ami_name="debian-12-amd64-20241201-1948"

for region in "${regions[@]}"; do
    ami_info=$(aws ec2 describe-images \
        --region "$region" \
        --owners amazon \
        --filters "Name=name,Values=$ami_name" \
        --query 'sort_by(Images, &CreationDate)[-1].[ImageId, Name]' \
        --output text)
    if [ ! -z "$ami_info" ]; then
        ami_id=$(echo "$ami_info" | cut -f1)
        ami_full_name=$(echo "$ami_info" | cut -f2)
        echo "$region: $ami_id # ($ami_full_name)"
    fi
done
