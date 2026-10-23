"""Run a shell script on the Gaffer instance via SSM Run Command and print its output.

    python ssm_run.py <instance id> <timeout s> <script file>

Uses the laptop's default AWS credentials (boto3 default chain); nothing is printed but the
command's own stdout / stderr and status.
"""
import sys
import time

import boto3

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

iid, timeout, script = sys.argv[1], int(sys.argv[2]), open(sys.argv[3], encoding="utf-8").read()
ssm = boto3.client("ssm", region_name="ap-southeast-2")
cmd = ssm.send_command(InstanceIds=[iid], DocumentName="AWS-RunShellScript",
                       Parameters={"commands": [script], "executionTimeout": [str(timeout)]},
                       TimeoutSeconds=60)
cid = cmd["Command"]["CommandId"]
t0 = time.time()
while True:
    time.sleep(5)
    try:
        r = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
    except ssm.exceptions.InvocationDoesNotExist:
        continue
    if r["Status"] not in ("Pending", "InProgress", "Delayed"):
        break
print(f"[{r['Status']} exit={r['ResponseCode']} {time.time() - t0:.0f}s command={cid}]")
print(r["StandardOutputContent"])
if r["StandardErrorContent"].strip():
    print("--- stderr ---")
    print(r["StandardErrorContent"][-6000:])
sys.exit(0 if r["Status"] == "Success" else 1)
