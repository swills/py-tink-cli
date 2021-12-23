#!/bin/sh


for x in template packet hardware workflow ; do
  python -m grpc_tools.protoc -I../tink/protos/${x} -I../googleapis/ --python_out=. --grpc_python_out=. ../tink/protos/${x}/${x}.proto
done
