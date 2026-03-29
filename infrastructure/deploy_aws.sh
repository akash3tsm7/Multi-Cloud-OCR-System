#!/bin/bash
# =============================================================================
# deploy_aws.sh
# One-command AWS provisioning: creates ALL resources from scratch.
# Usage: bash infrastructure/deploy_aws.sh
#
# Prerequisites:
#   1. AWS CLI installed:  https://aws.amazon.com/cli/
#   2. Configured:         aws configure   (enter your Access Key ID + Secret)
#   3. Python 3 + pip (for packaging Lambdas)
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

# ── Configuration ─────────────────────────────────────────────────────────────
REGION="${AWS_REGION:-us-east-1}"
ROLE_NAME="ocr-lambda-role"
LAMBDA_S3="OCR-S3Processor"
LAMBDA_API="OCR-ApiHandler"
API_NAME="OCR-MultiCloud-API"
PYTHON_RUNTIME="python3.11"

# ── Sanity checks ─────────────────────────────────────────────────────────────
command -v aws    &>/dev/null || die "AWS CLI not found. Install from: https://aws.amazon.com/cli/"
command -v python3 &>/dev/null || die "Python 3 not found."
command -v pip3   &>/dev/null || die "pip3 not found."
command -v zip    &>/dev/null || die "zip not found. Install with: sudo apt install zip"

aws sts get-caller-identity &>/dev/null || die "AWS credentials not configured. Run: aws configure"

ACC_ID=$(aws sts get-caller-identity --query Account --output text)
info "Logged in. Account: $ACC_ID | Region: $REGION"

# Bucket names use account ID to be globally unique across all AWS accounts
INPUT_BUCKET="ocr-input-bucket-${ACC_ID}"
OUTPUT_BUCKET="ocr-output-bucket-${ACC_ID}"

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── Helper: package a Lambda ──────────────────────────────────────────────────
package_lambda() {
    local SRC_DIR="$1"
    local FUNC_FILE="$SRC_DIR/lambda_function.py"
    local ZIP_FILE="$SRC_DIR/function.zip"

    info "Packaging $(basename $SRC_DIR)..."
    rm -rf "$SRC_DIR/package" "$ZIP_FILE"

    if [ -f "$SRC_DIR/requirements.txt" ]; then
        pip3 install -r "$SRC_DIR/requirements.txt" -t "$SRC_DIR/package" --quiet
    else
        mkdir -p "$SRC_DIR/package"
    fi

    cp "$FUNC_FILE" "$SRC_DIR/package/"
    (cd "$SRC_DIR/package" && zip -r "$ZIP_FILE" . -x "*.pyc" -x "__pycache__/*" > /dev/null)
    rm -rf "$SRC_DIR/package"
    success "Packaged: $(du -sh $ZIP_FILE | cut -f1)"
}

header "Step 1/7 — IAM Role for Lambda"
ROLE_ARN=""
if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    warn "IAM role '$ROLE_NAME' already exists. Reusing."
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
else
    TRUST_POLICY='{
      "Version":"2012-10-17",
      "Statement":[{
        "Effect":"Allow",
        "Principal":{"Service":"lambda.amazonaws.com"},
        "Action":"sts:AssumeRole"
      }]
    }'
    ROLE_ARN=$(aws iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "$TRUST_POLICY" \
      --query Role.Arn --output text)
    success "Created IAM role: $ROLE_NAME"

    info "Attaching policies..."
    for POLICY in \
        "arn:aws:iam::aws:policy/AmazonRekognitionFullAccess" \
        "arn:aws:iam::aws:policy/AmazonTextractFullAccess" \
        "arn:aws:iam::aws:policy/AmazonS3FullAccess" \
        "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"; do
        aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY"
    done
    success "Policies attached."

    info "Waiting for IAM role to propagate (15s)..."
    sleep 15
fi

header "Step 2/7 — S3 Buckets"
for BUCKET in "$INPUT_BUCKET" "$OUTPUT_BUCKET"; do
    if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
        warn "Bucket '$BUCKET' already exists. Reusing."
    else
        if [ "$REGION" = "us-east-1" ]; then
            aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" > /dev/null
        else
            aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
              --create-bucket-configuration LocationConstraint="$REGION" > /dev/null
        fi
        # Block public access
        aws s3api put-public-access-block --bucket "$BUCKET" \
          --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
        success "Created bucket: $BUCKET"
    fi
done

header "Step 3/7 — Package Lambda Functions"
package_lambda "$SCRIPT_DIR/aws-lambda/s3_ocr_handler"
package_lambda "$SCRIPT_DIR/aws-lambda/api_handler"

