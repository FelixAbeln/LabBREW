import json
import sys
with open('/opt/labbrew/data/sources/brewcan.json') as f:
    config = json.load(f)
config['config']['gateway_control_enabled'] = False
config['config']['gateway_rx_control_enabled'] = False
config['config']['gateway_send_fw_dev_probes'] = False
with open('/opt/labbrew/data/sources/brewcan.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Config updated')
