#!/bin/sh

python3 -m venv --system-site-packages venv
./venv/bin/pip3 install -r requirements.txt
which direnv >/dev/null 2>&1
if [ $? -eq 0 ]; then
  direnv allow
else
  echo "Run: ./venv/bin/activate"
fi
