"""
AWS Account Manager
Manages multiple AWS account integrations (Vantage.sh-style).
Supports cross-account IAM Role assumption and access-key credentials.
Persists accounts in a local JSON file.
"""

import json
import os
import uuid
import boto3
from datetime import datetime
from pathlib import Path
from config import Config


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ACCOUNTS_FILE.exists():
        ACCOUNTS_FILE.write_text(json.dumps({"accounts": []}, indent=2))


def _load_accounts():
    _ensure_data_dir()
    return json.loads(ACCOUNTS_FILE.read_text())


def _save_accounts(data):
    _ensure_data_dir()
    ACCOUNTS_FILE.write_text(json.dumps(data, indent=2, default=str))


# ------------------------------------------------------------------ #
#  Account CRUD
# ------------------------------------------------------------------ #

def list_accounts():
    """Return all registered accounts."""
    return _load_accounts().get("accounts", [])


def get_account(account_id):
    """Get a single account by its internal id."""
    for acct in list_accounts():
        if acct["id"] == account_id:
            return acct
    return None


def get_active_account():
    """Return the currently-active account, or None."""
    accounts = list_accounts()
    for acct in accounts:
        if acct.get("is_active"):
            return acct
    # Fallback: first connected account
    connected = [a for a in accounts if a.get("status") == "connected"]
    return connected[0] if connected else None


def set_active_account(account_id):
    """Switch the active account."""
    data = _load_accounts()
    found = False
    for acct in data["accounts"]:
        acct["is_active"] = (acct["id"] == account_id)
        if acct["id"] == account_id:
            found = True
    if found:
        _save_accounts(data)
    return found


def add_account(*, name, aws_account_id, auth_type, role_arn=None,
                external_id=None, access_key_id=None, secret_access_key=None,
                region=None):
    """
    Register a new AWS account.
    auth_type: 'iam_role' | 'access_key'
    """
    data = _load_accounts()

    # Prevent duplicates
    for a in data["accounts"]:
        if a["aws_account_id"] == aws_account_id:
            return None, "Account already registered"

    account = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "aws_account_id": aws_account_id,
        "auth_type": auth_type,
        "role_arn": role_arn or "",
        "external_id": external_id or "",
        "access_key_id": access_key_id or "",
        "secret_access_key": secret_access_key or "",
        "region": region or Config.AWS_REGION,
        "status": "pending",
        "status_message": "",
        "is_active": len(data["accounts"]) == 0,  # First account = active
        "created_at": datetime.utcnow().isoformat(),
        "last_checked": "",
    }

    # Test the connection immediately
    ok, msg = test_connection(account)
    account["status"] = "connected" if ok else "error"
    account["status_message"] = msg
    account["last_checked"] = datetime.utcnow().isoformat()

    data["accounts"].append(account)
    _save_accounts(data)
    return account, msg


def update_account(account_id, **kwargs):
    """Update mutable fields of an account."""
    data = _load_accounts()
    for acct in data["accounts"]:
        if acct["id"] == account_id:
            allowed = {"name", "role_arn", "external_id", "access_key_id",
                        "secret_access_key", "region", "auth_type"}
            for k, v in kwargs.items():
                if k in allowed:
                    acct[k] = v
            _save_accounts(data)
            return acct
    return None


def delete_account(account_id):
    """Remove an account."""
    data = _load_accounts()
    before = len(data["accounts"])
    data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
    if len(data["accounts"]) < before:
        # If we deleted the active one, activate the first remaining
        if data["accounts"] and not any(a.get("is_active") for a in data["accounts"]):
            data["accounts"][0]["is_active"] = True
        _save_accounts(data)
        return True
    return False


def refresh_account_status(account_id):
    """Re-test connection for a single account."""
    data = _load_accounts()
    for acct in data["accounts"]:
        if acct["id"] == account_id:
            ok, msg = test_connection(acct)
            acct["status"] = "connected" if ok else "error"
            acct["status_message"] = msg
            acct["last_checked"] = datetime.utcnow().isoformat()
            _save_accounts(data)
            return acct
    return None


def refresh_all_statuses():
    """Re-test every account."""
    data = _load_accounts()
    for acct in data["accounts"]:
        ok, msg = test_connection(acct)
        acct["status"] = "connected" if ok else "error"
        acct["status_message"] = msg
        acct["last_checked"] = datetime.utcnow().isoformat()
    _save_accounts(data)
    return data["accounts"]


# ------------------------------------------------------------------ #
#  AWS Organizations – auto-discover member accounts
# ------------------------------------------------------------------ #

def discover_org_accounts():
    """
    Use the currently-active account (must be Org master/delegated admin)
    to list all member accounts.  Returns list of dicts.
    """
    session = get_session()
    if not session:
        return [], "No active account"
    try:
        orgs = session.client("organizations")
        paginator = orgs.get_paginator("list_accounts")
        accounts = []
        for page in paginator.paginate():
            for a in page["Accounts"]:
                accounts.append({
                    "aws_account_id": a["Id"],
                    "name": a.get("Name", ""),
                    "email": a.get("Email", ""),
                    "status": a.get("Status", ""),
                    "joined": a.get("JoinedTimestamp", ""),
                    "already_added": any(
                        x["aws_account_id"] == a["Id"] for x in list_accounts()
                    ),
                })
        return accounts, None
    except Exception as e:
        return [], str(e)


