import asyncio
import copy
from datetime import datetime, timezone, timedelta
from esi_api.connections import get_openstack_connection, get_esi_connection
from esi.lib import nodes

from consumer import FlaskKafka
from kafka import  KafkaProducer, errors
from kazoo.client import KazooClient
from kazoo.exceptions import NodeExistsError

from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from threading import Event, Thread
import json
import signal
import os
import sys
import traceback

from metalsmith import _provisioner
from metalsmith import instance_config


LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
CORS(app)

INTERRUPT_EVENT = Event()

cloud_name = os.environ.get('CLOUD_NAME') or "openstack"

kafka_brokers = os.environ.get('KAFKA_BROKERS') or "kafka-kafka-bootstrap:9093"
kafka_group_fulfill = os.environ.get('KAFKA_GROUP_FULFILL') or "esi-fulfill-group"
kafka_topic_fulfill_offer = os.environ.get('KAFKA_TOPIC_FULFILL_OFFER') or "esi-fulfill-offer-task"
kafka_topic_order_loop = os.environ.get('KAFKA_TOPIC_ORDER_LOOP') or "esi-fulfill-order-loop"
kafka_topic_order_status = os.environ.get('KAFKA_TOPIC_ORDER_STATUS') or "esi-fulfill-order-status"
kafka_security_protocol = os.environ.get('KAFKA_SECURITY_PROTOCOL') or "SSL"
# Run: oc extract -n ai-telemetry-cbca60 secret/kafka-cluster-ca-cert --to=/opt/app-root/src/kafka/truststore/ --keys=ca.crt --confirm
kafka_ssl_cafile = os.environ.get('KAFKA_SSL_CAFILE') or "/opt/app-root/src/kafka/truststore/ca.crt"
# Run: oc extract -n ai-telemetry-cbca60 secret/esi --to=/opt/app-root/src/kafka/keystore/ --keys=user.crt --confirm
kafka_ssl_certfile = os.environ.get('KAFKA_SSL_CERTFILE') or "/opt/app-root/src/kafka/keystore/user.crt"
# Run: oc extract -n ai-telemetry-cbca60 secret/esi --to=/opt/app-root/src/kafka/keystore/ --keys=user.key --confirm
kafka_ssl_keyfile = os.environ.get('KAFKA_SSL_KEYFILE') or "/opt/app-root/src/kafka/keystore/user.key"
kafka_max_poll_records = int(os.environ.get('KAFKA_MAX_POLL_RECORDS') or "1")
kafka_max_poll_interval_ms = int(os.environ.get('KAFKA_MAX_POLL_INTERVAL_MS') or "3000000")

zookeeper_host_name = os.environ.get('ZOOKEEPER_HOST_NAME') or "zookeeper"
zookeeper_port = int(os.environ.get('ZOOKEEPER_PORT') or "2181")

# Kafka setup
kafka_available = False
bus_run = None
producer = None

try:
    producer = KafkaProducer(
            bootstrap_servers=kafka_brokers
            , security_protocol=kafka_security_protocol
            , ssl_cafile=kafka_ssl_cafile
            , ssl_certfile=kafka_ssl_certfile
            , ssl_keyfile=kafka_ssl_keyfile
            )

    bus_run = FlaskKafka(INTERRUPT_EVENT
            , bootstrap_servers=",".join([kafka_brokers])
            , group_id=kafka_group_fulfill
            , security_protocol=kafka_security_protocol
            , ssl_cafile=kafka_ssl_cafile
            , ssl_certfile=kafka_ssl_certfile
            , ssl_keyfile=kafka_ssl_keyfile
    #             , max_poll_interval_ms=kafka_max_poll_interval_ms
            , max_poll_records=kafka_max_poll_records
            )
    kafka_available = True
except errors.NoBrokersAvailable:
    LOG.warning("Kafka broker unavailable. APP will start without Kafka.")
except Exception as e:
    LOG.warning(f"Kafka setup failed: {e}. APP will start without Kafka.")


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

            items.append({
                'node': node,
                'lease_info': lease_list,
                'network_info': "\n".join(network_info_list)
            })

        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)})

