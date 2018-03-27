#!/usr/bin/env bash

source ~/tf11/bin/activate
mkdir -p trained_models
mkdir -p train_eval
start=`date +%s.%N`
CUDA_VISIBLE_DEVICES=$deviceId python ${script_path} --batch_size=$batch_size --epochs=$epochs --device_ids=$deviceId --num_gpus=${gpu_count}
end=`date +%s.%N`
runtime=$( echo "$end - $start" | bc -l )
echo "finished with execute time: ${runtime}"
python cifar10_eval.py
deactivate
rm trained_models/*
rm train_eval/*