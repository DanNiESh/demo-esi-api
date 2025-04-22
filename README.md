
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
curl -X POST http://localhost:8081/api/v1/baremetal-order/fulfill \
  -H "Content-Type: application/json" \
  -d '{"network_id": "provisioning",
       "nodes": [{"resource_class": "fc830", "number": 3},
                 {"resource_class": "gpu", "number": 2}]
  }'
  curl -X POST http://localhost:8081/api/v1/nodes/deploy \
  -H "Content-Type: application/json" \
  -d '{"network": "network-uitest",
       "node": "MOC-R4PAC24U31-S3D",
       "image": "centos-image",
       "ssh_keys": ["ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCjd8ogDDNG69B+vaN0n58iZr7cN50d0tfy/zauK5PDIrLZABAemigVg8RlzDBjltwAp9JE3tPy6hM/iDkvawwVA9KMKHlTgIJaCxl+LUZlp5YlqA0RKIUunKYndEvcrlB19u+WMCbq2GKWDNGFZJ36taskKJRL7gFZ6bi6xYvjRbkNQLqHlGxk8Ukw7Ss4nxA4roXTCez7LpJssUgedegEwRnXVyqL7/bAS74c//ZGTe+W8pSGFeEN9Jnpsj4ysM+ncI/CbMI4t+GbHnvz00q+44FPpZHs++7Ant7kIPo386rzZCyf0f6taU+eCjJBmE2zG95Pi2/BqB6WNyIJT/klMuCAen7eg8TJdQZBHilhSo9Du+XeOTS8IUUnYbEp530Zu2kdlEglxqDrqpYl4ju0r+N9Sp2XdRzjne//PDvZQIUMV9syrq9NDUb7YUUYVxcoKI66DHMX2Qv3egoeIBH6WNQssORerXmfV7tHyOB3BK5caVk4o+jrbVAkHmXrgrM= sdanni@sdanni-thinkpadx1carbongen9.boston.csb"]
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
