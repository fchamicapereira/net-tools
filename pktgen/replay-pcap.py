#!/usr/bin/env python3

import os
import requests
import subprocess
import json
import argparse
import time
import re

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PKTGEN_DIR = '/opt/Pktgen-DPDK'

PKTGEN_SCRIPT        = f'{PKTGEN_DIR}/scripts/replay.lua'
PKTGEN_RESULTS       = f'{PKTGEN_DIR}/results.tsv'
RESULTS_FILENAME     = 'results.csv'

MIN_RATE             = 0   # Gbps
MAX_RATE             = 100 # Gbps

DEFAULT_TX_CORES     = 2
DEFAULT_RX_CORES     = 2
DEFAULT_DURATION_SEC = 10 # seconds

DPDK_PKTGEN_SCRIPT_TEMPLATE = \
"""
package.path = package.path ..";?.lua;test/?.lua;app/?.lua;../?.lua"

require "Pktgen";

local duration  = {{duration}};
local sendport  = "{{sendport}}";
local recvport  = "{{recvport}}";
local rate      = {{rate}};
local delayTime = 1000;
local n_to_send = 0; -- continuous stream of traffic

function main()
	pktgen.screen("off");
	pktgen.clr();

	pktgen.set(sendport, "rate", rate);
	pktgen.set("all", "count", n_to_send);

	pktgen.start(sendport);
	pktgen.delay(duration);
	pktgen.stop(sendport);
	pktgen.delay(delayTime);
	
	local stats = pktgen.portStats("all", "port");

	local txStat = stats[tonumber(sendport)];
	local rxStat = stats[tonumber(recvport)];

	local tx = txStat["opackets"];
	local rx = rxStat["ipackets"];

	local txBytes = txStat["obytes"];
	local rxBytes = rxStat["ibytes"];

	local recordedTxRate = ((txBytes + 20) * 8.0) / (duration / 1e3);
	local recordedRxRate = ((rxBytes + 20) * 8.0) / (duration / 1e3);

	local recordedTxPacketRate = tx / (duration / 1e3);
	local recordedRxPacketRate = rx / (duration / 1e3);

	local loss = (tx - rx) / tx;

	local outFile = io.open("{{results_filename}}", "w");
	outFile:write(
		string.format("%.3f\t%.3f\t%.3f\t%.3f\t%3.3f\\n",
			recordedTxRate,
			recordedTxPacketRate,
			recordedRxRate,
			recordedRxPacketRate,
			loss
		)
	);
	
	pktgen.quit();
end

main();
"""

def build_lua_script(rate, tx, rx, duration_sec):
	script = DPDK_PKTGEN_SCRIPT_TEMPLATE
	script = script.replace('{{sendport}}', str(tx['port']))
	script = script.replace('{{recvport}}', str(rx['port']))
	script = script.replace('{{rate}}', str(rate))
	script = script.replace('{{duration}}', str(duration_sec * 1000))
	script = script.replace('{{results_filename}}', PKTGEN_RESULTS)
	
	f = open(PKTGEN_SCRIPT, 'w')
	f.write(script)
	f.close()

def get_device_numa_node(pcie_dev):
	try:
		cmd  = [ "lspci", "-s", pcie_dev, "-vv" ]
		info = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
		info = info.decode('utf-8')
		result = re.search(r"NUMA node: (\d+)", info)
		
		if not result:
			return 0

		assert result
		return int(result.group(1))
	except subprocess.CalledProcessError:
		print(f'Invalid PCIE dev {pcie_dev}')
		exit(1)

def get_all_cpus():
	cmd    = [ "lscpu" ]
	info   = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
	info   = info.decode('utf-8')
	result = re.search(r"CPU\(s\):\D+(\d+)", info)

	assert result
	total_cpus = int(result.group(1))
	
	return [ x for x in range(total_cpus) ]