LAMBDA_ENV="Variables={AWS_S3_INPUT_BUCKET=${INPUT_BUCKET},AWS_S3_OUTPUT_BUCKET=${OUTPUT_BUCKET}}"

header "Step 4/7 — Lambda: $LAMBDA_S3 (S3-triggered)"
if aws lambda get-function --function-name "$LAMBDA_S3" --region "$REGION" &>/dev/null; then
    warn "Function '$LAMBDA_S3' already exists. Updating code..."
    aws lambda update-function-code \
      --function-name "$LAMBDA_S3" \
      --zip-file "fileb://$SCRIPT_DIR/aws-lambda/s3_ocr_handler/function.zip" \
      --region "$REGION" --output text > /dev/null
else
    aws lambda create-function \
      --function-name "$LAMBDA_S3" \
      --runtime "$PYTHON_RUNTIME" \
      --role "$ROLE_ARN" \
      --handler lambda_function.lambda_handler \
      --zip-file "fileb://$SCRIPT_DIR/aws-lambda/s3_ocr_handler/function.zip" \
      --region "$REGION" \
      --timeout 60 \
      --memory-size 256 \
      --environment "$LAMBDA_ENV" \
      > /dev/null
    success "Created Lambda: $LAMBDA_S3"
fi

# S3 trigger permission
aws lambda remove-permission --function-name "$LAMBDA_S3" --statement-id s3-trigger --region "$REGION" 2>/dev/null || true
aws lambda add-permission \
  --function-name "$LAMBDA_S3" \
  --statement-id s3-trigger \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::${INPUT_BUCKET}" \
  --region "$REGION" > /dev/null

S3_LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_S3" --region "$REGION" \
  --query Configuration.FunctionArn --output text)

# Set S3 notification
cat > /tmp/s3-notification.json <<EOF
{
  "LambdaFunctionConfigurations": [{
    "LambdaFunctionArn": "${S3_LAMBDA_ARN}",
    "Events": ["s3:ObjectCreated:*"]
  }]
}
EOF
aws s3api put-bucket-notification-configuration \
  --bucket "$INPUT_BUCKET" \
  --notification-configuration file:///tmp/s3-notification.json
success "$LAMBDA_S3 wired to S3 trigger."

header "Step 5/7 — Lambda: $LAMBDA_API (API Gateway-triggered)"
if aws lambda get-function --function-name "$LAMBDA_API" --region "$REGION" &>/dev/null; then
    warn "Function '$LAMBDA_API' already exists. Updating code..."
    aws lambda update-function-code \
      --function-name "$LAMBDA_API" \
      --zip-file "fileb://$SCRIPT_DIR/aws-lambda/api_handler/function.zip" \
      --region "$REGION" --output text > /dev/null
else
    aws lambda create-function \
      --function-name "$LAMBDA_API" \
      --runtime "$PYTHON_RUNTIME" \
      --role "$ROLE_ARN" \
      --handler lambda_function.lambda_handler \
      --zip-file "fileb://$SCRIPT_DIR/aws-lambda/api_handler/function.zip" \
      --region "$REGION" \
      --timeout 30 \
      --memory-size 128 \
      --environment "$LAMBDA_ENV" \
      > /dev/null
    success "Created Lambda: $LAMBDA_API"
fi

API_LAMBDA_ARN=$(aws lambda get-function --function-name "$LAMBDA_API" --region "$REGION" \
  --query Configuration.FunctionArn --output text)

header "Step 6/7 — API Gateway (REST)"

# Check if API already exists
EXISTING_API=$(aws apigateway get-rest-apis --region "$REGION" \
  --query "items[?name=='$API_NAME'].id" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_API" ] && [ "$EXISTING_API" != "None" ]; then
    API_ID="$EXISTING_API"
    warn "API '$API_NAME' already exists (ID: $API_ID). Reusing."
else
    API_ID=$(aws apigateway create-rest-api \
      --name "$API_NAME" \
      --region "$REGION" \
      --query id --output text)
    success "Created API Gateway: $API_NAME (ID: $API_ID)"
fi

ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id "$API_ID" --region "$REGION" \
  --query "items[?path=='/'].id" --output text)

# Helper to create or reuse a resource
create_resource() {
    local PARENT="$1"; local PATH_PART="$2"
    local EXISTING
    EXISTING=$(aws apigateway get-resources --rest-api-id "$API_ID" --region "$REGION" \
      --query "items[?pathPart=='$PATH_PART'].id" --output text 2>/dev/null || echo "")
    if [ -n "$EXISTING" ] && [ "$EXISTING" != "None" ]; then
        echo "$EXISTING"; return
    fi
    aws apigateway create-resource \
      --rest-api-id "$API_ID" --parent-id "$PARENT" \
      --path-part "$PATH_PART" --region "$REGION" \
      --query id --output text
}

