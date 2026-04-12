#!/usr/bin/env bash
# Generate a self-signed CA certificate for Squid SSL bump.
# The CA cert must be imported into the browser's trust store.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/ssl_cert"

mkdir -p "${CERT_DIR}"

CA_KEY="${CERT_DIR}/ca.key"
CA_CERT="${CERT_DIR}/ca.crt"
CA_PEM="${CERT_DIR}/ca.pem"

echo "Generating CA certificate for Squid SSL bump..."
echo "Output directory: ${CERT_DIR}"

# Generate CA private key
openssl genrsa -out "${CA_KEY}" 4096

# Generate self-signed CA certificate (10 years)
openssl req -new -x509 -days 3650 -key "${CA_KEY}" \
    -out "${CA_CERT}" \
    -subj "/C=US/ST=Local/L=Local/O=SquidCode Proxy/CN=SquidCode CA"

# Combined PEM for convenience
cat "${CA_CERT}" "${CA_KEY}" > "${CA_PEM}"

echo ""
echo "Done! Files generated:"
echo "  CA key:   ${CA_KEY}"
echo "  CA cert:  ${CA_CERT}"
echo "  Combined: ${CA_PEM}"
echo ""
echo "IMPORTANT: Import ${CA_CERT} into your browser's trusted root certificates."
echo ""
echo "For Firefox: Settings → Privacy & Security → View Certificates → Import"
echo "For Chrome:  Settings → Security → Manage Certificates → Import"
echo ""
echo "Then update squid.conf sslcrtd_program path and run:"
echo "  squid -z    # initialize cache"
echo "  squid -f \${SCRIPT_DIR}/squid.conf"
