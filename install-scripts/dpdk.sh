#!/bin/bash

set -euo pipefail

DPDK_VERSION="22.11.2"
RTE_TARGET=x86_64-native-linux-gcc
DPDK_DIR=/opt/dpdk

export DEBIAN_FRONTEND=noninteractive

get_deps() {
	sudo apt update
	sudo apt-get -y install build-essential make vim sudo wget curl git \
		python3-pyelftools python3-pip linux-generic linux-headers-generic \
		cmake pkg-config libnuma-dev libpcap-dev lshw kmod iproute2 net-tools \
    ninja-build
	pip3 install meson
}

install_dpdk() {
	if [ -d $DPDK_DIR ]; then
		echo "DPDK directory already exists: $DPDK_DIR."
		return 0
	fi

	pushd /tmp
		DPDK_TAR="dpdk-$DPDK_VERSION.tar.xz"
		wget https://fast.dpdk.org/rel/$DPDK_TAR
		tar xJf $DPDK_TAR && rm $DPDK_TAR
		sudo mv dpdk-stable-$DPDK_VERSION $DPDK_DIR
		sudo chown -R $USER:$USER $DPDK_DIR
	popd

	pushd $DPDK_DIR
		meson build
		ninja -C build
		sudo ninja -C build install
		sudo ldconfig
	popd

	echo "export RTE_SDK=$DPDK_DIR" >> ~/.bashrc
}

get_deps
install_dpdk