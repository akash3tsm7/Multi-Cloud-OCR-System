#!/bin/bash
# deploy_lambda.sh
# Packages and deploys both Lambda functions to AWS.
# Usage: bash deploy_lambda.sh [s3_handler|api_handler|all]

set -e

FUNCTION_S3="OCR-S3Processor"
FUNCTION_API="OCR-ApiHandler"
REGION="${AWS_REGION:-us-east-1}"
TARGET="${1:-all}"

echo "=== Multi-Cloud OCR — Lambda Deploy ==="
echo "Region: $REGION | Target: $TARGET"
echo ""

package_and_deploy() {
    local DIR="$1"
    local FUNC_NAME="$2"

    echo "── Packaging $FUNC_NAME from $DIR ──"
    cd "$DIR"

    # Clean previous build
    rm -rf package/ function.zip

    # Install dependencies
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt -t ./package --quiet
    fi

    # Copy source to package dir
    cp lambda_function.py package/

    # Zip it up
    cd package
    zip -r ../function.zip . -x "*.pyc" -x "__pycache__/*" > /dev/null
    cd ..

    echo "   Package size: $(du -sh function.zip | cut -f1)"

    # Check if function exists
    if aws lambda get-function --function-name "$FUNC_NAME" --region "$REGION" > /dev/null 2>&1; then
        echo "   Updating existing function: $FUNC_NAME"
        aws lambda update-function-code \
            --function-name "$FUNC_NAME" \
            --zip-file fileb://function.zip \
            --region "$REGION" \
            --output text --query "FunctionName"
    else
        echo "   ERROR: Function '$FUNC_NAME' does not exist in $REGION."
        echo "   Please create it first via the AWS Console or aws_setup.md instructions."
        exit 1
    fi

    # Update environment variables
    aws lambda update-function-configuration \
        --function-name "$FUNC_NAME" \
        --region "$REGION" \
        --environment "Variables={
            AWS_S3_INPUT_BUCKET=${AWS_S3_INPUT_BUCKET:-ocr-input-bucket},
            AWS_S3_OUTPUT_BUCKET=${AWS_S3_OUTPUT_BUCKET:-ocr-output-bucket},
            AWS_REGION=$REGION
        }" \
        --output text --query "FunctionName" > /dev/null

    echo "   ✅ $FUNC_NAME deployed successfully."
    echo ""

    # Return to aws-lambda root
    cd "$(dirname "$0")"
}

# Resolve script directory (aws-lambda/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "$TARGET" == "all" || "$TARGET" == "s3_handler" ]]; then
    package_and_deploy "$SCRIPT_DIR/s3_ocr_handler" "$FUNCTION_S3"
fi

if [[ "$TARGET" == "all" || "$TARGET" == "api_handler" ]]; then
    package_and_deploy "$SCRIPT_DIR/api_handler" "$FUNCTION_API"
fi

echo "=== Deploy complete ==="