async def fulfill_order_loop(conn, order_data, zk):
    # Keep in the loop until all nodes requests fulfilled
    order_id = order_data['order_id']
    requested_nodes = copy.deepcopy(order_data['nodes'])
    try:
        while True:
            order_status = order_data['status']
            producer.send(kafka_topic_order_status, json.dumps(order_data).encode('utf-8'))
            LOG.info(f"Sent order {order_id} {order_status} to Kafka topic {kafka_topic_order_status}")
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
                    tasks.append(fulfill_offer_task(conn, offer, order_data))
                    item['number'] -= 1

            if not tasks:
                LOG.info('No offer is available yet. Retrying...')
                await asyncio.sleep(60)
                continue
            await asyncio.gather(*tasks)

            # Break the loop if all node requests fulfilled
            if all(item['number'] <= 0 for item in requested_nodes):
                if kafka_available:
                    order_data["status"] = "Completed"
                    producer.send(kafka_topic_order_status, json.dumps(order_data).encode('utf-8'))
                    zk.set(f"baremetal/fulfill_order/{order_id}/status", bytes("Completed", "utf-8"))
                    zk.stop()
                break

            # Retry if not all requests fulfilled yet
            LOG.info('Not all requests fulfilled yet. Retrying...')
            await asyncio.sleep(60)
    except Exception as e:
        LOG.error(e)
        if kafka_available:
            order_data["status"] = "error"
            producer.send(kafka_topic_order_status, json.dumps(order_data).encode('utf-8'))
            zk.set(f"baremetal/fulfill_order/{order_id}/status", bytes("Error", 'utf-8'))
            if zk:
                zk.stop()

