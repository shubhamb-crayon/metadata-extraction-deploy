#!/bin/bash

# Detect if script is sourced or executed
is_sourced() {
    [[ "${BASH_SOURCE[0]}" != "${0}" ]]
}

safe_exit() {
    if is_sourced; then
        return "$1"
    else
        exit "$1"
    fi
}

TOKEN_CODE=$2
ARG_PROFILE=$1

# Determine profile to use
if [ -n "$ARG_PROFILE" ]; then
    PROFILE="$ARG_PROFILE"
elif [ -n "$AWS_PROFILE" ]; then
    PROFILE="$AWS_PROFILE"
else
    PROFILE="default"
fi

if [ -z "$TOKEN_CODE" ]; then
    echo "Usage: source $0 <mfa-token> [profile]"
    safe_exit 1
fi

# Clear existing AWS credentials (only when NOT sourced)
if ! is_sourced; then
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
fi

# Get profile details
ROLE_ARN=$(aws configure get role_arn --profile "$PROFILE")
MFA_SERIAL=$(aws configure get mfa_serial --profile "$PROFILE")
SOURCE_PROFILE=$(aws configure get source_profile --profile "$PROFILE")

TMP_FILE=".aws_session.json"
ENV_FILE=".env"

set_credentials() {
    ACCESS_KEY_ID=$(jq -r '.Credentials.AccessKeyId' "$TMP_FILE")
    SECRET_ACCESS_KEY=$(jq -r '.Credentials.SecretAccessKey' "$TMP_FILE")
    SESSION_TOKEN=$(jq -r '.Credentials.SessionToken' "$TMP_FILE")
    EXPIRATION=$(jq -r '.Credentials.Expiration' "$TMP_FILE")

    if is_sourced; then
        export AWS_ACCESS_KEY_ID="$ACCESS_KEY_ID"
        export AWS_SECRET_ACCESS_KEY="$SECRET_ACCESS_KEY"
        export AWS_SESSION_TOKEN="$SESSION_TOKEN"
        export AWS_DEFAULT_REGION=ap-southeast-1
    fi

    cat > "$ENV_FILE" <<EOF
AWS_ACCESS_KEY_ID=$ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=$SECRET_ACCESS_KEY
AWS_SESSION_TOKEN=$SESSION_TOKEN
AWS_SESSION_EXPIRATION=$EXPIRATION
AWS_DEFAULT_REGION=ap-southeast-1
EOF

    echo "✅ AWS credentials ready"
    echo "   Session expires at: $EXPIRATION"

    if ! is_sourced; then
        echo "👉 Run: source $ENV_FILE"
    fi
}

# Role vs IAM
if [ -n "$ROLE_ARN" ]; then
    if [ -z "$SOURCE_PROFILE" ] || [ -z "$MFA_SERIAL" ]; then
        echo "❌ Role profile [$PROFILE] missing source_profile or mfa_serial"
        safe_exit 1
    fi

    aws sts assume-role \
        --role-arn "$ROLE_ARN" \
        --role-session-name "${PROFILE}-session" \
        --serial-number "$MFA_SERIAL" \
        --token-code "$TOKEN_CODE" \
        --duration-seconds 14400 \
        --profile "$SOURCE_PROFILE" > "$TMP_FILE"
else
    if [ -z "$MFA_SERIAL" ]; then
        echo "❌ IAM user profile [$PROFILE] missing mfa_serial"
        safe_exit 1
    fi

    aws sts get-session-token \
        --serial-number "$MFA_SERIAL" \
        --token-code "$TOKEN_CODE" \
        --duration-seconds 36000 \
        --profile "$PROFILE" > "$TMP_FILE"
fi

if [ $? -eq 0 ]; then
    set_credentials
    rm -f "$TMP_FILE"
else
    echo "❌ Failed to get AWS session credentials"
    rm -f "$TMP_FILE"
    safe_exit 1
fi