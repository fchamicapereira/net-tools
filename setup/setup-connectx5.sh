#!/bin/bash

set -euo pipefail

if !cat /etc/os-release | grep -q "VERSION_ID=\"20.04\""; then
	echo "Expecting Ubuntu 20.04. Exiting"
	exit 1
fi

wget https://content.mellanox.com/ofed/MLNX_OFED-5.8-2.0.3.0/MLNX_OFED_LINUX-5.8-2.0.3.0-ubuntu20.04-x86_64.tgz
tar xvfz MLNX_OFED_LINUX-5.8-2.0.3.0-ubuntu20.04-x86_64.tgz
cd MLNX_OFED_LINUX-5.8-2.0.3.0-ubuntu20.04-x86_64
yes | sudo ./mlnxofedinstall --dpdk
sudo /etc/init.d/openibd restart