async def fulfill_offer_task(conn, offer, order_data):
    """
    Claims an offer, waits for lease to become active,
    and attaches the network to the leased node
    or provision the node with metalsmith if ssh_keys and image are provided.
    """
    network_id = order_data.get('network_id')
    ssh_keys = order_data.get('ssh_keys')
    image = order_data.get('image')
    order_id = order_data.get('order_id')
    try:
        lease = conn.lease.claim_offer(offer.id)
        LOG.info(f"Claimed offer {offer.id}: lease {lease.get('uuid')}")
        if kafka_available:
            result = {"order_id": order_id, "offer_id": offer.id, "lease_id": lease.get('uuid')}
            producer.send(kafka_topic_fulfill_offer, json.dumps(result).encode('utf-8'))
            LOG.info(f"Sent the offer claim message to Kafka: {result}")
        while True:
            lease_status = conn.lease.get_lease(lease.get('uuid')).status
            LOG.info('Get lease status...')
            if lease_status == 'active':
                LOG.info(f'Lease {lease.get("uuid")} is active')
                break
            await asyncio.sleep(30)

        node_id = lease.get('resource_uuid')
        openstack_conn = get_openstack_connection(cloud=cloud_name)
        if ssh_keys and image:
            config = instance_config.GenericConfig(ssh_keys=ssh_keys)
            provisioner = _provisioner.Provisioner(session=openstack_conn.session)
            provisioner.provision_node(node_id, image, nics=[{"network": network_id}], config=config)
            LOG.info(f"Provisioning node {node_id} with image {image}")
        elif not ssh_keys and not image:
            # Adopt the node
            node_provsion_state = openstack_conn.baremetal.get_node(node_id).provision_state
            if node_provsion_state != 'manageable':
                openstack_conn.baremetal.set_node_provision_state(node=node_id, target="manage", wait=True)
            openstack_conn.baremetal.set_node_provision_state(node=node_id, target="adopt")
            nodes.network_attach(conn, node_id, {'network': network_id})
            openstack_conn.baremetal.set_node_power_state(node=node_id, target="power on")
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
        "order_id": "123_xyz",
        "network_id": "<network UUID or name>",
        "nodes": [
            {"resource_class": "fc430", "number": 2},
            {"resource_class": "gpu", "number": 1}
        ]
    }
    or like this if privisioning with metalsmith:
    {
        "order_id": "123_xyz",
        "network_id": "<network UUID or name>",
        "nodes": [
            {"resource_class": "fc430", "number": 2},
            {"resource_class": "gpu", "number": 1}
        ],
        "ssh_keys": [<ssh_key_string>,],
        "image": <image name or id>
    }
    """
    try:
        order_data = request.get_json()
        if not order_data:
            return jsonify({'error': 'Missing order data'}), 400

        order_id = order_data.get('order_id')
        network_id = order_data.get('network_id')
        requested_nodes = order_data.get('nodes')
        ssh_keys = order_data.get('ssh_keys')
        image = order_data.get('image')
        if not order_id or not network_id or not requested_nodes:
            return jsonify({'error': 'Missing order_id, network_id or nodes'}), 400
        if (ssh_keys and not image) or (image and not ssh_keys):
            return jsonify({'error': 'Must provide both ssh_keys and image to use metalsmith provisioning.'}), 400

        # Verify if the network exists
        conn = get_openstack_connection(cloud=cloud_name)
        network_res = conn.network.find_network(network_id)
        if not network_res:
            return jsonify({'error': f'Network "{network_id}" not found'}), 404

        # Send to Kafka
        if kafka_available:
            order_data["status"] = "Running"
            producer.send(kafka_topic_order_loop, json.dumps(order_data).encode('utf-8'))
            LOG.info(f"Sent order {order_id} to Kafka topic {kafka_topic_order_loop}")
        else:
            LOG.warning("Kafka unavailable. Running order fulfillment without Kafka.")
            # Start fulfillment in background
            t = Thread(target=run_fulfillment_background, args=(order_data,))
            t.start()
        return jsonify({
            'status': 'CREATED',
            'code': 201,
        })
    except Exception as e:
        LOG.error(f'error: {str(e)}')
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

def run_fulfillment_background(order_data, zk=None):
    conn = get_esi_connection(cloud=cloud_name)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fulfill_order_loop(conn, order_data, zk))
    loop.close()

if kafka_available:
    @bus_run.handle(kafka_topic_order_loop)
    def on_fulfill_order(msg):
        try:
            bus_run.consumer.commit()
            LOG.info("Received fulfillment message from topic %s: %s", kafka_topic_order_loop, msg)

            order_data = json.loads(msg.value)
            order_id = order_data['order_id']

            if order_data.get('status') == 'Running':
                # Start zookeeper
                zk = KazooClient(hosts=f'{zookeeper_host_name}:{zookeeper_port}')
                zk.start()
                zk_path = f"baremetal/fulfill_order/{order_id}/status"
                try:
                    zk.create(zk_path, b"Running", makepath=True)
                except NodeExistsError:
                    zk.set(zk_path, b"Running")

                # Run fulfillment async
                run_fulfillment_background(order_data, zk)

        except Exception as e:
            LOG.error(f"Failed to process Kafka message: {e}")

@app.route('/api/v1/offers/list', methods=['GET'])
def offers_list():
    """
    Lists available node offer counts grouped by baremetal resource_class.

    Returns:
        JSON array of resource classes and node counts:
        [
            {
                'resource_class': <name of resource class>,
                'count': <count of available nodes>
            },
            ...
        ]
    """
    try:
        conn = get_esi_connection(cloud=cloud_name)
        now = datetime.now(timezone.utc)
        offers = list(conn.lease.offers(available_start_time=now,
                                        available_end_time=now + timedelta(days=7)))

        resource_class_count = {}
        for offer in offers:
            rc = offer.resource_class
            resource_class_count[rc] = resource_class_count.get(rc, 0) + 1

        resource_class_list = []
        for key in resource_class_count:
            resource_class_list.append(
                {
                    "resource_class": key,
                    "count": resource_class_count[key]
                }
            )
        return jsonify(resource_class_list)
    except Exception as e:
        return jsonify({'error': str(e)})

def start():
    flask_port = os.environ.get('FLASK_PORT') or 8081
    flask_port = int(flask_port)
    if kafka_available:
        bus_run.run()
    app.run(port=flask_port, host='0.0.0.0')


if __name__ == "__main__":
    start()
