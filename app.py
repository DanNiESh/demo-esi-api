from esi_api.connections import get_openstack_connection, get_esi_connection
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


@app.route('/api/v1/list/node', methods=['GET'])
def list_node():
    items = [
        {'id': 1, 'name': 'Item 1'},
        {'id': 2, 'name': 'Item 2'},
        {'id': 3, 'name': 'Item 3'}
    ]
    return jsonify(items)

@app.route('/api/v1/order/bare-metal', methods=['POST'])
def bare_metal_fulfillment_order_request():
    response = {
        'status': 'CREATED'
        , 'code': 201
    }
    return jsonify(response)

@app.route('/api/v1/list/networks', methods=['GET'])
def list_networks():
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
