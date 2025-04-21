import asyncio
from datetime import datetime, timezone, timedelta
from esi_api.connections import get_openstack_connection, get_esi_connection
from esi.lib import nodes
from flask import Flask, jsonify, request
import logging
from threading import Event, Thread
import json
import signal
import os
import sys
import traceback

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
                    mac_address = node_port["baremetal_port"]["address"]
                    network_string = mac_address
                    if node_port["networks"]:
                        network = node_port['networks'].get('parent')
                        if network:
                            network_string = "%s [%s (%s)]" % (network_string, network.get("name"), network.get("provider_segmentation_id"))
                    network_info_list.append(network_string)

            items.append({'node': node,
                'lease_info': lease_list,
                'network_info': "\n".join(network_info_list)
                })
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)})

def run_fulfillment_background(network_id, requested_nodes):
    conn = get_esi_connection(cloud=cloud_name)
    # Run async fulfillment tasks inside this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fulfill_order_loop(conn, network_id, requested_nodes))
    loop.close()

async def fulfill_order_loop(conn, network_id, requested_nodes):
    # Keep in the loop until all nodes requests fulfilled
    while True:
        tasks = []
        now = datetime.now(timezone.utc)
        offers_all = list(conn.lease.offers(available_start_time=now,
                                            available_end_time=now + timedelta(days=7)))
        for item in requested_nodes:
            resource_class = item['resource_class']
            number = item['number']
            if number <= 0:
                continue
            # Filter the offer with resource_class
            offers_filtered = [o for o in offers_all
                               if o.resource_class == resource_class]
            # Grab the first X offers to claim
            offers_to_claim = offers_filtered[:number]

            for offer in offers_to_claim:
                tasks.append(fulfill_offer_task(conn, offer, network_id))
                item['number'] -= 1

        if not tasks:
            LOG.info('No offer is available yet. Retrying...')
            await asyncio.sleep(60)
            continue
        await asyncio.gather(*tasks)
        # Break the loop if all node requests fulfilled
        if all(item['number'] <= 0 for item in requested_nodes):
            break
        # Retry if not all requests fulfilled yet
        LOG.info('Not all requests fulfilled yet. Retrying...')
        await asyncio.sleep(60)

async def fulfill_offer_task(conn, offer, network_id):
    """
    Claims an offer, waits for lease to become active,
    and attaches the network to the leased node.
    """
    try:
        lease = conn.lease.claim_offer(offer.id)
        LOG.info(f"Claimed offer {offer.id}: lease {lease.get('uuid')}")
        while True:
            lease_status = conn.lease.get_lease(lease.get('uuid')).status
            LOG.info('Get lease status...')
            if lease_status == 'active':
                LOG.info(f'Lease {lease.get("uuid")} is active')
                break
            await asyncio.sleep(30)
        nodes.network_attach(conn, lease.get('resource_uuid'), {'network': network_id})
        LOG.info(f"Network {network_id} attached to node {lease.get('resource_uuid')}")
    except Exception as e:
        LOG.error(f"Error fulfilling offer {offer.id}: {e}")
        raise RuntimeError(f'Error fulfilling offer {offer.id}: {e}')

@app.route('/api/v1/baremetal-order/fulfill', methods=['POST'])
def baremetal_order_fulfill():
    """
    Fulfills a baremetal node order.
    A bare-metal order should be like this:
    {
        "network_id": "<network UUID or name>",
        "nodes": [
            {"resource_class": "fc430", "number": 2},
            {"resource_class": "gpu", "number": 1}
        ]
    }
    """
    try:
        order_data = request.get_json()
        if not order_data:
            return jsonify({'error': 'Missing order data'}), 400

        network_id = order_data.get('network_id')
        requested_nodes = order_data.get('nodes')
        if not network_id or not requested_nodes:
            return jsonify({'error': 'Missing network_id or nodes'}), 400

        # Verify if the network exists
        conn = get_openstack_connection(cloud=cloud_name)
        network_res = conn.network.find_network(network_id)
        if not network_res:
            return jsonify({'error': f'Network "{network_id}" not found'}), 404

        # Start fulfillment in background
        t = Thread(target=run_fulfillment_background, args=(network_id, requested_nodes))
        t.start()

        return jsonify({
            'status': 'CREATED',
            'code': 201,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
