
## How to run the application in an OpenShift AI workbench

```bash
git clone https://github.com/CCI-MOC/demo-esi-api.git ~/demo-esi-api
cd ~/demo-esi-api
pip install -r requirements.txt
python app.py
```

In a separate terminal, test the request: 

```bash
curl -X GET http://localhost:8081/api/v1/list/node
curl -X GET http://localhost:8081/api/v1/list/networks
curl -X POST http://localhost:8081/api/v1/order/bare-metal -d '{"network_id": "<some network>",
  "Nodes": [{"resource_class": "fc830", "number": 3}, 
         {"resource_class": "<some gpu class>", "number":2}]}'
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

### Pull down Kafka secrets from OpenShift Local for development

```bash
sudo install -d -o $USER -g $USER -m 771 /opt/kafka/truststore
sudo install -d -o $USER -g $USER -m 771 /opt/kafka/keystore
oc extract -n kafka secret/smartvillage-kafka --to=/opt/kafka/keystore/ --keys=user.crt --confirm
oc extract -n kafka secret/smartvillage-kafka --to=/opt/kafka/keystore/ --keys=user.key --confirm
oc extract -n kafka secret/default-cluster-ca-cert --to=/opt/kafka/truststore/ --keys=ca.crt --confirm
```

### Run the container for local development

```bash
podman run -v /opt/kafka:/opt/kafka nerc-images/demo-esi-api:computate-api
```

## How to connect to ESI API
To establish a connection, you'll need to: 
1. put the clouds.yaml file in `~/.config/openstack/clouds.yaml`. You can refer to the 
`example_clouds.yaml` for a sample clouds.yaml. 

2. set the environment variable `CLOUD_NAME`.
For the provided `example_clouds.yaml`, the CLOUD_NAME should be set to "openstack".
