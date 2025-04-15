from esi_api.connections import get_openstack_connection, get_esi_connection
from esi.lib import nodes
from flask import Flask, jsonify
from threading import Event
import json
import signal
import os
import sys
import traceback


app = Flask(__name__)

INTERRUPT_EVENT = Event()

cloud_name = os.environ.get('CLOUD_NAME') or "openstack"


@app.route('/api/v1/nodes/list', methods=['GET'])
def nodes_list():
    """
    Returns:
        JSON array of node, network and lease details in the format:
        [
            {
                'node': openstack.baremetal.v1.node.Node,
                'lease_info': [esi.lease.v1.lease.Lease],
                'network_info': [
                    {
                        'baremetal_port': openstack.baremetal.v1.port.Port,
                        'network_ports':[openstack.network.v2.port.Port] or [],
                        'network': openstack.network.v2.network.Network or None
                    },
                    ...
                ]
            },
            ...
        ]
    """
    try:
        conn = get_esi_connection(cloud=cloud_name)
        node_networks_res = nodes.network_list(conn)
        node_networks = {nn['node'].id: nn['network_info'] for nn in node_networks_res}
        nodes_all = conn.lease.nodes()
        items = []
        for node in nodes_all:
            # Get node leases
            leases = conn.lease.leases(resource_uuid=node.id)
            lease_list = [l for l in leases] if leases else []

            # Get node network configurations
            network_info_list = []
            node_network = node_networks.get(node.id)
            if node_network:
                for node_port in node_network:
                    if node_port["networks"]:
                        network = node_port['networks'].get('parent')
                    stripped_network_info = {
                        'baremetal_port': node_port["baremetal_port"],
                        'network_ports': node_port["network_ports"],
                        'network': network,
                    }
                    network_info_list.append(stripped_network_info)

            items.append({'node': node,
                'lease_info': lease_list,
                'network_info': network_info_list
                })
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/v1/baremetal-order/fulfill', methods=['POST'])
def baremetal_order_fulfill():
    response = {
        'status': 'CREATED'
        , 'code': 201
    }
    return jsonify(response)

@app.route('/api/v1/networks/list', methods=['GET'])
def networks_list():
    try:
        conn = get_openstack_connection(cloud=cloud_name)
        response = conn.network.networks()
        networks = [r.to_dict() for r in response]
        return jsonify(networks)
    except Exception as e:
        return jsonify({"error": str(e)})

def start():
    flask_port = os.environ.get('FLASK_PORT') or 8081
    flask_port = int(flask_port)

    app.run(port=flask_port, host='0.0.0.0')

if __name__ == "__main__":
    start()
