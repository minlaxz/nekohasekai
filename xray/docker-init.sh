#!/bin/sh

WORK_DIR=/usr/bin
CONFIG_DIR=/etc/xray
RULES_DIR=/usr/share/xray
# XRAY_ARCH=$(uname -m)

warning() { echo -e "\033[31m\033[01m$*\033[0m"; }
info() { echo -e "\033[32m\033[01m$*\033[0m"; }
hint() { echo -e "\033[33m\033[01m$*\033[0m"; }

check_arch() {
  hint "Checking system architecture ..."
  case "$ARCH" in
    arm64 )
      XRAY_ARCH=linux-arm64-v8a;
      ;;
    amd64 )
      XRAY_ARCH=linux-64;
      ;;
    armv7 )
      XRAY_ARCH=linux-arm32-v7a;
      ;;
  esac
  hint "System architecture: $ARCH"
}

check_latest_xray() {
  local VERSION_LATEST=$(wget -qO- "https://api.github.com/repos/XTLS/Xray-core/releases" | awk -F '["v-]' '/tag_name/{print $5}' | sort -r | sed -n '1p')
  XRAY_VERSION=$(wget -qO- "https://api.github.com/repos/XTLS/Xray-core/releases" | awk -F '["v]' -v var="tag_name.*$VERSION_LATEST" '$0 ~ var {print $5; exit}')
}

check_arch
check_latest_xray

# Checks
if [ -z "$XRAY_ARCH" || -z "$XRAY_VERSION"]; then
  warning "architecture: $ARCH"
  warning "version: $XRAY_VERSION"
  exit 1
fi

XRAY_FILE="Xray-${XRAY_ARCH}.zip"
XRAY_DOWNLOAD_URL="https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/${XRAY_FILE}"

# Download
hint "Downloading zip file: ${XRAY_FILE}"
wget --no-check-certificate -O /${XRAY_FILE} ${XRAY_DOWNLOAD_URL} > /dev/null 2>&1
if [ $? -ne 0 ]; then
    warning "Error: Failed to download zip file: ${XRAY_FILE}" && exit 1
fi
info "Download zip file: ${XRAY_FILE} completed"

# Unzip
hist "Unzipping file: ${XRAY_FILE}"
unzip -o /${XRAY_FILE} -d $WORK_DIR/ > /dev/null 2>&1
if [ $? -ne 0 ]; then
    warning "Error: Failed to unzip file: ${XRAY_FILE}" && exit 1
fi
info "Unzipping file: ${XRAY_FILE} completed"

# Rules
mv $WORK_DIR/*.dat $RULES_DIR/

# Config
# cat > $CONFIG_DIR/config.json << EOF
# {
#   "log": {
#     "loglevel": "warning"
#   },
#   "inbounds": [],
#   "outbounds": [
#     {
#       "protocol": "freedom",
#       "settings": {}
#     }
#   ]
# }
# EOF

# Clean up
info "Cleaning up ..."
rm -fr *.zip $WORK_DIR/*.md $WORK_DIR/LICENSE

# Run it!
info "Starting Xray ..."
chmod +x $WORK_DIR/xray
$WORK_DIR/xray -config $CONFIG_DIR/config.json > /dev/null 2>&1
