#!/usr/bin/env python3

import os
import requests
import json
import argparse
import time

SCRIPT_DIR   = os.path.dirname(os.path.realpath(__file__))

DEFAULT_HOST = '146.193.41.114'
DEFAULT_PORT = 8123

def get_url(host, port):
	return f'http://{host}:{port}/api/v1'

def redirect(api_url, in_port, out_port):
	url = f'{api_url}/redirect/{in_port}'
	body = f'{out_port}'
	res = requests.put(url, body)
	assert res.status_code == 200

def clear_counters(api_url, port):
	url = f'{api_url}/counters/{port}'
	res = requests.delete(url)
	assert res.status_code == 200

def get_counters(api_url, port):
	url = f'{api_url}/counters/{port}'
	res = requests.get(url)
	assert res.status_code == 200

	counters = json.loads(res.text)

	in_pkts   = counters['in']['pkts']
	in_bytes  = counters['in']['bytes']
	out_pkts  = counters['in']['pkts']
	out_bytes = counters['in']['bytes']

	# Tofino adds 4B metadata to its packets
	out_bytes -= out_pkts * 4
	out_bytes -= out_pkts * 4

	return in_pkts, in_bytes, out_pkts, out_bytes

def main():
	parser = argparse.ArgumentParser()

	parser.add_argument('--host', type=str, default=DEFAULT_HOST, required=False,
		help='IP of host running port redirector app')
	parser.add_argument('--port', type=int, default=DEFAULT_PORT, required=False,
		help='Port of host running port redirector app')

	subparsers = parser.add_subparsers(help='Subparser', dest='command')

	redirect_parser = subparsers.add_parser('redirect', help='Redirect traffic from one port to another')
	redirect_parser.add_argument('inbound', type=int, help='Inbound port')
	redirect_parser.add_argument('outbound', type=int, help='Outbound port')

	clear_parser = subparsers.add_parser('clear', help='Clear counters')
	clear_parser.add_argument('switch_port', type=int, help='Port')

	get_parser = subparsers.add_parser('get', help='Get counters')
	get_parser.add_argument('switch_port', type=int, help='Port')

	args = parser.parse_args()

	api_url = get_url(args.host, args.port)

	if args.command == 'redirect':
		inbound  = args.inbound
		outbound = args.outbound
		redirect(api_url, inbound, outbound)
	elif args.command == 'clear':
		port = args.switch_port
		clear_counters(api_url, port)
	elif args.command == 'get':
		port = args.switch_port
		in_pkts, in_bytes, out_pkts, out_bytes = get_counters(api_url, port)

		print(f'rx: {in_pkts} pkts {in_bytes} B ')
		print(f'tx: {out_pkts} pkts {out_bytes} B ')

	exit(0)

if __name__ == '__main__':
	main()
