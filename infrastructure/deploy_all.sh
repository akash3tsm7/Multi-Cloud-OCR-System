#!/bin/bash
# =============================================================================
# deploy_all.sh — Master deploy script
# Provisions ALL Azure + AWS resources in one shot.
#
# Usage: bash infrastructure/deploy_all.sh
#
# Prerequisites:
#   Azure: az login
#   AWS:   aws configure   (enter Access Key ID + Secret from IAM)
# =============================================================================

set -euo pipefail

CYAN='\033[0;36m'; BOLD='\033[1m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; RESET='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════╗"
echo "║       Multi-Cloud OCR — Full Deployment          ║"
echo "║         Azure + AWS  (one-command setup)         ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${RESET}"

echo -e "${BOLD}This will create:${RESET}"
echo "  Azure: Resource Group, Storage, Computer Vision, App Insights, Function App"
echo "  AWS:   S3 Buckets, IAM Role, 2x Lambda, API Gateway"
echo ""
read -p "Press ENTER to continue (or Ctrl+C to cancel)..."
echo ""

# ── Azure first ───────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}▶ Running Azure provisioning...${RESET}"
bash "$SCRIPT_DIR/deploy_azure.sh"

# ── AWS next ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}▶ Running AWS provisioning...${RESET}"
bash "$SCRIPT_DIR/deploy_aws.sh"

echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  🎉  FULL DEPLOYMENT COMPLETE!${RESET}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo "  1. Open  ui/index.html  in your browser"
echo "  2. Paste the Azure Function URL + AWS API URL into the config panel"
echo "  3. Click Save Config → drop an image → click Run OCR"
echo ""
echo -e "${YELLOW}Tip: Your .env file has been auto-updated with all Azure credentials.${RESET}"
echo -e "${YELLOW}     Add your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY manually.${RESET}"
echo ""
