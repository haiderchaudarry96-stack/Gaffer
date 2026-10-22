# ruff: noqa: E501  (one IAM statement per line reads better than wrapped JSON)
r"""Write the three Gaffer IAM JSON documents for one AWS account (deploy/DEPLOY_AWS.md, step 1).

    py deploy\aws\make_iam_policies.py <account id> outputs\aws_iam

gaffer-dev-deploy-policy.json -> managed policy GafferDeploy on the laptop user Gaffer-dev;
gaffer-ec2-role-policy.json   -> inline policy GafferEc2Access on role gaffer-ec2-role
                                 (+ AWS managed AmazonSSMManagedInstanceCore);
gaffer-ec2-trust.json         -> trust policy of that role (the console writes the same one).
"""
import json
import sys
from pathlib import Path

A, R = sys.argv[1], "ap-southeast-2"
OUT = Path(sys.argv[2])
B = f"gaffer-demo-{A}"
TYPES = ["t4g.large", "c7g.large", "c7g.xlarge", "m7i-flex.large", "c7i-flex.large"]
LG = [f"arn:aws:logs:{R}:{A}:log-group:/gaffer/app", f"arn:aws:logs:{R}:{A}:log-group:/gaffer/app:*"]
TAG = {"aws:ResourceTag/Project": "gaffer"}
REQ_TAG = {"aws:RequestTag/Project": "gaffer"}
IN_REGION = {"StringEquals": {"aws:RequestedRegion": R}}


def st(sid, action, resource, cond=None):
    s = {"Sid": sid, "Effect": "Allow", "Action": action, "Resource": resource}
    if cond:
        s["Condition"] = cond
    return s


deploy = [
    st("Ec2ReadSydney", "ec2:Describe*", "*", IN_REGION),
    st("RunOnlyAllowedTypesTagged", "ec2:RunInstances", f"arn:aws:ec2:{R}:{A}:instance/*",
       {"StringEquals": REQ_TAG, "ForAllValues:StringEquals": {"ec2:InstanceType": TYPES}}),
    st("RunInstancesOtherResources", "ec2:RunInstances",
       [f"arn:aws:ec2:{R}:{A}:volume/*", f"arn:aws:ec2:{R}:{A}:network-interface/*",
        f"arn:aws:ec2:{R}:{A}:security-group/*", f"arn:aws:ec2:{R}:{A}:subnet/*",
        f"arn:aws:ec2:{R}::image/*"]),
    st("TagOnlyOnCreate", "ec2:CreateTags", f"arn:aws:ec2:{R}:{A}:*/*",
       {"StringEquals": {"ec2:CreateAction": ["RunInstances", "CreateSecurityGroup", "AllocateAddress"]}}),
    st("CreateTaggedSecurityGroup", "ec2:CreateSecurityGroup", f"arn:aws:ec2:{R}:{A}:security-group/*",
       {"StringEquals": REQ_TAG}),
    st("CreateSecurityGroupInVpc", "ec2:CreateSecurityGroup", f"arn:aws:ec2:{R}:{A}:vpc/*"),
    st("ManageGafferSecurityGroup",
       ["ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress", "ec2:DeleteSecurityGroup"],
       f"arn:aws:ec2:{R}:{A}:security-group/*", {"StringEquals": TAG}),
    st("AllocateTaggedElasticIp", "ec2:AllocateAddress", f"arn:aws:ec2:{R}:{A}:elastic-ip/*",
       {"StringEquals": REQ_TAG}),
    st("ManageGafferElasticIp", ["ec2:AssociateAddress", "ec2:DisassociateAddress", "ec2:ReleaseAddress"],
       [f"arn:aws:ec2:{R}:{A}:elastic-ip/*", f"arn:aws:ec2:{R}:{A}:instance/*",
        f"arn:aws:ec2:{R}:{A}:network-interface/*"],
       {"StringEqualsIfExists": TAG}),
    st("OperateGafferInstanceOnly",
       ["ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances", "ec2:TerminateInstances",
        "ec2:ModifyInstanceAttribute", "ec2:ModifyInstanceMetadataOptions"],
       f"arn:aws:ec2:{R}:{A}:instance/*",
       {"StringEquals": TAG, "ForAllValues:StringEqualsIfExists": {"ec2:Attribute/InstanceType": TYPES}}),
    st("PassOnlyTheGafferRole", "iam:PassRole", f"arn:aws:iam::{A}:role/gaffer-ec2-role",
       {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}),
    st("ReadTheGafferRole",
       ["iam:GetRole", "iam:GetInstanceProfile", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies",
        "iam:GetRolePolicy"],
       [f"arn:aws:iam::{A}:role/gaffer-ec2-role", f"arn:aws:iam::{A}:instance-profile/gaffer-ec2-role"]),
    st("AmazonLinuxAmiLookup", ["ssm:GetParameter", "ssm:GetParameters"],
       f"arn:aws:ssm:{R}::parameter/aws/service/ami-amazon-linux-latest/*"),
    st("RunShellOnGafferInstanceOnly", "ssm:SendCommand", f"arn:aws:ec2:{R}:{A}:instance/*",
       {"StringEquals": {"ssm:resourceTag/Project": "gaffer"}}),
    st("RunShellDocument", "ssm:SendCommand", f"arn:aws:ssm:{R}::document/AWS-RunShellScript"),
    st("ReadCommandResults",
       ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations", "ssm:ListCommands",
        "ssm:DescribeInstanceInformation"], "*", IN_REGION),
    st("TheOneGafferBucket",
       ["s3:CreateBucket", "s3:DeleteBucket", "s3:ListBucket", "s3:GetBucketLocation",
        "s3:PutBucketPublicAccessBlock", "s3:GetBucketPublicAccessBlock",
        "s3:PutEncryptionConfiguration", "s3:GetEncryptionConfiguration",
        "s3:PutBucketOwnershipControls", "s3:GetBucketOwnershipControls", "s3:PutBucketTagging"],
       f"arn:aws:s3:::{B}"),
    st("TheOneGafferBucketObjects", ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
       f"arn:aws:s3:::{B}/*"),
    st("TheOneLogGroup",
       ["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:PutMetricFilter",
        "logs:DeleteMetricFilter", "logs:DescribeMetricFilters", "logs:DescribeLogStreams",
        "logs:GetLogEvents", "logs:FilterLogEvents", "logs:TagResource"], LG),
    st("ListLogGroups", "logs:DescribeLogGroups", f"arn:aws:logs:{R}:{A}:log-group:*"),
    st("ReadMetrics", ["cloudwatch:GetMetricStatistics", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics"],
       "*", IN_REGION),
    st("ReadTheBudget", "budgets:ViewBudget", f"arn:aws:budgets::{A}:budget/gaffer-budget"),
]

