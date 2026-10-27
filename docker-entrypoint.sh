#!/bin/sh
# Adds private CA certificates from EXTRA_CA_CERTS_DIR (default /certs) to the
# system trust store, then runs the container command.
set -e

CA_DIR="${EXTRA_CA_CERTS_DIR:-/certs}"
RUNTIME_CA_DIR="${RUNTIME_CA_CERTS_DIR:-/usr/local/share/ca-certificates/runtime}"

if [ -d "$RUNTIME_CA_DIR" ]; then
    rm -rf "$RUNTIME_CA_DIR"
fi

if [ -d "$CA_DIR" ]; then
    found=0
    for cert in "$CA_DIR"/*.crt; do
        [ -f "$cert" ] || continue
        mkdir -p "$RUNTIME_CA_DIR"
        cp "$cert" "$RUNTIME_CA_DIR"/
        found=1
    done
    if [ "$found" = "1" ]; then
        if update-ca-certificates; then
            echo "Loaded private CA certificates from $CA_DIR"
        else
            echo "Error: could not update the CA trust store from $CA_DIR" >&2
            exit 1
        fi
    fi
fi

exec "$@"
