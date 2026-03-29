#!/bin/bash
# =============================================================================
# deploy_azure.sh
# One-command Azure provisioning: creates ALL resources from scratch.
# Usage: bash infrastructure/deploy_azure.sh
#
# Prerequisites:
#   1. Azure CLI installed:  https://docs.microsoft.com/en-us/cli/azure/install-azure-cli
#   2. Logged in:            az login
#   3. Azure Functions Core Tools:  npm install -g azure-functions-core-tools@4
# =============================================================================

set -euo pipefail

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
header()  { echo -e "\n${BOLD}${CYAN}=== $* ===${RESET}\n"; }
die()     { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ── Configuration — change these if you want different names ──────────────────
RESOURCE_GROUP="rg-ocr-multicloud"
LOCATION="southeastasia"
STORAGE_ACCOUNT="rgocrmulticloudacbc"
VISION_NAME="ocrvision-akash-2026"
APPINSIGHTS_NAME="ocr-appinsights"
FUNCTION_APP="ocr-serverless-func"
PYTHON_VERSION="3.11"
FUNCTIONS_VERSION="4"

# ── Sanity checks ─────────────────────────────────────────────────────────────
command -v az &>/dev/null   || die "Azure CLI not found. Install from: https://aka.ms/installazurecli"
command -v func &>/dev/null || warn "Azure Functions Core Tools not found. You won't be able to deploy code. Install: npm install -g azure-functions-core-tools@4"

# Check logged in
az account show &>/dev/null || die "Not logged in. Run: az login"

SUBSCRIPTION=$(az account show --query name -o tsv)
info "Logged in. Subscription: $SUBSCRIPTION"

header "Step 1/6 — Resource Group"
if az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    warn "Resource group '$RESOURCE_GROUP' already exists. Reusing."
else
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none
    success "Created resource group: $RESOURCE_GROUP"
fi

header "Step 2/6 — Storage Account + Blob Containers"
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    warn "Storage account '$STORAGE_ACCOUNT' already exists. Reusing."
else
    az storage account create \
      --name "$STORAGE_ACCOUNT" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku Standard_LRS \
      --kind StorageV2 \
      -o none
    success "Created storage account: $STORAGE_ACCOUNT"
fi

# Get connection string
STORAGE_CONN=$(az storage account show-connection-string \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query connectionString -o tsv)

# Create containers (ignore if already exists)
info "Creating blob containers..."
az storage container create --name input-images   --account-name "$STORAGE_ACCOUNT" --connection-string "$STORAGE_CONN" -o none || true
az storage container create --name output-results --account-name "$STORAGE_ACCOUNT" --connection-string "$STORAGE_CONN" -o none || true
success "Blob containers ready: input-images, output-results"

header "Step 3/6 — Computer Vision (OCR)"
if az cognitiveservices account show --name "$VISION_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    warn "Computer Vision '$VISION_NAME' already exists. Reusing."
else
    az cognitiveservices account create \
      --name "$VISION_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --kind ComputerVision \
      --sku S1 \
      --location "$LOCATION" \
      --yes \
      -o none
    success "Created Computer Vision: $VISION_NAME"
fi

VISION_KEY=$(az cognitiveservices account keys list \
  --name "$VISION_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query key1 -o tsv)

VISION_ENDPOINT=$(az cognitiveservices account show \
  --name "$VISION_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.endpoint -o tsv)

header "Step 4/6 — Application Insights (Monitoring)"
az extension add --name application-insights 2>/dev/null || true

if az monitor app-insights component show --app "$APPINSIGHTS_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    warn "App Insights '$APPINSIGHTS_NAME' already exists. Reusing."
else
    az monitor app-insights component create \
      --app "$APPINSIGHTS_NAME" \
      --location "$LOCATION" \
      --resource-group "$RESOURCE_GROUP" \
      --application-type web \
      -o none
    success "Created App Insights: $APPINSIGHTS_NAME"
fi

APPINSIGHTS_KEY=$(az monitor app-insights component show \
  --app "$APPINSIGHTS_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query instrumentationKey -o tsv)

header "Step 5/6 — Azure Function App"
if az functionapp show --name "$FUNCTION_APP" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    warn "Function App '$FUNCTION_APP' already exists. Reusing."
else
    az functionapp create \
      --name "$FUNCTION_APP" \
      --resource-group "$RESOURCE_GROUP" \
      --storage-account "$STORAGE_ACCOUNT" \
      --consumption-plan-location "$LOCATION" \
      --runtime python \
      --runtime-version "$PYTHON_VERSION" \
      --functions-version "$FUNCTIONS_VERSION" \
      --os-type linux \
      -o none
    success "Created Function App: $FUNCTION_APP"
fi

# Set app settings (we'll fill AWS keys as placeholders — add them later)
info "Setting Function App environment variables..."
az functionapp config appsettings set \
  --name "$FUNCTION_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --settings \
    "AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN" \
    "AZURE_VISION_KEY=$VISION_KEY" \
    "AZURE_VISION_ENDPOINT=$VISION_ENDPOINT" \
    "APPINSIGHTS_INSTRUMENTATIONKEY=$APPINSIGHTS_KEY" \
    "AWS_ACCESS_KEY_ID=PLACEHOLDER" \
    "AWS_SECRET_ACCESS_KEY=PLACEHOLDER" \
    "AWS_REGION=us-east-1" \
    "AWS_S3_INPUT_BUCKET=ocr-input-bucket" \
    "AWS_S3_OUTPUT_BUCKET=ocr-output-bucket" \
  -o none
success "Environment variables set."

# Enable CORS for the web UI
info "Enabling CORS for web UI..."
az functionapp cors add \
  --name "$FUNCTION_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --allowed-origins "*" \
  -o none 2>/dev/null || warn "CORS already configured or not supported in this tier."

header "Step 6/6 — Deploy Function Code"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AZURE_FUNC_DIR="$SCRIPT_DIR/azure-functions"

if command -v func &>/dev/null; then
    info "Deploying Azure Functions code..."
    cd "$AZURE_FUNC_DIR"
    func azure functionapp publish "$FUNCTION_APP" --python
    cd "$SCRIPT_DIR"
    success "Functions deployed!"
else
    warn "Skipping code deploy — func CLI not found."
    warn "Install it, then run: cd azure-functions && func azure functionapp publish $FUNCTION_APP"
fi

# ── Output .env values ────────────────────────────────────────────────────────
FUNC_URL="https://${FUNCTION_APP}.azurewebsites.net/api"

echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  ✅  AZURE PROVISIONING COMPLETE!${RESET}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}Add these to your .env file:${RESET}"
echo ""
echo "AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN"
echo "AZURE_VISION_KEY=$VISION_KEY"
echo "AZURE_VISION_ENDPOINT=$VISION_ENDPOINT"
echo "APPINSIGHTS_INSTRUMENTATIONKEY=$APPINSIGHTS_KEY"
echo ""
echo -e "${BOLD}Azure Function API URL (paste into UI config panel):${RESET}"
echo "$FUNC_URL"
echo ""
echo -e "${YELLOW}Next: Run  bash infrastructure/deploy_aws.sh  to provision AWS resources.${RESET}"
echo ""

# Write to .env automatically
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
fi

# Update Azure lines in .env
sed -i "s|AZURE_STORAGE_CONNECTION_STRING=.*|AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONN|" "$ENV_FILE"
sed -i "s|AZURE_VISION_KEY=.*|AZURE_VISION_KEY=$VISION_KEY|" "$ENV_FILE"
sed -i "s|AZURE_VISION_ENDPOINT=.*|AZURE_VISION_ENDPOINT=$VISION_ENDPOINT|" "$ENV_FILE"
sed -i "s|APPINSIGHTS_INSTRUMENTATIONKEY=.*|APPINSIGHTS_INSTRUMENTATIONKEY=$APPINSIGHTS_KEY|" "$ENV_FILE"

success ".env file updated automatically with Azure credentials!"
