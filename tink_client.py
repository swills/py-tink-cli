#!/usr/bin/env python
import argparse
import json
import logging
import os
import socket
import urllib.request
from datetime import datetime

import grpc
import yaml
from google.protobuf.json_format import Parse
from pyghmi.ipmi import command

import hardware_pb2
import hardware_pb2_grpc
import template_pb2
import template_pb2_grpc
import workflow_pb2
import workflow_pb2_grpc

ipmi_userid = os.getenv('IPMI_USER')
ipmi_password = os.getenv('IPMI_PASS')

global all_hardware_info
global all_template_info
all_hardware_info = None
all_template_info = None


def create_parser():
    parser = argparse.ArgumentParser(description='do tink stuff')
    parser.add_argument('-d', '--debug',
                        action='store_true',
                        default=False,
                        dest='debug_logs',
                        help='debug Output'
                        )
    parser.add_argument("--tink_host",
                        dest="tink_host",
                        default=os.getenv('TINK_HOST'),
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
    parser.add_argument("--host",
                        dest="host",
                        default=None,
                        help="host name to operate on")
    parser.add_argument("--id",
                        dest="id",
                        default=None,
                        help="id to operate on")
    parser.add_argument("--reboot",
                        dest="reboot",
                        action='store_true',
                        default=False,
                        help="reboot host")
    parser.add_argument("--file",
                        dest="file",
                        default=None,
                        help="file to use for hardware/template")
    parser.add_argument("--format",
                        dest="format",
                        default="json",
                        help="output format (json, yaml)")
    parser.add_argument("--tls",
                        dest="tls",
                        default=True,
                        help="connect using TLS")
    parser.add_argument("action",
                        help="action to perform")
    parser.add_argument("object",
                        help="what to operate on")
    return parser


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


def connect():
    raise NotImplementedError("connect should have been overridden in run()")


def get_host_for_mac2(mac):
    resp = None
    try:
        with connect() as channel:
            stub = hardware_pb2_grpc.HardwareServiceStub(channel)
            response = stub.ByMAC(hardware_pb2.GetRequest(mac=mac.lower()))
            resp = response.network.interfaces[0].dhcp.hostname
    except grpc._channel._InactiveRpcError:
        pass
    return resp


def get_host_for_mac(mac):
    res = get_all_hardware()
    host = ""
    for re in res:
        if re['mac'] == mac:
            host = re['host']
    return host


def get_mac_for_host(host):
    res = get_all_hardware()
    mac = ""
    for re in res:
        if re['host'] == host:
            mac = re['mac']
    return mac


def get_all_hardware():
    global all_hardware_info
    if all_hardware_info is None:
        with connect() as channel:
            stub = hardware_pb2_grpc.HardwareServiceStub(channel)
            response = stub.All(hardware_pb2.GetRequest())
            result = []

            for r in response:
                re = {
                    'id': r.id,
                    'host': r.network.interfaces[0].dhcp.hostname,
                    'ip': r.network.interfaces[0].dhcp.ip.address,
                    'mac': r.network.interfaces[0].dhcp.mac,
                }
                result.append(re)
        all_hardware_info = result
    return all_hardware_info


def get_hardware(args):
    if args.id is not None:
        result = get_hardware_id(args.id)
    elif args.host is not None:
        result = get_hardware_name(args.host)
    else:
        result = get_all_hardware()
    return result


def get_hardware_name(hardware_name):
    res = get_all_hardware()
    result = None
    for re in res:
        if re['host'] == hardware_name:
            result = get_hardware_id(re['id'])
    return result


def get_hardware_id(hardware_id):
    with connect() as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        response = stub.ByID(hardware_pb2.GetRequest(id=hardware_id))
        result = {
            'id': response.id,
            'host': response.network.interfaces[0].dhcp.hostname,
            'ip': response.network.interfaces[0].dhcp.ip.address,
            'mac': response.network.interfaces[0].dhcp.mac,
        }
    return result


def get_all_templates():
    with connect() as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        response = stub.ListTemplates(template_pb2.GetRequest())
        result = []
        for r in response:
            re = {
                'name': r.name,
                'id': r.id,
            }
            result.append(re)
    return result


def get_template_by_id(template_id):
    global all_template_info
    if all_template_info is None:
        all_template_info = get_all_templates()
    result = {}
    for re in all_template_info:
        if re['id'] == template_id:
            result = re
    return result


def get_template_by_name(template_name):
    res = get_all_templates()
    result = None
    for re in res:
        if re['name'] == template_name:
            result = re['id']
    return result


def get_template_steps(template_id):
    with connect() as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        response = stub.GetTemplate(template_pb2.GetRequest(id=template_id))
    return response.data


def get_template_steps_by_name(args, raw_result):
    temp_result = get_all_templates()
    for template in temp_result:
        if template['name'] == args.template_name:
            template_id = template['id']
            raw_result = get_template_steps(template_id)
    return raw_result


def get_all_workflows():
    with connect() as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        response = stub.ListWorkflows(workflow_pb2.GetRequest())
        result = []
        for r in response:
            re = {
                'id': r.id,
            }
            template = get_template_by_id(r.template)
            re['template'] = template
            re['state'] = state_map(r.state)
            hardware_json = json.loads(r.hardware)
            devs = []
            for dev in hardware_json.keys():
                mac = hardware_json[dev]
                host = get_host_for_mac(mac)
                dev_data = {
                    'host': host,
                    'mac': mac,
                }
                devs.append(dev_data)
            re['devices'] = devs

            result.append(re)
    return result


def get_workflow_events(workflow_id):
    with connect() as channel:
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


def get_workflow_by_workflow_id(workflow_id):
    with connect() as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        req = workflow_pb2.WorkflowContextRequest(workflow_id=workflow_id)
        response = stub.GetWorkflowContexts(req)
        return response


def get_workflow_by_hardware_id(hardware_id):
    with connect() as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        req = workflow_pb2.WorkflowContextRequest(worker_id=hardware_id)
        response = stub.GetWorkflowContextList(req)
        res = []
        for context in response.workflow_contexts:
            r = {
                'workflow_id': context.workflow_id,
                'current_worker': context.current_worker,
                'current_task': context.current_task,
                'current_action': context.current_action,
                'current_action_index': context.current_action_index,
                'current_action_stat': state_map(context.current_action_state),
                'total_number_of_actions': context.total_number_of_actions,
            }
            res.append(r)
    return res


def get_workflow_by_host(host):
    hardware_info = get_hardware_name(host)
    result = get_workflow_by_hardware_id(hardware_info['id'])
    return result


def get_workflows_by_host(host):
    res = get_all_workflows()
    result = []
    for re in res:
        for device in re['devices']:
            if device['host'] == host:
                result.append(re)
    return result


def push_hardware(hardware_file):
    with open(hardware_file) as my_file:
        data = my_file.read()

    hardware = json.loads(data)
    hardware_id = hardware['id']
    hardware_hostname = hardware['network']['interfaces'][0]['dhcp']['hostname']
    hardware_ip = hardware['network']['interfaces'][0]['dhcp']['ip']['address']
    hardware_mac = hardware['network']['interfaces'][0]['dhcp']['mac']
    if len(hardware['network']['interfaces']) != 1:
        raise ValueError("Must specify exactly one IP per host")
    hardware_info = get_all_hardware()
    for existing in hardware_info:
        if existing['host'].lower == hardware_hostname.lower():
            raise ValueError("Duplicate hostname")
        if existing['ip'] == hardware_ip:
            raise ValueError("Duplicate IP")
        if existing['mac'].lower() == hardware_mac.lower():
            raise ValueError("Duplicate MAC address")
        if existing['id'] == hardware_id:
            raise ValueError("Duplicate hardware ID")
    hardware_wrapper = hardware_pb2.Hardware()
    nw = Parse(json.dumps(hardware['network']), hardware_wrapper.network)
    hardware_wrapper.id = hardware['id']
    for ele in hardware_wrapper.id:
        if ele.isupper():
            raise ValueError('Uppercase in Id')
    for ele in hardware_mac:
        if ele.isupper():
            raise ValueError('Uppercase in MAC')
    hardware_wrapper.metadata = json.dumps(hardware['metadata'], separators=(',', ':'))
    hardware_wrapper.network.CopyFrom(nw)

    with connect() as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        req = hardware_pb2.PushRequest(data=hardware_wrapper)
        stub.Push(req)
    return [hardware['id']]


def push_template(template_file):
    with open(template_file) as my_file:
        data = my_file.read()

    template_data = yaml.load(data, Loader=yaml.Loader)
    template_name = template_data['name']
    existing_template = get_template_by_name(template_name)
    if existing_template is not None:
        delete_template(existing_template)
    template_id = get_template_by_name(template_name)
    with connect() as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        if template_id is None:
            req = template_pb2.WorkflowTemplate(name=template_name, data=data)
            stub.CreateTemplate(req)
            template_id = get_template_by_name(template_name)
        else:
            req = template_pb2.WorkflowTemplate(name=template_name, data=data,
                                                id=template_id)
            stub.UpdateTemplate(req)
    return [template_id]


def push_workflow(client_name, template_name):
    with connect() as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        client_mac = get_mac_for_host(client_name)
        if client_mac == "":
            raise Exception("Invalid host")
        template_id = get_template_by_name(template_name)
        if template_id is None:
            raise Exception("Invalid template name")
        hardware = {'device_1': client_mac}
        hardware_json = json.dumps(hardware)
        existing_workflows = get_workflows_by_host(client_name)
        for workflow in existing_workflows:
            if workflow['devices'][0]['host'].lower() == client_name.lower():
                if workflow['state'] == "Running":
                    raise ValueError("Running workflow exists for host")
                if workflow['state'] == "Pending":
                    raise ValueError("Pending workflow exists for host")
        response = stub.CreateWorkflow(workflow_pb2.CreateRequest(
            template=template_id, hardware=hardware_json))
    return [response.id]


def delete_hardware(hardware_id):
    with connect() as channel:
        stub = hardware_pb2_grpc.HardwareServiceStub(channel)
        stub.Delete(hardware_pb2.DeleteRequest(id=hardware_id))
    return True


def delete_template(template_id):
    with connect() as channel:
        stub = template_pb2_grpc.TemplateServiceStub(channel)
        stub.DeleteTemplate(template_pb2.GetRequest(id=template_id))
    return True


def delete_workflow(workflow_id):
    with connect() as channel:
        stub = workflow_pb2_grpc.WorkflowServiceStub(channel)
        stub.DeleteWorkflow(workflow_pb2.GetRequest(id=workflow_id))
    return True


def ipmi_boot_pxe(host, username, password):
    ipmi_cmd = command.Command(bmc=host, userid=username, password=password)
    ipmi_cmd.set_bootdev("pxe")
    ipmi_cmd.set_power("boot")


def run():
    parser = create_parser()
    args = parser.parse_args()

    if args.tink_host is None:
        print("TINK_HOST environment variable must be set or --host must be specified")
        return

    args.tink_host = socket.gethostbyname(args.tink_host)
    auth = args.tink_host + ":" + args.rpc_port
    global connect

    if args.tls:
        global connect
        cert_url = 'http://' + args.tink_host + ':' + args.http_port + '/cert'
        with urllib.request.urlopen(cert_url) as response:
            trusted_certs = response.read()

        creds = grpc.ssl_channel_credentials(root_certificates=trusted_certs)

        def connect():
            return grpc.secure_channel(auth, creds)
    else:
        global connect

        def connect():
            return grpc.insecure_channel(auth)

    result = None
    raw_result = None
    if args.action == "get":
        if args.object == "hardware":
            result = get_hardware(args)
        elif args.object == "templates":
            result = get_all_templates()
        elif args.object == "template":
            if args.template_name is not None:
                raw_result = get_template_steps_by_name(args, raw_result)
            elif args.id is not None:
                raw_result = get_template_steps(args.id)
            else:
                print("Can't get template without template_name or id")
        elif args.object == "workflows":
            if args.host is not None:
                result = get_workflows_by_host(args.host)
            else:
                result = get_all_workflows()
        elif args.object == "workflow":
            if args.id is not None:
                result = get_workflow_events(args.id)
            elif args.host is not None:
                result = get_workflow_by_host(args.host)
            else:
                print("Can't get workflow without host or id")
        elif args.object == "workflow_contexts_by_hardware_id":
            if args.id is not None:
                result = get_workflow_by_hardware_id(args.id)
            else:
                print("Can't get workflow events without id")
        else:
            print("Get object must be one of: hardware, templates, template, "
                  "workflows, workflow, workflow_contexts_by_hardware_id")
    elif args.action == "push":
        if args.object == "workflow":
            if args.host is not None and args.template_name is not None:
                result = push_workflow(args.host, args.template_name)
                if args.reboot and \
                        ipmi_userid is not None and ipmi_password is not None:
                    hardware_info = get_hardware_name("ipmi." + args.host)
                    if hardware_info is not None:
                        bmc = hardware_info['ip']
                        ipmi_boot_pxe(host=bmc, username=ipmi_userid,
                                      password=ipmi_password)
            else:
                print("Workflow push requires host and template_name args")
        elif args.object == "hardware":
            if args.file is not None:
                result = push_hardware(args.file)
            else:
                print("Hardware push requires file arg")
        elif args.object == "template":
            if args.file is not None:
                result = push_template(args.file)
            else:
                print("Template push requires file arg")
        else:
            print("Push object must be one of: hardware, template, workflow")
    elif args.action == "delete":
        if args.object == "hardware":
            if args.id is not None:
                result = delete_hardware(args.id)
            else:
                print("Hardware delete requires id arg")
        elif args.object == "template":
            if args.id is not None:
                result = delete_template(args.id)
            else:
                print("Template delete requires id arg")
        elif args.object == "workflow":
            if args.id is not None:
                result = delete_workflow(args.id)
            else:
                print("Workflow delete requires id arg")
        else:
            print("Delete object must be one of: hardware, template, workflow")
    else:
        print("Invalid action specified, must be one of: get, push, delete")

    if result is not None:
        if args.format == "json":
            print(json.dumps(result, indent=2))
        elif args.format == "yaml":
            print(yaml.dump(result, default_flow_style=False, sort_keys=False))
    if raw_result is not None:
        print(raw_result)


if __name__ == '__main__':
    logging.basicConfig()
    run()
