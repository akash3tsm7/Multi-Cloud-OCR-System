# AWS Infrastructure Setup Guide

## IAM Role for Lambda

```bash
# Create trust policy
cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

# Create role
aws iam create-role \
  --role-name ocr-lambda-role \
  --assume-role-policy-document file:///tmp/trust-policy.json

# Attach required policies
aws iam attach-role-policy \
  --role-name ocr-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonRekognitionFullAccess

aws iam attach-role-policy \
  --role-name ocr-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonTextractFullAccess

aws iam attach-role-policy \
  --role-name ocr-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy \
  --role-name ocr-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchLogsFullAccess

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name ocr-lambda-role --query Role.Arn --output text)
echo "Role ARN: $ROLE_ARN"
```

## S3 Buckets

```bash
REGION=us-east-1

# Input bucket
aws s3api create-bucket \
  --bucket ocr-input-bucket \
  --region $REGION

# Output bucket
aws s3api create-bucket \
  --bucket ocr-output-bucket \
  --region $REGION

# Enable versioning (optional, for audit trail)
aws s3api put-bucket-versioning \
  --bucket ocr-input-bucket \
  --versioning-configuration Status=Enabled
```

## Lambda: OCR-S3Processor (S3-triggered)

```bash
ROLE_ARN=$(aws iam get-role --role-name ocr-lambda-role --query Role.Arn --output text)
REGION=us-east-1

# Create the function
aws lambda create-function \
  --function-name OCR-S3Processor \
  --runtime python3.11 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://aws-lambda/s3_ocr_handler/function.zip \
  --region $REGION \
  --timeout 60 \
  --memory-size 256 \
  --environment "Variables={
    AWS_S3_INPUT_BUCKET=ocr-input-bucket,
    AWS_S3_OUTPUT_BUCKET=ocr-output-bucket,
    AWS_REGION=$REGION
  }"

# Add S3 trigger permission
aws lambda add-permission \
  --function-name OCR-S3Processor \
  --statement-id s3-trigger \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::ocr-input-bucket \
  --region $REGION

# Create S3 event notification
cat > /tmp/s3-notification.json << 'EOF'
{
  "LambdaFunctionConfigurations": [{
    "LambdaFunctionArn": "REPLACE_WITH_LAMBDA_ARN",
    "Events": ["s3:ObjectCreated:*"]
  }]
}
EOF

LAMBDA_ARN=$(aws lambda get-function --function-name OCR-S3Processor --query Configuration.FunctionArn --output text)
sed -i "s|REPLACE_WITH_LAMBDA_ARN|$LAMBDA_ARN|g" /tmp/s3-notification.json

aws s3api put-bucket-notification-configuration \
  --bucket ocr-input-bucket \
  --notification-configuration file:///tmp/s3-notification.json
```

## Lambda: OCR-ApiHandler (API Gateway-triggered)

```bash
ROLE_ARN=$(aws iam get-role --role-name ocr-lambda-role --query Role.Arn --output text)
REGION=us-east-1

aws lambda create-function \
  --function-name OCR-ApiHandler \
  --runtime python3.11 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://aws-lambda/api_handler/function.zip \
  --region $REGION \
  --timeout 30 \
  --memory-size 128 \
  --environment "Variables={
    AWS_S3_INPUT_BUCKET=ocr-input-bucket,
    AWS_S3_OUTPUT_BUCKET=ocr-output-bucket,
    AWS_REGION=$REGION
  }"
```

## API Gateway

```bash
REGION=us-east-1

# Create REST API
API_ID=$(aws apigateway create-rest-api \
  --name "OCR-MultiCloud-API" \
  --region $REGION \
  --query id --output text)

# Get root resource
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id $API_ID \
  --region $REGION \
  --query "items[?path=='/'].id" --output text)

# Create /ocr resource
OCR_RESOURCE=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part "ocr" \
  --region $REGION \
  --query id --output text)

# Create /result/{key} resource
RESULT_RESOURCE=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part "result" \
  --region $REGION \
  --query id --output text)

KEY_RESOURCE=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $RESULT_RESOURCE \
  --path-part "{key}" \
  --region $REGION \
  --query id --output text)

LAMBDA_ARN=$(aws lambda get-function --function-name OCR-ApiHandler --query Configuration.FunctionArn --output text)

# Add POST /ocr method
aws apigateway put-method \
  --rest-api-id $API_ID --resource-id $OCR_RESOURCE \
  --http-method POST --authorization-type NONE --region $REGION

aws apigateway put-integration \
  --rest-api-id $API_ID --resource-id $OCR_RESOURCE \
  --http-method POST --type AWS_PROXY \
  --integration-http-method POST \
  --uri "arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/$LAMBDA_ARN/invocations" \
  --region $REGION

# Add GET /result/{key} method
aws apigateway put-method \
  --rest-api-id $API_ID --resource-id $KEY_RESOURCE \
  --http-method GET --authorization-type NONE --region $REGION

aws apigateway put-integration \
  --rest-api-id $API_ID --resource-id $KEY_RESOURCE \
  --http-method GET --type AWS_PROXY \
  --integration-http-method POST \
  --uri "arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/$LAMBDA_ARN/invocations" \
  --region $REGION

# Grant API Gateway permission to invoke Lambda
ACC_ID=$(aws sts get-caller-identity --query Account --output text)
aws lambda add-permission \
  --function-name OCR-ApiHandler \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$REGION:$ACC_ID:$API_ID/*/*/*" \
  --region $REGION

# Deploy to prod stage
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod \
  --region $REGION

echo "API URL: https://$API_ID.execute-api.$REGION.amazonaws.com/prod"
```

## Test AWS API

```bash
API_URL="https://<API_ID>.execute-api.us-east-1.amazonaws.com/prod"

# Upload test image
aws s3 cp tests/sample.jpg s3://ocr-input-bucket/sample.jpg

# POST on-demand OCR
curl -X POST "$API_URL/ocr" \
  -H "Content-Type: application/json" \
  -d '{"s3_key": "sample.jpg"}'

# GET stored result
curl "$API_URL/result/sample.jpg"
```

## Deploy Lambda Functions

```bash
cd aws-lambda/
bash deploy_lambda.sh all
```
