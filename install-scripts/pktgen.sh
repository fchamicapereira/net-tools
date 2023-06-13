#!/bin/bash

set -euo pipefail

DPDK_VERSION="22.11.2"
PKTGEN_VERSION="23.06.1"
RTE_TARGET=x86_64-native-linux-gcc
PKTGEN_DIR=/opt/Pktgen-DPDK
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

install_pktgen() {
	if [ ! -d $DPDK_DIR ]; then
		echo "DPDK directory not found."
		return 1
	fi

	if [ -d $PKTGEN_DIR ]; then
		echo "Pktgen directory already exists: $PKTGEN_DIR."
		return 0
	fi

	# Building DPDK Pktgen
	sudo git clone \
		--depth 1 \
		--branch pktgen-$PKTGEN_VERSION \
		https://github.com/pktgen/Pktgen-DPDK.git \
		$PKTGEN_DIR
	
	sudo chown -R $USER:$USER $PKTGEN_DIR

	# DPDK places the libdpdk.pc (pkg-config file) in a non-standard location.
	# We need to set enviroment variable PKG_CONFIG_PATH to the location of the file.
	# On Ubuntu 20.04 build of DPDK it places the file
	# here /usr/local/lib/x86_64-linux-gnu/pkgconfig/libdpdk.pc
	# Source: https://github.com/pktgen/Pktgen-DPDK/blob/1e93fa88916b8f2c27b612d761a03cbf03d046de/INSTALL.md
	PKG_CONFIG_PATH=/usr/local/lib/x86_64-linux-gnu/pkgconfig

	pushd $PKTGEN_DIR
		# Install LUA
		sudo apt install -y lua5.3 liblua5.3-dev

		# Enable LUA scripts
		sed -i 's/export lua_enabled="-Denable_lua=false"/export lua_enabled="-Denable_lua=true"/g' \
			 ./tools/pktgen-build.sh
		./tools/pktgen-build.sh build
	popd
}

get_deps
install_pktgen