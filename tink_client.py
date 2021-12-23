#!/usr/bin/env python

import logging
import json
import grpc
import urllib.request
import argparse
import os

import hardware_pb2_grpc
import hardware_pb2
import workflow_pb2_grpc
import workflow_pb2
import template_pb2_grpc
import template_pb2


def get_hostname_for_mac(server, port, creds, mac):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        response = stub.ByMAC(hardware_pb2.GetRequest(mac=mac.lower()))
    return response.network.interfaces[0].dhcp.hostname


def get_all_workflows(server, port, creds):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        response = stub.ListWorkflows(workflow_pb2.GetRequest())
        result = []
        for r in response:
            # print(r)
            re = {
                'id': r.id,
            }
            template = get_template_by_id(server, port, creds, template_id=r.template)
            re['template'] = template
            if r.state == workflow_pb2.STATE_PENDING:
                re['state'] = "Pending"
            elif r.state == workflow_pb2.STATE_RUNNING:
                re['state'] = "Running"
            elif r.state == workflow_pb2.STATE_FAILED:
                re['state'] = "Failed"
            elif r.state == workflow_pb2.STATE_TIMEOUT:
                re['state'] = "Timeout"
            elif r.state == workflow_pb2.STATE_SUCCESS:
                re['state'] = "Success"
            else:
                re['state'] = "Unknown"
            hardware_json = json.loads(r.hardware)
            devs = []
            for dev in hardware_json.keys():
                mac = hardware_json[dev]
                hostname = get_hostname_for_mac(server, port, creds, mac)
                devdata = {'mac': mac,
                           'hostname': hostname}
                devs.append(devs)
            re['devices'] = devdata

            result.append(re)
    return result


def get_all_hardware(server, port, creds):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        response = stub.All(hardware_pb2.GetRequest())
        result = []

        for r in response:
            re = {
                'id': r.id,
                'hostname': r.network.interfaces[0].dhcp.hostname,
                'ip': r.network.interfaces[0].dhcp.ip.address,
                'mac': r.network.interfaces[0].dhcp.mac,
            }
            result.append(re)
    return result


def get_all_templates(server, port, creds):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        response = stub.ListTemplates(template_pb2.GetRequest())
        result = []
        for r in response:
            re = {
                'id': r.id,
                'name': r.name,
            }
            result.append(re)
    return result


def get_template_by_id(server, port, creds, template_id):
    res = get_all_templates(server, port, creds)
    result = {}
    for re in res:
        if re['id'] == template_id:
            return re


def get_template_steps(server, port, creds, template_id):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        response = stub.GetTemplate(template_pb2.GetRequest(id=template_id))
    return response.data


def run():

    parser = argparse.ArgumentParser(description='do tink stuff')
    parser.add_argument('-d', '--debug',
                        action='store_true',
                        default=False,
                        dest='debug_logs',
                        help='debug Output'
                        )
    parser.add_argument("--host",
                        dest="host",
                        default=os.environ.get('TINK_HOST'),
                        help="tink host. required.")
    parser.add_argument("--rpc_port",
                        dest="rpc_port",
                        default="42113",
                        help="rpc port. Default is '42113'.")
    parser.add_argument("--http_port",
                        dest="http_port",
                        default="42114",
                        help="http port. Default is '42114'.")
    parser.add_argument("--template_name",
                        dest="template_name",
                        help="template name to operate on")
    parser.add_argument("action",
                        help="action to perform")
    parser.add_argument("object",
                        help="what to operate on")
    args = parser.parse_args()

    cert_url = 'http://' + args.host + ':' + args.http_port + '/cert'
    with urllib.request.urlopen(cert_url) as response:
        trusted_certs = response.read()

    creds = grpc.ssl_channel_credentials(root_certificates=trusted_certs)

    if args.action == "get":
        if args.object == "workflows":
            result = get_all_workflows(args.host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "hardware":
            result = get_all_hardware(args.host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "templates":
            result = get_all_templates(args.host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "template":
            if args.template_name is not None:
                result = get_all_templates(args.host, args.rpc_port, creds)
                for template in result:
                    if template['name'] == args.template_name:
                        id = template['id']
                        template_result = get_template_steps(args.host, args.rpc_port,
                                                         creds, template_id=id)
                        print(template_result)


if __name__ == '__main__':
    logging.basicConfig()
    run()