L = f"arn:aws:bedrock:{R}:{A}:inference-profile/global.amazon.nova-2-lite-v1:0"
M = f"arn:aws:bedrock:{R}:{A}:inference-profile/apac.amazon.nova-micro-v1:0"
INV = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
role = [
    st("NovaLiteGlobalProfile", INV, L, IN_REGION),
    st("NovaLiteInSydney", INV, f"arn:aws:bedrock:{R}::foundation-model/amazon.nova-2-lite-v1:0",
       {"StringEquals": {"aws:RequestedRegion": R, "bedrock:InferenceProfileArn": L}}),
    st("NovaLiteGlobalRouting", INV, "arn:aws:bedrock:::foundation-model/amazon.nova-2-lite-v1:0",
       {"StringEquals": {"aws:RequestedRegion": "unspecified", "bedrock:InferenceProfileArn": L}}),
    st("NovaMicroApacProfile", INV, M),
    st("NovaMicroApacRouting", INV, "arn:aws:bedrock:ap-*::foundation-model/amazon.nova-micro-v1:0",
       {"StringEquals": {"bedrock:InferenceProfileArn": M}}),
    st("GafferBucketList", "s3:ListBucket", f"arn:aws:s3:::{B}"),
    st("GafferBucketReadWrite", ["s3:GetObject", "s3:PutObject"], f"arn:aws:s3:::{B}/*"),
    st("GafferLogGroupWrite", ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"], LG),
]
trust = [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]

OUT.mkdir(parents=True, exist_ok=True)
for name, stmts in [("gaffer-dev-deploy-policy.json", deploy), ("gaffer-ec2-role-policy.json", role),
                    ("gaffer-ec2-trust.json", trust)]:
    text = json.dumps({"Version": "2012-10-17", "Statement": stmts}, indent=2)
    (OUT / name).write_text(text + "\n", encoding="utf-8")
    print(name, len(json.dumps({"Version": "2012-10-17", "Statement": stmts}, separators=(",", ":"))),
          "chars (minified)")
