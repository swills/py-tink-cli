#!/usr/bin/env python

import logging
import json
import grpc
import urllib.request
import argparse
import os
import yaml
from google.protobuf.json_format import Parse
from datetime import datetime

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


def get_mac_for_hostname(server, port, creds, hostname):
    res = get_all_hardware(server, port, creds)
    mac = ""
    for re in res:
        if re['hostname'] == hostname:
            mac = re['mac']
    return mac


def push_workflow(server, port, creds, client_name, template_name):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        client_mac = get_mac_for_hostname(server, port, creds, client_name)
        if client_mac == "":
            raise Exception("Invalid hostname")
        template_id = get_template_by_name(server, port, creds, template_name)
        if template_id is None:
            raise Exception("Invalid template name")
        hardware = {'device_1': client_mac}
        hardware_json = json.dumps(hardware)
        response = stub.CreateWorkflow(workflow_pb2.CreateRequest(
            template=template_id, hardware=hardware_json))
        result = [response.id]
    return result


def push_hardware(server, port, creds, hardware_file):
    with open(hardware_file, "r") as my_file:
        data = my_file.read()

    hardware = json.loads(data)
    hardware_wrapper = hardware_pb2.Hardware()
    nw = Parse(json.dumps(hardware['network']), hardware_wrapper.network)
    hardware_wrapper.id = hardware['id']
    hardware_wrapper.metadata = json.dumps(hardware['metadata'], separators=(',', ':'))
    hardware_wrapper.network.CopyFrom(nw)

    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        req = hardware_pb2.PushRequest(data=hardware_wrapper)
        stub.Push(req)
    return [hardware['id']]


def push_template(server, port, creds, template_file):
    with open(template_file, "r") as my_file:
        data = my_file.read()

    template_data = yaml.load(data, Loader=yaml.Loader)
    template_name = template_data['name']
    template_id = get_template_by_name(server, port, creds, template_name)
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        if template_id is None:
            req = template_pb2.WorkflowTemplate(name=template_name, data=data)
            stub.CreateTemplate(req)
            template_id = get_template_by_name(server, port, creds, template_name)
        else:
            req = template_pb2.WorkflowTemplate(name=template_name, data=data,
                                                id=template_id)
            stub.UpdateTemplate(req)
    return [template_id]


def delete_hardware(server, port, creds, hardware_id):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        stub.Delete(hardware_pb2.DeleteRequest(id=hardware_id))
    return True


def delete_template(server, port, creds, template_id):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        stub.DeleteTemplate(template_pb2.GetRequest(id=template_id))
    return True


def delete_workflow(server, port, creds, workflow_id):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        stub.DeleteWorkflow(workflow_pb2.GetRequest(id=workflow_id))
    return True


def get_workflow_events(server, port, creds, workflow_id):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        res = stub.ShowWorkflowEvents(workflow_pb2.GetRequest(id=workflow_id))
        result = {}
        actions = []
        result['worker_id'] = None
        result['task_name'] = None
        result['seconds'] = 0
        for r in res:
            if result['worker_id'] is None:
                result['worker_id'] = r.worker_id
            if result['task_name'] is None:
                result['task_name'] = r.task_name
            action_result = {
                'action_name': r.action_name,
                'action_status': state_map(r.action_status),
                'message': r.message,
                'timestamp': datetime.fromtimestamp(r.created_at.seconds).strftime(
                    "%A, %B %d, %Y %I:%M:%S")
            }
            if action_result['action_status'] != "Running":
                action_result['seconds'] = r.seconds
                result['seconds'] += r.seconds
            actions.append(action_result)

        result['actions'] = actions
    return result


def get_all_workflows(server, port, creds):
    with grpc.secure_channel(server + ":" + port, creds) as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        response = stub.ListWorkflows(workflow_pb2.GetRequest())
        result = []
        for r in response:
            re = {
                'id': r.id,
            }
            template = get_template_by_id(server, port, creds, template_id=r.template)
            re['template'] = template
            re['state'] = state_map(r.state)
            hardware_json = json.loads(r.hardware)
            devs = []
            for dev in hardware_json.keys():
                mac = hardware_json[dev]
                hostname = get_hostname_for_mac(server, port, creds, mac)
                dev_data = {'mac': mac,
                            'hostname': hostname}
                devs.append(devs)
            re['devices'] = dev_data

            result.append(re)
    return result


