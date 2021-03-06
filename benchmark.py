#!/usr/bin/env python
# coding=utf-8

""" benchmark.py: Execute tests according to a given config file.

Created by gogleyin on 3/22/18.
"""

from collections import namedtuple
import csv
import os
import time
import shutil
import subprocess
import datetime
from globalconfig import Framework, NetworkType, FCN, Status, Synthetic
from nvidiasmi import GPUManager, ModeStatus
import logging
logger = logging.getLogger(__name__ if __name__ != '__main__' else os.path.splitext(os.path.basename(__file__))[0])
logger.setLevel(logging.DEBUG)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HOST_NAME = subprocess.check_output("hostname", shell=True).strip().split('\n')[0]
TRAINING_SUMMARY_TEMPLATE = 'Average Batch Time: {batchTime}'
EVALUATION_SUMMARY_TEMPLATE = 'Accuracy: {accuracy}'

FIELDS = [
    'framework',
    'network_type',
    'network_name',
    'device_id',
    'device_count',
    'cpu_count',  # 0 means using the default value. Be careful, this is for deep learning on GPU(s).
    'batch_size',
    'number_of_epochs',
    'epoch_size',
    'learning_rate',
    'synthetic',
    'enabled'
]

TestResultFields = [
    'framework',
    'network_type',
    'network_name',
    'device_id',
    'device_count',
    'cpu_count',
    'batch_size',
    'number_of_epochs',
    'epoch_size',
    'learning_rate',
    'synthetic',
    'training_speed',
    'accuracy',
    'gpu_utilization',
    'mem_utilization',
    'max_memory_usage',
]

TestConfigEntry = namedtuple('TestConfigEntry', FIELDS)
TestResultEntry = namedtuple('TestResultEntry', TestResultFields)


def generate_configs(config_file):
    config = TestConfigEntry(Framework.tensorflow, NetworkType.fc, FCN.fcn5,
                             0, 1, 4096, 2, 60000, 0.05, Synthetic.true, Status.enabled)
    with open(config_file, 'wb') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(FIELDS)
        writer.writerow(config)
        writer.writerow(TestConfigEntry('tensorflow', 'cnn', 'alexnet', 0, 1, 1024, 2, 50000, 0.01, False, True))


def generate_log_file(config):
    if "-1" in config.device_id:
        device_name = 'cpuName'
    else:
        device_name = 'gpuName'
    log_file_name = '-'.join([config.framework, config.network_type, config.network_name, device_name,
                              '*%s' % config.device_count,
                              'b%s' % config.batch_size,
                             time.ctime(), HOST_NAME + '.log'])
    log_file_name = log_file_name.replace(" ", "_")
    return log_file_name


def save_a_result(test_result_entry, result_file):
    with open(result_file, 'wb') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(test_result_entry)


def pretest(gpus, log_dir):
    for gpu in gpus:
        if gpu.ecc_mode.status == ModeStatus.On:
            gpu.ecc_mode.turn_off()
        if gpu.persistence_mode.status == ModeStatus.Off:
            gpu.persistence_mode.turn_on()
        if gpu.auto_boost_mode.status == ModeStatus.On:
            gpu.auto_boost_mode.turn_off()

    collect_env_sh = os.path.join(PROJECT_ROOT, 'collect_systen_info.sh')
    if os.path.isfile(collect_env_sh):
        system_info_log = os.path.join(log_dir, 'system-info.txt')
        cmd = 'bash %s %s' % (collect_env_sh, system_info_log)
        logger.debug('[Querying system info] Executing shell: %s' % cmd)
        if os.system(cmd) != 0:
            logger.error('[Querying system info] Executing shell failed: %s' % cmd)
        else:
            logger.debug('[Querying system info] Executing shell success: %s' % cmd)


def run(config_file, log_dir=None, test_summary_file=None):
    if not log_dir:
        timestamp = datetime.datetime.now()
        log_dir = 'GpuBenchmarkLog_%s' % timestamp.strftime('%y%m%d-%H%M%S')
    if os.path.isdir(log_dir):
        shutil.rmtree(log_dir)
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    if not test_summary_file:
        test_summary_file = os.path.join(log_dir, 'all_results.csv')
    with open(test_summary_file, 'wb') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(TestResultFields)

    gpus = GPUManager.list_gpus()
    gpu_count = len(gpus)
    logger.info('Found %d GPUs.' % len(gpus))
    pretest(gpus, log_dir)
    devId = ','.join([str(i) for i in range(gpu_count)])  # use all GPUs.

    with open(config_file, 'rb') as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)  # skip the header
        configs = [TestConfigEntry(*row) for row in reader]
        for config in configs:
            if config.enabled != Status.enabled:
                continue
            os.environ['training_speed'] = str(0)
            logger.info('===== Running test with config: %s =====' % str(config))
            sub_benchmark_file_name = config.framework + 'bm.py'
            sub_benchmark = os.path.join(PROJECT_ROOT, 'frameworks', config.framework, sub_benchmark_file_name)
            if not os.path.exists(sub_benchmark):
                logger.error('File not found: %s' % (sub_benchmark,))
                continue
            log_file_name = generate_log_file(config)
            log_file_path = os.path.join(log_dir, log_file_name)
            network_dir = os.path.join(log_dir, config.framework, config.network_type, config.network_name)
            config_dir_name = '--'.join([str(config.device_id),
                                         str(config.device_count),
                                         str(config.batch_size),
                                         str(config.number_of_epochs),
                                         str(config.epoch_size),
                                         str(config.learning_rate),
                                         str(config.synthetic)]).replace(' ', '_')
            # configs may be the same, so we add a timestamp to distinguish them.
            config_dir = os.path.join(network_dir,
                                      config_dir_name,
                                      datetime.datetime.now().strftime('%y%m%d-%H%M%S'))
            if not os.path.isdir(config_dir):
                os.makedirs(config_dir)
            args = {
                'netType': config.network_type,
                'log': log_file_path,
                'batchSize': config.batch_size,
                'numEpochs': config.number_of_epochs,
                'epochSize': config.epoch_size,
                'network': config.network_name,
                'lr': config.learning_rate,
                'log_dir': config_dir,
                'gpuCount': config.device_count,
                'devId': config.device_id.replace(';', ','),
                'synthetic': config.synthetic,
                'test_summary_file': test_summary_file,
                'cpuCountForGpu': config.cpu_count,
            }
            args_str = ' '.join(['-%s %s' % (k, v) for k, v in args.items()])
            cmd = 'python {scriptFile} {argsStr}'.format(scriptFile=sub_benchmark, argsStr=args_str)
            logger.debug('Executing shell: %s' % cmd)
            try:
                subprocess.check_call(cmd, shell=True)
                logger.info('Executing shell success: %s' % cmd)
                logger.info('Config run success: %s' % str(config))
            except subprocess.CalledProcessError:
                logger.error('Executing shell failed: %s' % cmd)
                logger.info('Config run failed: %s' % str(config))
                continue


def set_arguments():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-config", "--config_file", help="file path of config file", type=str)
    parser.add_argument("-log_dir", "--log_dir", help="Directory for logs.", type=str, default=None)
    parser.add_argument("-test_summary_file", "--test_summary_file", help="test_summary_file", type=str, default=None)
    args = parser.parse_args()
    run(args.config_file, log_dir=args.log_dir, test_summary_file=args.test_summary_file)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    set_arguments()
    # _config_file = '/tmp/config.csv'
    # generate_configs(_config_file)
    # run(_config_file)