add_method_integration() {
    local RESOURCE="$1"; local HTTP_METHOD="$2"; local LAMBDA="$3"
    # PUT method (idempotent)
    aws apigateway put-method \
      --rest-api-id "$API_ID" --resource-id "$RESOURCE" \
      --http-method "$HTTP_METHOD" --authorization-type NONE \
      --region "$REGION" > /dev/null 2>&1 || true
    # PUT integration
    aws apigateway put-integration \
      --rest-api-id "$API_ID" --resource-id "$RESOURCE" \
      --http-method "$HTTP_METHOD" --type AWS_PROXY \
      --integration-http-method POST \
      --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA}/invocations" \
      --region "$REGION" > /dev/null 2>&1 || true
    # Lambda permission
    local STMT_ID="apigw-${HTTP_METHOD,,}-$(echo $RESOURCE | tr -d '-')-$$"
    aws lambda add-permission \
      --function-name "$LAMBDA_API" \
      --statement-id "$STMT_ID" \
      --action lambda:InvokeFunction \
      --principal apigateway.amazonaws.com \
      --source-arn "arn:aws:execute-api:${REGION}:${ACC_ID}:${API_ID}/*/${HTTP_METHOD}/*" \
      --region "$REGION" > /dev/null 2>&1 || true
}

info "Creating /ocr resource..."
OCR_ID=$(create_resource "$ROOT_ID" "ocr")
add_method_integration "$OCR_ID" "POST" "$API_LAMBDA_ARN"

info "Creating /result/{key} resource..."
RESULT_ID=$(create_resource "$ROOT_ID" "result")
KEY_ID=$(create_resource "$RESULT_ID" "{key}")
add_method_integration "$KEY_ID" "GET" "$API_LAMBDA_ARN"

info "Adding OPTIONS for CORS on /ocr..."
aws apigateway put-method \
  --rest-api-id "$API_ID" --resource-id "$OCR_ID" \
  --http-method OPTIONS --authorization-type NONE \
  --region "$REGION" > /dev/null 2>&1 || true
aws apigateway put-integration \
  --rest-api-id "$API_ID" --resource-id "$OCR_ID" \
  --http-method OPTIONS --type MOCK \
  --request-templates '{"application/json": "{\"statusCode\": 200}"}' \
  --region "$REGION" > /dev/null 2>&1 || true

info "Deploying to 'prod' stage..."
aws apigateway create-deployment \
  --rest-api-id "$API_ID" \
  --stage-name prod \
  --region "$REGION" > /dev/null

API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/prod"
success "API Gateway deployed."

header "Step 7/7 — Update .env"
ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
fi
# These placeholders will be filled after user runs aws configure
echo "" >> "$ENV_FILE"
echo "# AWS (auto-filled by deploy_aws.sh)" >> "$ENV_FILE"
echo "AWS_REGION=$REGION" >> "$ENV_FILE"
echo "AWS_S3_INPUT_BUCKET=$INPUT_BUCKET" >> "$ENV_FILE"
echo "AWS_S3_OUTPUT_BUCKET=$OUTPUT_BUCKET" >> "$ENV_FILE"

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  ✅  AWS PROVISIONING COMPLETE!${RESET}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${BOLD}Resources created:${RESET}"
echo "  IAM Role:      $ROLE_NAME"
echo "  S3 Buckets:    $INPUT_BUCKET  |  $OUTPUT_BUCKET"
echo "  Lambda (S3):   $LAMBDA_S3"
echo "  Lambda (API):  $LAMBDA_API"
echo "  API Gateway:   $API_NAME"
echo ""
echo -e "${BOLD}AWS API URL (paste into UI config panel):${RESET}"
echo "  $API_URL"
echo ""
echo -e "${BOLD}Add these to your .env file:${RESET}"
echo "  AWS_ACCESS_KEY_ID=<from aws configure>"
echo "  AWS_SECRET_ACCESS_KEY=<from aws configure>"
echo "  AWS_REGION=$REGION"
echo "  AWS_S3_INPUT_BUCKET=$INPUT_BUCKET"
echo "  AWS_S3_OUTPUT_BUCKET=$OUTPUT_BUCKET"
echo ""
echo -e "${YELLOW}⚠️  Don't forget: paste your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY into .env${RESET}"
echo -e "${YELLOW}    and update the Function App settings:${RESET}"
echo -e "${YELLOW}    az functionapp config appsettings set --name ocr-serverless-func --resource-group rg-ocr-multicloud --settings AWS_ACCESS_KEY_ID=<KEY> AWS_SECRET_ACCESS_KEY=<SECRET>${RESET}"
echo ""