def state_map(r):
    if r == workflow_pb2.STATE_PENDING:
        return "Pending"
    elif r == workflow_pb2.STATE_RUNNING:
        return "Running"
    elif r == workflow_pb2.STATE_FAILED:
        return "Failed"
    elif r == workflow_pb2.STATE_TIMEOUT:
        return "Timeout"
    elif r == workflow_pb2.STATE_SUCCESS:
        return "Success"
    else:
        return "Unknown"


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
            result = re
    return result


def get_template_by_name(server, port, creds, template_name):
    res = get_all_templates(server, port, creds)
    result = None
    for re in res:
        if re['name'] == template_name:
            result = re['id']
    return result


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
    parser.add_argument("--tink_host",
                        dest="tink_host",
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
                        default=None,
                        help="template name to operate on")
    parser.add_argument("--host_name",
                        dest="host_name",
                        default=None,
                        help="host name to operate on")
    parser.add_argument("--id",
                        dest="id",
                        default=None,
                        help="id to operate on")
    parser.add_argument("--file",
                        dest="file",
                        default=None,
                        help="file to use for hardware/template")
    parser.add_argument("action",
                        help="action to perform")
    parser.add_argument("object",
                        help="what to operate on")
    args = parser.parse_args()

    if args.tink_host is None:
        print("TINK_HOST environment variable must be set or --host must be specified")
        return

    cert_url = 'http://' + args.tink_host + ':' + args.http_port + '/cert'
    with urllib.request.urlopen(cert_url) as response:
        trusted_certs = response.read()

    creds = grpc.ssl_channel_credentials(root_certificates=trusted_certs)

    if args.action == "get":
        if args.object == "workflows":
            result = get_all_workflows(args.tink_host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "workflow":
            if args.id is not None:
                result = get_workflow_events(args.tink_host, args.rpc_port, creds,
                                             workflow_id=args.id)
                print(json.dumps(result, indent=2))
        elif args.object == "hardware":
            result = get_all_hardware(args.tink_host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "templates":
            result = get_all_templates(args.tink_host, args.rpc_port, creds)
            print(json.dumps(result, indent=2))
        elif args.object == "template":
            if args.template_name is not None:
                result = get_all_templates(args.tink_host, args.rpc_port, creds)
                for template in result:
                    if template['name'] == args.template_name:
                        template_id = template['id']
                        template_result = get_template_steps(args.tink_host,
                                                             args.rpc_port, creds,
                                                             template_id=template_id)
                        print(template_result)
    elif args.action == "push":
        if args.object == "workflow":
            if args.host_name is not None and args.template_name is not None:
                result = push_workflow(args.tink_host, args.rpc_port, creds,
                                       args.host_name, args.template_name)
                print(json.dumps(result, indent=2))
        elif args.object == "hardware":
            if args.file is not None:
                result = push_hardware(args.tink_host, args.rpc_port, creds,
                                       args.file)
                print(json.dumps(result))
        elif args.object == "template":
            if args.file is not None:
                result = push_template(args.tink_host, args.rpc_port, creds,
                                       args.file)
                print(json.dumps(result))
    elif args.action == "delete":
        if args.object == "hardware":
            if args.id is not None:
                result = delete_hardware(args.tink_host, args.rpc_port, creds,
                                         args.id)
                if result:
                    print(json.dumps([args.id]))
        elif args.object == "template":
            if args.id is not None:
                result = delete_template(args.tink_host, args.rpc_port, creds,
                                         args.id)
                if result:
                    print(json.dumps([args.id]))
        elif args.object == "workflow":
            if args.id is not None:
                result = delete_workflow(args.tink_host, args.rpc_port, creds,
                                         args.id)
                if result:
                    print(json.dumps([args.id]))


if __name__ == '__main__':
    logging.basicConfig()
    run()