def get_numa_node_cpus(node):
	cmd  = [ "lscpu" ]
	info = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
	info = info.decode('utf-8')
	info = [ line for line in info.split('\n') if 'NUMA' in line ]

	assert len(info) > 0
	total_nodes_match = re.search(r"\D+(\d+)", info[0])
	
	assert total_nodes_match
	total_nodes = int(total_nodes_match.group(1))

	if node > total_nodes:
		print(f'Requested NUMA node ({node}) >= available nodes ({total_nodes})')
		exit(1)
	
	if total_nodes == 1:
		return get_all_cpus()

	assert len(info) == total_nodes + 1
	node_info = info[node + 1]

	if '-' in node_info:
		cpus_match = re.search(r"\D+(\d+)\-(\d+)$", node_info)
		assert cpus_match

		min_cpu = int(cpus_match.group(1))
		max_cpu = int(cpus_match.group(2))

		return [ cpu for cpu in range(min_cpu, max_cpu + 1) ]

	cpus_match = re.search(r"\D+([\d,]+)$", node_info)
	assert cpus_match
	return [ int(i) for i in cpus_match.groups(0)[0].split(',') ]

def get_pcie_dev_cpus(pcie_dev):
	numa = get_device_numa_node(pcie_dev)
	cpus = get_numa_node_cpus(numa)
	print(f'[*] PCIe={pcie_dev} NUMA={numa} CPUs={cpus}')
	return cpus

def get_port_from_pcie_dev(pcie_dev):
	# I'm not sure this is the convention, but it works so far
	return int(pcie_dev.split('.')[1])

def build_pktgen_command(pcap, rate, tx, rx, master_core, duration_sec):
	all_used_cores = \
		master_core + \
		tx['cores']['tx'] + \
		tx['cores']['rx'] + \
		rx['cores']['tx'] + \
		rx['cores']['rx']

	all_used_cores = ','.join([ str(c) for c in all_used_cores ])

	tx_rx_cores    = '/'.join([ str(c) for c in tx['cores']['rx'] ])
	tx_tx_cores    = '/'.join([ str(c) for c in tx['cores']['tx'] ])

	rx_rx_cores    = '/'.join([ str(c) for c in rx['cores']['rx'] ])
	rx_tx_cores    = '/'.join([ str(c) for c in rx['cores']['tx'] ])

	tx_cfg         = f"[{tx_rx_cores}:{tx_tx_cores}].{tx['port']}"
	rx_cfg         = f"[{rx_rx_cores}:{rx_tx_cores}].{rx['port']}"

	cmd = [
		"sudo", "-E",
		f"{PKTGEN_DIR}/Builddir/app/pktgen",
		"-l", f"{all_used_cores}",
		"-n", "4",
		"--proc-type", "auto",
		"-a", tx['dev'],
		"-a", rx['dev'],
		"--",
		"-N", "-T", "-P",
		"-m", f"{tx_cfg},{rx_cfg}",
		"-s", f"{tx['port']}:{pcap}",
		"-f", f"{PKTGEN_SCRIPT}",
	]

	print(f'[*] Pktgen command: {" ".join(cmd)}')
	
	return cmd

def run_pktgen(pcap, rate, tx, rx, master_core, duration_sec, dry_run, verbose):
	build_lua_script(rate, tx, rx, duration_sec)	
	pktgen_cmd = build_pktgen_command(pcap, rate, tx, rx, master_core, duration_sec)

	if dry_run:
		exit(0)

	if verbose:
		proc = subprocess.run(pktgen_cmd, cwd=PKTGEN_DIR)
	else:
		proc = subprocess.run(
			pktgen_cmd,
			cwd=PKTGEN_DIR,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL
		)

	assert proc.returncode == 0

	f = open(PKTGEN_RESULTS, 'r')
	results = f.readline()
	f.close()

	os.remove(PKTGEN_RESULTS)
	results = results.split('\t')
	
	data = {
		'tx': {
			'rate': float(results[0]) / 1e9,
			'pkt_rate': float(results[1]) / 1e6,
		},
		'rx': {
			'rate': float(results[2]) / 1e9,
			'pkt_rate': float(results[3]) / 1e6,
		},
		'loss': float(results[4]) * 100,
	}

	print(f"[*] TX   {data['tx']['pkt_rate']:.3f} Mpps {data['tx']['rate']:.3f} Gbps")
	print(f"[*] RX   {data['rx']['pkt_rate']:.3f} Mpps {data['rx']['rate']:.3f} Gbps")
	print(f"[*] loss {data['loss']} %")

	return data

def select_cores(all_cores, num_cores, to_ignore):
	filtered_cores = [ core for core in all_cores if core not in to_ignore ]
	
	if len(filtered_cores) < num_cores:
		print(f'Number of requested cores {num_cores} > available cores {len(all_cores)}')
		print(f'Available cores: {all_cores}')
		print(f'Filtered cores:  {filtered_cores}')
		exit(1)
	
	return filtered_cores[:num_cores]

