
# How to develop the ESI API in an OpenShift AI Workbench

## Pull down Kafka secrets to your OpenShift AI Workbench

```bash
install -d -o $USER -g $USER -m 771 /opt/app-root/src/kafka/truststore/
install -d -o $USER -g $USER -m 771 /opt/app-root/src/kafka/keystore/
oc extract secret/esi --to=/opt/app-root/src/kafka/keystore/ --keys=user.crt --confirm
oc extract secret/esi --to=/opt/app-root/src/kafka/keystore/ --keys=user.key --confirm
oc extract secret/esi --to=/opt/app-root/src/kafka/keystore/ --keys=user.p12 --confirm
oc extract secret/kafka-cluster-ca-cert --to=/opt/app-root/src/kafka/truststore/ --keys=ca.crt --confirm
oc extract secret/kafka-cluster-ca-cert --to=/opt/app-root/src/kafka/truststore/ --keys=ca.p12 --confirm
```

## How to connect to ESI API
To establish a connection, you'll need to:
1. put the clouds.yaml file in `~/.config/openstack/clouds.yaml`. You can refer to the
`example_clouds.yaml` for a sample clouds.yaml.

2. set the environment variable `CLOUD_NAME`.
For the provided `example_clouds.yaml`, the CLOUD_NAME should be set to "openstack".

## How to run the application in an OpenShift AI workbench

```bash
git clone https://github.com/CCI-MOC/demo-esi-api.git ~/demo-esi-api
cd ~/demo-esi-api
pip install -r requirements.txt
python app.py
```

In a separate terminal, test the request:

```bash
curl -X GET http://localhost:8081/api/v1/nodes/list
curl -X GET http://localhost:8081/api/v1/networks/list
curl -X GET http://localhost:8081/api/v1/offers/list
curl -X POST http://localhost:8081/api/v1/baremetal-order/fulfill \
  -H "Content-Type: application/json" \
  -d '{"order_id": "123_xyz",
       "network_id": "provisioning",
       "nodes": [{"resource_class": "fc430", "number": 1}]
  }'
```

## How to run the application as a Podman container

### Install the prerequiste packages for buildah and podman

```bash
pkcon install -y buildah
pkcon install -y podman
```

### Build the container with podman

```bash
cd ~/.local/src/TLC
podman build -t nerc-images/demo-esi-api:computate-api .
```

### Push the container up to quay.io
```bash
podman login quay.io
podman push nerc-images/demo-esi-api:computate-api quay.io/nerc-images/demo-esi-api:computate-api
```

### Run the container for local development

```bash
podman run -v /opt/kafka:/opt/kafka nerc-images/demo-esi-api:computate-api
```