# ------------------------------------------------------------------ #
#  Session factory – used by every service module
# ------------------------------------------------------------------ #

def get_session(account_id=None):
    """
    Build a boto3 Session for the given (or active) account.
    Supports IAM-role assumption and access-key auth.
    """
    acct = get_account(account_id) if account_id else get_active_account()
    if not acct:
        return _fallback_session()

    region = acct.get("region") or Config.AWS_REGION

    if acct["auth_type"] == "iam_role" and acct.get("role_arn"):
        return _assume_role_session(acct["role_arn"], acct.get("external_id", ""), region)
    elif acct["auth_type"] == "access_key" and acct.get("access_key_id"):
        return boto3.Session(
            aws_access_key_id=acct["access_key_id"],
            aws_secret_access_key=acct["secret_access_key"],
            region_name=region,
        )
    else:
        return _fallback_session()


def _assume_role_session(role_arn, external_id, region):
    """Assume a cross-account IAM role and return a session."""
    sts = boto3.client("sts")
    params = {
        "RoleArn": role_arn,
        "RoleSessionName": "AWSCostOptimizer",
        "DurationSeconds": 3600,
    }
    if external_id:
        params["ExternalId"] = external_id
    creds = sts.assume_role(**params)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def _fallback_session():
    """Session from env vars / instance profile (single-account fallback)."""
    kwargs = {"region_name": Config.AWS_REGION}
    if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = Config.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = Config.AWS_SECRET_ACCESS_KEY
    return boto3.Session(**kwargs)


# ------------------------------------------------------------------ #
#  Connection tester
# ------------------------------------------------------------------ #

def test_connection(acct):
    """
    Verify we can authenticate and identify the account.
    Returns (success: bool, message: str).
    """
    try:
        region = acct.get("region") or Config.AWS_REGION

        if acct["auth_type"] == "iam_role" and acct.get("role_arn"):
            session = _assume_role_session(acct["role_arn"], acct.get("external_id", ""), region)
        elif acct["auth_type"] == "access_key" and acct.get("access_key_id"):
            session = boto3.Session(
                aws_access_key_id=acct["access_key_id"],
                aws_secret_access_key=acct["secret_access_key"],
                region_name=region,
            )
        else:
            return False, "No valid credentials configured"

        sts = session.client("sts")
        identity = sts.get_caller_identity()
        return True, f"Authenticated as {identity['Arn']} (Account {identity['Account']})"

    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------ #
#  CloudFormation template body (for easy IAM role setup)
# ------------------------------------------------------------------ #

EXTERNAL_ID_DEFAULT = "AWSCostOptimizer-" + str(uuid.uuid4())[:8]

def get_cloudformation_template(trusted_account_id=None, external_id=None):
    """Return a CF template string that creates a read-only cross-account role."""
    external_id = external_id or EXTERNAL_ID_DEFAULT
    # Determine the caller's own account ID to set as trusted principal
    if not trusted_account_id:
        try:
            sts = boto3.client("sts")
            trusted_account_id = sts.get_caller_identity()["Account"]
        except Exception:
            trusted_account_id = "REPLACE_WITH_YOUR_MANAGEMENT_ACCOUNT_ID"

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "AWS Cost Optimizer – Cross-account read-only IAM role",
        "Parameters": {
            "ExternalId": {
                "Type": "String",
                "Default": external_id,
                "Description": "External ID for secure role assumption",
            },
            "TrustedAccountId": {
                "Type": "String",
                "Default": trusted_account_id,
                "Description": "AWS Account ID of the cost optimizer host",
            },
        },
        "Resources": {
            "CostOptimizerRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": "AWSCostOptimizerReadOnly",
                    "AssumeRolePolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": {"Fn::Sub": "arn:aws:iam::${TrustedAccountId}:root"}
                            },
                            "Action": "sts:AssumeRole",
                            "Condition": {
                                "StringEquals": {
                                    "sts:ExternalId": {"Ref": "ExternalId"}
                                }
                            },
                        }],
                    },
                    "ManagedPolicyArns": [
                        "arn:aws:iam::aws:policy/ReadOnlyAccess",
                    ],
                    "Policies": [{
                        "PolicyName": "CostExplorerAccess",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [{
                                "Effect": "Allow",
                                "Action": [
                                    "ce:*",
                                    "cur:Describe*",
                                    "savingsplans:Describe*",
                                    "savingsplans:List*",
                                    "support:DescribeTrustedAdvisor*",
                                    "organizations:ListAccounts",
                                    "organizations:DescribeOrganization",
                                ],
                                "Resource": "*",
                            }],
                        },
                    }],
                },
            },
        },
        "Outputs": {
            "RoleArn": {
                "Description": "ARN of the cross-account role",
                "Value": {"Fn::GetAtt": ["CostOptimizerRole", "Arn"]},
            },
            "ExternalId": {
                "Description": "External ID to configure in the optimizer",
                "Value": {"Ref": "ExternalId"},
            },
        },
    }
    return json.dumps(template, indent=2)