def run(tx_pcie_dev, rx_pcie_dev, pcap, num_tx_cores, num_rx_cores, rate, duration_sec, dry_run, verbose):
	all_cores     = get_all_cpus()
	all_tx_cores  = get_pcie_dev_cpus(tx_pcie_dev)
	all_rx_cores  = get_pcie_dev_cpus(rx_pcie_dev)

	tx_cores      = select_cores(all_tx_cores, num_tx_cores + 1, [])
	rx_cores      = select_cores(all_tx_cores, num_rx_cores + 1, tx_cores)
	master_core   = select_cores(all_cores, 1, tx_cores + rx_cores)

	tx_rx_cores = [ tx_cores[0] ]
	tx_tx_cores = tx_cores[1:]

	rx_rx_cores = rx_cores[1:]
	rx_tx_cores = [ rx_cores[0] ]

	tx_port  = get_port_from_pcie_dev(tx_pcie_dev)
	rx_port  = get_port_from_pcie_dev(rx_pcie_dev)

	assert tx_port != rx_port

	print(f'[*] TX dev={tx_pcie_dev} port={tx_port} cores={tx_tx_cores}')
	print(f'[*] RX dev={rx_pcie_dev} port={rx_port} cores={rx_rx_cores}')
	print(f'[*] Master core={master_core}')
	print(f"[*] Replaying at {rate}% linerate")

	tx = {
		'dev':   tx_pcie_dev,
		'port':  tx_port,
		'cores': {
			'tx': tx_tx_cores,
			'rx': tx_rx_cores,
		},
	}

	rx = {
		'dev':   rx_pcie_dev,
		'port':  rx_port,
		'cores': {
			'tx': rx_tx_cores,
			'rx': rx_rx_cores,
		},
	}

	data = run_pktgen(pcap, rate, tx, rx, master_core, duration_sec, dry_run, verbose)

	results = []
	results.append(str(data['tx']['rate']))
	results.append(str(data['tx']['pkt_rate']))
	results.append(str(data['rx']['rate']))
	results.append(str(data['rx']['pkt_rate']))
	results.append(str(data['loss']))

	with open(RESULTS_FILENAME, 'w') as f:
		f.write('# tx (Gbps), tx (Mpps), rx (Gbps), rx (Mpps), loss (%)')
		f.write('\n')
		f.write(','.join(results))
		f.write('\n')

def range_limited_rate(arg):
	MIN_VAL = MIN_RATE
	MAX_VAL = MAX_RATE

	try:
		f = float(arg)
	except ValueError:    
		raise argparse.ArgumentTypeError("Must be a floating point number")
	if f <= MIN_VAL or f > MAX_VAL:
		raise argparse.ArgumentTypeError(f"Argument must be < {MAX_VAL} + and >= {MIN_VAL}")
	return f

def main():
	parser = argparse.ArgumentParser()
	
	parser.add_argument('tx', type=str, help='TX PCIe device')
	parser.add_argument('rx', type=str, help='RX PCIe device')
	parser.add_argument('pcap', type=str, help='pcap to replay')
	parser.add_argument('rate', type=range_limited_rate, help='replay rate (%% of total capacity)')

	parser.add_argument('--tx-cores',
		type=int, default=DEFAULT_TX_CORES, required=False, help='Number of TX cores')

	parser.add_argument('--rx-cores',
		type=int, default=DEFAULT_RX_CORES, required=False, help='Number of RX cores')
	
	parser.add_argument('--duration',
		type=int, default=DEFAULT_DURATION_SEC, required=False, help='Time duration (seconds)')

	parser.add_argument('--dry',
		default=False, required=False, action='store_true',
		help='Dry run (does not run pktgen, just prints out the configuration)')
	
	parser.add_argument('-v',
		default=False, required=False, action='store_true',
		help='Shows Pktgen output')

	args = parser.parse_args()

	pcap = os.path.abspath(args.pcap)
	assert os.path.exists(pcap)

	run(args.tx, args.rx, pcap, args.tx_cores, args.rx_cores, args.rate, args.duration, args.dry, args.v)

if __name__ == '__main__':
	main()
